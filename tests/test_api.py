"""FastAPI service tests (#018): httpx ASGI transport, no real port."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from httpx import ASGITransport, AsyncClient

from experienceos.api.app import create_app
from experienceos.storage import ExperienceStore


def call(app: Any, method: str, url: str, **kwargs: Any) -> Any:
    async def _run() -> Any:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(_run())


@pytest.fixture
def api(home, make_experience) -> Any:
    store = ExperienceStore(home)
    store.save(
        make_experience(
            title="Alpha Site",
            type="work",
            technology=["Python"],
            result=["40% faster"],
        )
    )
    store.save(make_experience(title="Beta Draft", status="draft"))
    return create_app(home=home)


def test_list_excludes_nothing_by_default(api: Any) -> None:
    response = call(api, "GET", "/experiences")
    assert response.status_code == 200
    data = response.json()
    assert {item["title"] for item in data} == {"Alpha Site", "Beta Draft"}


def test_list_status_filter(api: Any) -> None:
    response = call(api, "GET", "/experiences", params={"status": "active"})
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Alpha Site"]


def test_type_filter(api: Any) -> None:
    response = call(api, "GET", "/experiences", params={"type": "work"})
    assert response.status_code == 200
    assert {item["title"] for item in response.json()} == {"Alpha Site"}


def test_get_by_prefix(api: Any) -> None:
    listing = call(api, "GET", "/experiences").json()
    full_id = listing[0]["id"]
    # same-millisecond ULIDs share their timestamp prefix, so use all but
    # the last char to stay unique
    response = call(api, "GET", f"/experiences/{full_id[:-1]}")
    assert response.status_code == 200
    assert response.json()["id"] == full_id


def test_get_unknown_returns_404(api: Any) -> None:
    response = call(api, "GET", "/experiences/exp_does_not_exist")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower() or "not found" in str(
        response.json()
    )


def test_search_endpoint(api: Any) -> None:
    response = call(api, "GET", "/search", params={"text": "alpha"})
    assert response.status_code == 200
    assert any("Alpha" in item["title"] for item in response.json())


def test_stats_endpoint(api: Any) -> None:
    response = call(api, "GET", "/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["by_status"] == {"draft": 1, "active": 1}


def test_lint_endpoint(api: Any) -> None:
    response = call(api, "GET", "/lint")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["issues"][0]["sentence"] == "40% faster"
    assert "source=interview" in data["issues"][0]["suggestion"]


def test_create_draft_roundtrip(api: Any, home: Path) -> None:
    payload = {
        "title": "From The API",
        "type": "personal",
        "period": {"start": "2024-01"},
        "technology": ["Rust"],
    }
    response = call(api, "POST", "/experiences/drafts", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "draft"
    assert data["source"]["origin"] == "manual"
    assert data["source"]["created_by"] == "user"
    saved = ExperienceStore(home).list_all()
    assert any(exp.title == "From The API" for exp in saved)


def test_create_draft_rejects_active_claim(api: Any) -> None:
    payload = {
        "title": "Sneaky",
        "type": "work",
        "period": {"start": "2024-01"},
        "status": "active",
    }
    response = call(api, "POST", "/experiences/drafts", json=payload)
    assert response.status_code == 422
    assert "drafts" in response.json()["detail"]


def test_create_draft_rejects_invalid_type(api: Any) -> None:
    payload = {"title": "X", "type": "wizardry", "period": {"start": "2024-01"}}
    response = call(api, "POST", "/experiences/drafts", json=payload)
    assert response.status_code == 422


def test_bad_since_param_maps_to_422(api: Any) -> None:
    response = call(api, "GET", "/experiences", params={"since": "yesterday"})
    assert response.status_code == 422


def test_uninitialized_home_rejected(home: Path) -> None:
    from experienceos.core.errors import NotInitializedError

    with pytest.raises(NotInitializedError):
        create_app(home=Path(home) / "nowhere")


def test_openapi_schema_generated(api: Any) -> None:
    response = call(api, "GET", "/openapi.json")
    assert response.status_code == 200
    paths = json.loads(response.text)["paths"]
    assert "/experiences" in paths and "/stats" in paths
