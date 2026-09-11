"""Exercise the browser API, durable recovery and live-provider boundary."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.core.models import Experience
from experienceos.storage import ExperienceStore
from experienceos.web.demo import WorkbenchDemoProvider
from experienceos.web.server import RequestError, StartRequest, Workbench, make_server


def finish(workbench: Workbench, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = workbench.view(run_id)
        if not view["active"]:
            return view
        time.sleep(0.01)
    pytest.fail("workbench did not finish")


def test_demo_uses_tools_and_preserves_personal_store(tmp_path: Path):
    personal = Experience.new(
        title="Private project", type="personal", period={"start": "2024-01"}
    )
    store = ExperienceStore(tmp_path)
    path = store.save(personal)
    before = path.read_bytes()
    bench = Workbench(tmp_path, demo_delay=0)
    view = finish(bench, bench.start(StartRequest())["id"])
    assert view["status"] == "completed"
    assert len(view["output"]["citations"]) == 3
    assert len(view["output"]["evidence_gaps"]) == 1
    assert [e["name"] for e in view["events"]] == [
        "search_experiences",
        "get_experience",
        "get_experience",
        "get_experience",
        "get_evidence_stats",
    ]
    assert all("result" not in event for event in view["events"])
    assert view["report"]["total_tokens"] is None
    assert path.read_bytes() == before
    assert len(store.list_all()) == 1
    assert all(r.source.created_by == "ai:synthetic-demo" for r in bench.store("demo").list_all())


def test_resume_after_restart_does_not_repeat_tools(tmp_path: Path):
    first = Workbench(tmp_path, demo_delay=0)
    run_id = first.start(StartRequest(simulate_failure=True))["id"]
    paused = finish(first, run_id)
    assert paused["status"] == "paused" and paused["can_resume"]
    second = Workbench(tmp_path, demo_delay=0)
    assert second.history()[0]["id"] == run_id
    second.resume(run_id)
    completed = finish(second, run_id)
    assert completed["status"] == "completed"
    assert completed["events"] == paused["events"]
    assert completed["workflow_id"] == paused["workflow_id"]
    assert second.resume(run_id) == {"id": run_id}


def test_interrupted_running_state_can_resume(tmp_path: Path):
    bench = Workbench(tmp_path, demo_delay=0)
    run_id = bench.start(StartRequest(simulate_failure=True))["id"]
    finish(bench, run_id)
    manifest = bench._read(run_id)
    manifest.update(status="running", error=None)
    bench._write(manifest)
    restarted = Workbench(tmp_path, demo_delay=0)
    assert restarted.view(run_id)["status"] == "paused"
    assert restarted.view(run_id)["can_resume"]
    restarted.resume(run_id)
    assert finish(restarted, run_id)["status"] == "completed"


def test_conflicting_start_and_resume_rejected(tmp_path: Path):
    bench = Workbench(tmp_path, demo_delay=0.1)
    run_id = bench.start(StartRequest())["id"]
    with pytest.raises(RequestError) as error:
        bench.start(StartRequest())
    assert error.value.status == 409
    with pytest.raises(RequestError):
        bench.resume(run_id)
    assert finish(bench, run_id)["status"] == "completed"


def test_live_uses_configured_factory_and_personal_records(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-do-not-expose")
    store = ExperienceStore(tmp_path)
    personal = Experience.new(
        title="Live record",
        type="personal",
        period={"start": "2024-02"},
        result=["Existing result"],
    )
    store.save(personal)
    calls = []

    def factory(config):
        calls.append(config)
        return WorkbenchDemoProvider(delay=0)

    monkeypatch.setattr("experienceos.web.server.create_provider", factory)
    bench = Workbench(tmp_path, demo_delay=0)
    result = finish(bench, bench.start(StartRequest(mode="live", question="Find my result"))["id"])
    assert calls and result["status"] == "completed"
    assert result["output"]["citations"][0]["experience_id"] == personal.id
    assert "test-secret-do-not-expose" not in json.dumps(bench.configuration())
    assert "test-secret-do-not-expose" not in json.dumps(result)
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(RequestError):
        bench.start(StartRequest(mode="live"))


@pytest.fixture
def http_workbench(tmp_path):
    bench = Workbench(tmp_path, demo_delay=0)
    server = make_server(bench, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield bench, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(base, path, data=None, headers=None):
    values = {"X-ExperienceOS": "workbench", **(headers or {})}
    body = None if data is None else json.dumps(data).encode()
    if body is not None:
        values.setdefault("Content-Type", "application/json")
    req = Request(base + path, data=body, headers=values)
    try:
        response = urlopen(req, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def test_http_full_workflow_and_assets(http_workbench):
    bench, base = http_workbench
    for path in ("/", "/app.js", "/style.css"):
        status, headers, body = request(base, path)
        assert status == 200 and body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert len(json.loads(request(base, "/api/experiences?mode=demo")[2])) == 3
    assert json.loads(request(base, "/api/experiences?mode=live")[2]) == []
    status, _, body = request(base, "/api/runs", {"mode": "demo", "simulate_failure": True})
    assert status == 202
    run_id = json.loads(body)["id"]
    assert finish(bench, run_id)["status"] == "paused"
    assert request(base, f"/api/runs/{run_id}/resume", {})[0] == 202
    finish(bench, run_id)
    result = json.loads(request(base, f"/api/runs/{run_id}")[2])
    assert result["status"] == "completed"
    assert "messages" not in result and "last_error" not in result
    assert json.loads(request(base, "/api/runs")[2])[0]["id"] == run_id


@pytest.mark.parametrize(
    ("path", "data", "headers", "status"),
    [
        ("/api/config", None, {"Origin": "https://untrusted.example"}, 403),
        ("/api/config", None, {"Host": "untrusted.example"}, 403),
        ("/api/config", None, {"X-ExperienceOS": ""}, 403),
        ("/api/runs", {}, {"Origin": "null"}, 403),
        ("/api/runs", {}, {"Content-Type": "text/plain"}, 415),
        ("/api/runs", {"mode": "unknown"}, {}, 400),
        ("/api/runs", {"question": " "}, {}, 400),
        ("/api/runs", {"question": "x" * 4001}, {}, 400),
        ("/api/runs", {"simulate_failure": "false"}, {}, 400),
        ("/api/runs/../../config.toml", None, {}, 404),
        ("/../config.toml", None, {}, 404),
        ("/api/experiences?mode=invalid", None, {}, 400),
    ],
)
def test_http_rejects_cross_site_and_invalid_input(http_workbench, path, data, headers, status):
    _, base = http_workbench
    assert request(base, path, data, headers)[0] == status


def test_cli_web_reuses_selected_home(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "experienceos.web.server.serve", lambda home, port: calls.append((home, port))
    )
    result = CliRunner().invoke(app, ["--home", str(tmp_path), "web", "--port", "18765"])
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path, 18765)]
