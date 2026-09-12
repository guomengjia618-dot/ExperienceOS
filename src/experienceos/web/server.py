# ruff: noqa: RUF001
"""Loopback-only HTTP workbench. No extra web framework or database required."""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
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
from experienceos.config import load_config, save_config
from experienceos.core.errors import (
    AIProviderError,
    ExperienceOSError,
    ExportError,
    NotFoundError,
)
from experienceos.core.models import UNDATED_START, Experience, utcnow
from experienceos.core.ulid import new_ulid
from experienceos.exporters import default_exporter_registry
from experienceos.exporters.base import ExportOptions
from experienceos.storage import ExperienceStore
from experienceos.web.demo import DEMO_QUESTION, WorkbenchDemoProvider, seed_demo

_RUN_ID = re.compile(r"^run_[0-9A-HJKMNP-TV-Z]{26}$")
_MODEL = re.compile(r"^[A-Za-z0-9._/\-:]{1,100}$")
_STATIC = Path(__file__).parent / "static"
_MIME_BY_SUFFIX = {
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}
# Same-family suggestions for the model picker; the host of the configured
# base_url decides which family applies. Always merged with the current model.
_SUGGESTED_MODELS = {
    "bigmodel.cn": ["glm-4.7", "glm-4.6-air", "glm-4-plus", "glm-4.5-air"],
    "deepseek.com": ["deepseek-chat", "deepseek-reasoner"],
    "openai.com": ["gpt-4o-mini", "gpt-4o"],
    "moonshot.cn": ["moonshot-v1-8k", "moonshot-v1-32k"],
    "dashscope.aliyuncs.com": ["qwen-plus", "qwen-max"],
}
# Transport error classification -> a plain-language pause reason. These
# strings are operational metadata from the retry layer, never model content.
_PAUSE_REASONS = {
    "network": (
        "连不上模型接口（网络被拒绝或中断），已自动重试仍未成功。"
        "网络恢复后点「继续运行」，将从断点接着跑，已完成的步骤不会重来。"
    ),
    "timeout": "模型接口响应超时，已自动重试仍未成功。稍后点「继续运行」从断点接着跑。",
    "rate_limit": "模型接口限流（请求太频繁或额度用尽），稍等片刻再点「继续运行」。",
    "server_error": "模型服务暂时故障（服务端 5xx），稍后点「继续运行」。",
    "invalid_json": (
        "模型返回了无法解析的内容，且修复重试后仍未通过校验。"
        "换一个模型或换个问法再试。"
    ),
    "http_error": "模型接口拒绝了请求（鉴权或参数问题），请检查 key 与配置后重试。",
}


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["demo", "live"] = "demo"
    question: str = Field(default=DEMO_QUESTION, min_length=1, max_length=4000)
    simulate_failure: StrictBool = False


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "other"
    location: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=2000)


class PeriodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str | None = None
    end: str | None = None


