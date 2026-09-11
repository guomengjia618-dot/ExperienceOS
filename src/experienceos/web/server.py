# ruff: noqa: RUF001
"""Loopback-only HTTP workbench. No extra web framework or database required."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from experienceos.ai.factory import create_provider
from experienceos.ai.reporting import build_run_report, save_run_report
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.ai.workflow import EvidenceBriefWorkflow, WorkflowCheckpointStore, WorkflowState
from experienceos.config import load_config
from experienceos.core.models import utcnow
from experienceos.core.ulid import new_ulid
from experienceos.storage import ExperienceStore
from experienceos.web.demo import DEMO_QUESTION, WorkbenchDemoProvider, seed_demo

_RUN_ID = re.compile(r"^run_[0-9A-HJKMNP-TV-Z]{26}$")
_STATIC = Path(__file__).parent / "static"


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["demo", "live"] = "demo"
    question: str = Field(default=DEMO_QUESTION, min_length=1, max_length=4000)
    simulate_failure: StrictBool = False


class ObservedCheckpoints(WorkflowCheckpointStore):
    def __init__(self, root: Path, on_save: Callable[[WorkflowState], None], lock: Any):
        super().__init__(root)
        self.on_save = on_save
        self.lock = lock

    def save(self, state: WorkflowState) -> Path:
        # Windows file replacement must not race a polling reader.
        with self.lock:
            path = super().save(state)
            self.on_save(state)
            return path


class Workbench:
    """One active run per process; manifests and workflow checkpoints survive restart."""

    def __init__(self, home: Path, *, demo_delay: float = 0.35):
        self.home = Path(home).resolve()
        self.directory = self.home / "workbench" / "runs"
        self.demo_home = self.home / "workbench" / "demo"
        self.demo_delay = demo_delay
        self.lock = threading.RLock()
        self.active_id: str | None = None
        self.directory.mkdir(parents=True, exist_ok=True)
        seed_demo(ExperienceStore(self.demo_home))

    def store(self, mode: str) -> ExperienceStore:
        if mode not in {"demo", "live"}:
            raise RequestError("请选择离线演示或真实模型。")
        return ExperienceStore(self.demo_home if mode == "demo" else self.home)

    def configuration(self) -> dict[str, Any]:
        config = load_config(self.home).ai
        return {
            "model": config.model,
            "provider": config.provider,
            "live_ready": bool(os.environ.get(config.api_key_env)),
            "api_key_env": config.api_key_env,
            "demo_question": DEMO_QUESTION,
        }

    def _path(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise RequestError("找不到这次运行。", 404)
        return self.directory / f"{run_id}.json"

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.exists():
            raise RequestError("找不到这次运行。", 404)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, run: dict[str, Any]) -> None:
        target = self._path(run["id"])
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)

    def start(self, request: StartRequest) -> dict[str, Any]:
        if not request.question.strip():
            raise RequestError("请先输入问题。")
        if request.mode == "live":
            if request.simulate_failure:
                raise RequestError("中断演示仅适用于离线模式。")
            if not self.configuration()["live_ready"]:
                raise RequestError("尚未配置模型密钥。请在启动服务的环境中设置后重启。")
            if not self.store("live").list_all():
                raise RequestError("经历库为空，请先通过命令行新增或导入经历。")
        with self.lock:
            if self.active_id:
                raise RequestError("已有任务运行中，请等待完成。", 409)
            run = {
                "id": f"run_{new_ulid()}",
                "mode": request.mode,
                "question": DEMO_QUESTION if request.mode == "demo" else request.question.strip(),
                "simulate_failure": request.simulate_failure,
                "created_at": utcnow().isoformat(),
                "workflow_id": None,
                "status": "queued",
                "error": None,
            }
            self._write(run)
            self._launch(run, resume=False)
            return {"id": run["id"]}

    def resume(self, run_id: str) -> dict[str, Any]:
        with self.lock:
            if self.active_id:
                raise RequestError("已有任务运行中，请等待完成。", 409)
            run = self._read(run_id)
            if not run["workflow_id"]:
                raise RequestError("尚未生成检查点，请重新开始。")
            state = WorkflowCheckpointStore(self.store(run["mode"]).root).load(run["workflow_id"])
            if state.status == "completed":
                return {"id": run_id}
            if run["mode"] == "live" and not self.configuration()["live_ready"]:
                raise RequestError("请先配置模型密钥再继续。")
            run.update(status="queued", error=None)
            self._write(run)
            self._launch(run, resume=True)
            return {"id": run_id}

    def _launch(self, run: dict[str, Any], *, resume: bool) -> None:
        self.active_id = run["id"]
        threading.Thread(target=self._execute, args=(run, resume), daemon=True).start()

    def _execute(self, run: dict[str, Any], resume: bool) -> None:
        def on_save(state: WorkflowState) -> None:
            with self.lock:
                run.update(workflow_id=state.workflow_id, status=state.status)
                self._write(run)

        store = self.store(run["mode"])
        checkpoints = ObservedCheckpoints(store.root, on_save, self.lock)
        try:
            provider = (
                WorkbenchDemoProvider(
                    fail_after_tools=run["simulate_failure"] and not resume,
                    delay=self.demo_delay,
                )
                if run["mode"] == "demo"
                else create_provider(load_config(self.home).ai)
            )
            workflow = EvidenceBriefWorkflow(
                provider=provider,
                tools=ExperienceToolRegistry(store),
                checkpoints=checkpoints,
            )
            state = (
                workflow.resume(run["workflow_id"]) if resume else workflow.start(run["question"])
            )
            save_run_report(state, store.root / "reports" / f"{state.workflow_id}.json")
        except Exception:
            # Provider exceptions may contain private content. Keep raw errors off the web API.
            with self.lock:
                run["status"] = "paused"
                run["error"] = (
                    "演示已在工具读取后中断。点击继续运行，将从保存的进度接着完成。"
                    if run["mode"] == "demo" and run["simulate_failure"] and not resume
                    else "运行中断。请检查模型配置、网络或本地记录，再从已保存的进度继续。"
                )
                self._write(run)
        finally:
            with self.lock:
                self.active_id = None

    def view(self, run_id: str) -> dict[str, Any]:
        with self.lock:
            run = self._read(run_id)
            active = self.active_id == run_id
            if run["status"] in {"queued", "running"} and not active:
                run.update(status="paused", error="服务曾中断，可从保存的进度继续。")
            result = {**run, "active": active, "events": [], "output": None, "report": None}
            if run["workflow_id"]:
                state = WorkflowCheckpointStore(self.store(run["mode"]).root).load(
                    run["workflow_id"]
                )
                result["events"] = [
                    event.model_dump(mode="json", exclude={"result"}) for event in state.tool_events
                ]
                result["output"] = state.output.model_dump() if state.output else None
                result["report"] = build_run_report(state).model_dump(mode="json")
                if state.status == "completed":
                    result["status"] = "completed"
                elif active and state.status != "paused":
                    result["status"] = state.status
            result["can_resume"] = bool(
                run["workflow_id"] and not active and result["status"] == "paused"
            )
            return result

    def history(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.directory.glob("run_*.json"), reverse=True)[:30]:
            try:
                view = self.view(path.stem)
                items.append(
                    {
                        key: view[key]
                        for key in ("id", "mode", "question", "status", "created_at", "active")
                    }
                )
            except (ValueError, OSError):
                continue
        return items


def make_server(workbench: Workbench, port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Local questions and identifiers do not belong in access logs.

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value: Any, status: int = 200) -> None:
            self._send(
                status,
                json.dumps(value, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )

        def _guard(self, *, api: bool) -> None:
            authority = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != authority:
                raise RequestError("仅允许从本机工作台访问。", 403)
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{authority}":
                raise RequestError("不允许跨站请求。", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise RequestError("不允许跨站请求。", 403)
            if api and self.headers.get("X-ExperienceOS") != "workbench":
                raise RequestError("请通过工作台访问。", 403)

        def do_GET(self) -> None:
            try:
                parsed = urlsplit(self.path)
                path = parsed.path
                self._guard(api=path.startswith("/api/"))
                assets = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }
                if path in assets:
                    name, mime = assets[path]
                    return self._send(200, (_STATIC / name).read_bytes(), mime)
                if path == "/api/config":
                    return self._json(workbench.configuration())
                if path == "/api/experiences":
                    mode = parse_qs(parsed.query).get("mode", ["demo"])[0]
                    return self._json(
                        [r.model_dump(mode="json") for r in workbench.store(mode).list_all()]
                    )
                if path == "/api/runs":
                    return self._json(workbench.history())
                if path.startswith("/api/runs/"):
                    return self._json(workbench.view(path.removeprefix("/api/runs/")))
                raise RequestError("页面不存在。", 404)
            except RequestError as exc:
                self._json({"error": str(exc)}, exc.status)
            except Exception:
                self._json({"error": "无法读取本地数据，请检查配置与记录文件。"}, 500)

        def do_POST(self) -> None:
            try:
                self._guard(api=True)
                if self.headers.get_content_type() != "application/json":
                    raise RequestError("需要 JSON 请求。", 415)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise RequestError("请求为空或超过大小限制。", 413)
                data = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/runs":
                    result = workbench.start(StartRequest.model_validate(data))
                elif path.startswith("/api/runs/") and path.endswith("/resume"):
                    if data != {}:
                        raise RequestError("继续运行不接受额外参数。")
                    result = workbench.resume(path[len("/api/runs/") : -len("/resume")])
                else:
                    raise RequestError("操作不存在。", 404)
                self._json(result, 202)
            except RequestError as exc:
                self._json({"error": str(exc)}, exc.status)
            except (ValidationError, ValueError, UnicodeError):
                self._json({"error": "请求参数不正确。问题须为 1–4000 个字符。"}, 400)
            except Exception:
                self._json({"error": "操作未完成，请检查本地配置后重试。"}, 500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(home: Path, port: int = 8765) -> None:
    server = make_server(Workbench(home), port)
    print(f"ExperienceOS 工作台：http://127.0.0.1:{server.server_port}", flush=True)
    print("按 Ctrl+C 关闭；运行记录保存在所选 home 的 workbench 目录。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