class RecordUpsert(BaseModel):
    """The visually editable surface of a record. Identity, provenance and
    timestamps are system-owned and never accepted from the form."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    type: str = "personal"
    status: Literal["draft", "active", "archived"] = "active"
    period: PeriodIn = PeriodIn()
    context: str = Field(default="", max_length=4000)
    role: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=8000)
    technology: list[str] = Field(default_factory=list, max_length=100)
    contribution: list[str] = Field(default_factory=list, max_length=100)
    challenge: list[str] = Field(default_factory=list, max_length=100)
    solution: list[str] = Field(default_factory=list, max_length=100)
    result: list[str] = Field(default_factory=list, max_length=100)
    reflection: str = Field(default="", max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=100)

    def to_domain(self) -> dict[str, Any]:
        period = dict(self.period.model_dump())
        period.setdefault("start", None)
        if not period["start"]:
            period["start"] = UNDATED_START
        return {
            "title": self.title,
            "type": self.type,
            "status": self.status,
            "period": period,
            "context": self.context,
            "role": self.role,
            "description": self.description,
            "technology": self.technology,
            "contribution": self.contribution,
            "challenge": self.challenge,
            "solution": self.solution,
            "result": self.result,
            "reflection": self.reflection,
            "tags": self.tags,
            "evidence": [e.model_dump() for e in self.evidence],
        }


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

    # -- record management (visual surface of the CLI's human-in-the-loop) --

    def _local_store(self, mode: str) -> ExperienceStore:
        if mode != "live":
            raise RequestError(
                "演示数据是合成示例，只读。切换到「在线」即可管理真实经历。", 403
            )
        return self.store("live")

    def create_record(self, mode: str, data: RecordUpsert) -> dict[str, Any]:
        store = self._local_store(mode)
        fields = data.to_domain()
        fields["source"] = {"origin": "manual", "created_by": "user"}
        try:
            experience = Experience.new(**fields)
        except (ValidationError, ValueError) as exc:
            raise RequestError(self._validation_message(exc)) from exc
        store.save(experience)
        return experience.model_dump(mode="json")

    def update_record(self, mode: str, record_id: str, data: RecordUpsert) -> dict[str, Any]:
        store = self._local_store(mode)
        existing = self._load(store, record_id)
        merged = existing.model_dump(mode="json")
        merged.update(data.to_domain())
        merged["id"] = existing.id
        merged["source"] = existing.source.model_dump(mode="json")
        try:
            updated = Experience.model_validate(merged)
        except (ValidationError, ValueError) as exc:
            raise RequestError(self._validation_message(exc)) from exc
        store.save(updated)
        return updated.model_dump(mode="json")

    def delete_record(self, mode: str, record_id: str) -> None:
        store = self._local_store(mode)
        if not store.delete(self._resolve(store, record_id)):
            raise RequestError("找不到这条经历。", 404)

    def change_status(self, mode: str, record_id: str, status: str) -> None:
        store = self._local_store(mode)
        existing = self._load(store, record_id)
        merged = existing.model_dump(mode="json")
        merged["status"] = status
        try:
            updated = Experience.model_validate(merged)
        except (ValidationError, ValueError) as exc:
            raise RequestError(self._validation_message(exc)) from exc
        store.save(updated)

    @staticmethod
    def _resolve(store: ExperienceStore, record_id: str) -> str:
        try:
            return store.resolve(record_id)
        except NotFoundError as exc:
            raise RequestError("找不到这条经历。", 404) from exc

    @classmethod
    def _load(cls, store: ExperienceStore, record_id: str) -> Experience:
        try:
            return store.load(cls._resolve(store, record_id))
        except ExperienceOSError as exc:
            raise RequestError(
                "记录文件无法读取，请先运行 experienceos validate 检查。", 409
            ) from exc

    def export(self, mode: str, name: str) -> tuple[bytes, str, str]:
        """Render an export artifact for download; active records only —
        drafts never leak, matching the CLI's default."""
        self._local_store(mode)
        exporter = default_exporter_registry.get(name)
        records = [r for r in self.store("live").list_all() if r.status.value == "active"]
        suffix = f".{exporter.suffix}"
        fd, raw = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            target = exporter.export(records, Path(raw), ExportOptions())
            body = target.read_bytes()
        finally:
            with contextlib.suppress(OSError):  # best-effort cleanup
                os.unlink(raw)
        disposition = f"experienceos-export-{name}{suffix}"
        return body, _MIME_BY_SUFFIX.get(suffix, "application/octet-stream"), disposition

    @staticmethod
    def _validation_message(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
            return f"字段不合法：{location or '表单'} — {first.get('msg', '')}"
        return "表单内容不合法，请检查后重试。"

    def configuration(self) -> dict[str, Any]:
        config = load_config(self.home).ai
        host = urlsplit(config.base_url).hostname or ""
        suggestions = next(
            (
                models
                for domain, models in _SUGGESTED_MODELS.items()
                if domain in host
            ),
            [],
        )
        return {
            "model": config.model,
            "provider": config.provider,
            "model_options": sorted({config.model, *suggestions}),
            "live_ready": bool(os.environ.get(config.api_key_env)),
            "api_key_env": config.api_key_env,
            "demo_question": DEMO_QUESTION,
        }

    def set_model(self, model: str) -> dict[str, Any]:
        """Switch the live model and persist it to config.toml."""
        if not _MODEL.fullmatch(model or ""):
            raise RequestError("模型名不合法：只允许字母、数字和 . _ / - :。")
        config = load_config(self.home)
        config.ai.model = model
        save_config(self.home, config)
        return self.configuration()

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
        except Exception as exc:
            # Model-content errors must stay off the wire; transport errors
            # are operational metadata and get a plain-language reason. The
            # workflow wraps provider failures, so walk the cause chain.
            reason = None
            candidate: BaseException | None = exc
            while candidate is not None and reason is None:
                if isinstance(candidate, AIProviderError) and isinstance(
                    candidate.metadata, dict
                ):
                    reason = _PAUSE_REASONS.get(str(candidate.metadata.get("error_type")))
                candidate = candidate.__cause__ or candidate.__context__
            with self.lock:
                run["status"] = "paused"
                run["error"] = reason or (
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
                if path == "/api/export":
                    query = parse_qs(parsed.query)
                    name = (query.get("name") or ["markdown"])[0]
                    mode = (query.get("mode") or ["live"])[0]
                    try:
                        body, mime, filename = workbench.export(mode, name)
                    except ExportError as exc:
                        raise RequestError(
                            "没有可导出的记录（默认只导出「正式」状态的经历）。"
                            "先新增或转正一条经历再导出。",
                            400,
                        ) from exc
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{filename}"'
                    )
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/runs":
                    return self._json(workbench.history())
                if path.startswith("/api/runs/"):
                    return self._json(workbench.view(path.removeprefix("/api/runs/")))
                raise RequestError("页面不存在。", 404)
            except RequestError as exc:
                self._json({"error": str(exc)}, exc.status)
            except Exception:
                self._json({"error": "无法读取本地数据，请检查配置与记录文件。"}, 500)

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get_content_type() != "application/json":
                raise RequestError("需要 JSON 请求。", 415)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                raise RequestError("请求为空或超过大小限制。", 413)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise RequestError("请求参数不正确。", 400)
            return data

        def do_POST(self) -> None:
            try:
                self._guard(api=True)
                data = self._read_json()
                path = urlsplit(self.path).path
                if path == "/api/experiences":
                    mode = parse_qs(urlsplit(self.path).query).get("mode", ["live"])[0]
                    result = workbench.create_record(
                        mode, RecordUpsert.model_validate(data)
                    )
                    self._json(result, 201)
                    return
                if path == "/api/model":
                    if data.keys() != {"model"} or not isinstance(data["model"], str):
                        raise RequestError("需要 model 字段。", 400)
                    return self._json(workbench.set_model(data["model"]))
                if path.startswith("/api/experiences/") and path.endswith("/status"):
                    if data.keys() != {"status"} or data["status"] not in {
                        "draft",
                        "active",
                        "archived",
                    }:
                        raise RequestError("状态不合法。", 400)
                    workbench.change_status(
                        parse_qs(urlsplit(self.path).query).get("mode", ["live"])[0],
                        path[len("/api/experiences/") : -len("/status")],
                        data["status"],
                    )
                    self._json({"ok": True})
                    return
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
                self._json({"error": "请求参数不正确。请检查表单内容。"}, 400)
            except Exception:
                self._json({"error": "操作未完成，请检查本地配置后重试。"}, 500)

        def do_PUT(self) -> None:
            try:
                self._guard(api=True)
                data = self._read_json()
                path = urlsplit(self.path).path
                if path.startswith("/api/experiences/"):
                    mode = parse_qs(urlsplit(self.path).query).get("mode", ["live"])[0]
                    result = workbench.update_record(
                        mode,
                        path.removeprefix("/api/experiences/"),
                        RecordUpsert.model_validate(data),
                    )
                    return self._json(result)
                raise RequestError("操作不存在。", 404)
            except RequestError as exc:
                self._json({"error": str(exc)}, exc.status)
            except (ValidationError, ValueError, UnicodeError):
                self._json({"error": "请求参数不正确。请检查表单内容。"}, 400)
            except Exception:
                self._json({"error": "操作未完成，请检查本地配置后重试。"}, 500)

        def do_DELETE(self) -> None:
            try:
                self._guard(api=True)
                parsed = urlsplit(self.path)
                if parsed.path.startswith("/api/experiences/"):
                    mode = parse_qs(parsed.query).get("mode", ["live"])[0]
                    workbench.delete_record(
                        mode, parsed.path.removeprefix("/api/experiences/")
                    )
                    return self._json({"ok": True})
                raise RequestError("操作不存在。", 404)
            except RequestError as exc:
                self._json({"error": str(exc)}, exc.status)
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
