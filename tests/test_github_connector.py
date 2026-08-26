"""Offline contract tests for the GitHub connector (#007)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.connectors import (
    AuthoredExtractor,
    GitHubAPIError,
    GitHubExtractor,
    default_registry,
)
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, SourceOrigin, Status
from experienceos.storage import ExperienceStore

API_URL = "https://api.github.test"
runner = CliRunner()


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class FakeGitHubClient:
    def __init__(
        self,
        data: dict[str, Any],
        *,
        rate_limited: bool = False,
        network_failure: bool = False,
    ) -> None:
        self.data = data
        self.rate_limited = rate_limited
        self.network_failure = network_failure
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        timeout: int,
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "params": params,
                "timeout": timeout,
            }
        )
        if self.network_failure:
            raise OSError("offline")
        if self.rate_limited:
            return FakeResponse(
                {"message": "API rate limit exceeded"},
                status_code=403,
                headers={"X-RateLimit-Remaining": "0"},
            )
        if url == f"{API_URL}/user":
            return FakeResponse(self.data["user"])
        if url == f"{API_URL}/repos/octo/demo":
            return FakeResponse(self.data["repository"])
        if url == f"{API_URL}/repos/octo/demo/languages":
            return FakeResponse(self.data["languages"])
        if url == f"{API_URL}/repos/octo/demo/commits":
            return FakeResponse(
                self.data["commits_page_1"],
                headers={"Link": (f'<{API_URL}/repos/octo/demo/commits?page=2>; rel="next"')},
            )
        if url == f"{API_URL}/repos/octo/demo/commits?page=2":
            return FakeResponse(self.data["commits_page_2"])
        if url == f"{API_URL}/repos/octo/demo/issues":
            return FakeResponse(self.data["issues"])
        return FakeResponse({"message": "Not Found"}, status_code=404)


@pytest.fixture
def github_data() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "github_api.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_extractor_satisfies_author_capability() -> None:
    assert isinstance(GitHubExtractor(client=object()), AuthoredExtractor)


def test_explicit_author_builds_evidence_backed_draft(
    github_data: dict[str, Any],
) -> None:
    client = FakeGitHubClient(github_data)
    extractor = GitHubExtractor(
        client=client,
        token="",
        api_url=API_URL,
    )

    drafts = list(
        extractor.extract_for_author(
            "github:octo/demo",
            "octocat",
        )
    )

    assert len(drafts) == 1
    experience = drafts[0].experience
    assert experience.status is Status.draft
    assert experience.source.origin is SourceOrigin.github
    assert experience.source.ref == "https://github.com/octo/demo"
    assert experience.title == "demo"
    assert experience.period.start == "2024-01"
    assert experience.period.end == "2024-05"
    assert experience.technology == ["Python", "Shell"]
    assert experience.contribution == [
        "Build connector",
        "Add tests",
        "Add pagination",
    ]
    assert experience.context == (
        "GitHub activity for @octocat: 3 commit(s), 1 pull request(s), and 1 issue(s)."
    )
    assert [item.kind for item in experience.evidence] == [
        EvidenceKind.repo,
        EvidenceKind.commit,
        EvidenceKind.commit,
        EvidenceKind.commit,
        EvidenceKind.pull_request,
        EvidenceKind.issue,
    ]

    commit_calls = [call for call in client.calls if "/commits" in call["url"]]
    assert len(commit_calls) == 2
    assert commit_calls[0]["params"] == {
        "author": "octocat",
        "per_page": 100,
    }
    assert commit_calls[1]["params"] is None
    assert all("Authorization" not in call["headers"] for call in client.calls)


def test_omitted_author_uses_authenticated_user(
    github_data: dict[str, Any],
) -> None:
    client = FakeGitHubClient(github_data)
    extractor = GitHubExtractor(
        client=client,
        token="secret",
        api_url=API_URL,
    )

    experience = next(extractor.extract("github:octo/demo")).experience

    assert experience.context.startswith("GitHub activity for @octocat")
    assert client.calls[0]["url"] == f"{API_URL}/user"
    assert all(call["headers"]["Authorization"] == "Bearer secret" for call in client.calls)


def test_missing_token_without_author_fails_before_network(
    github_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = FakeGitHubClient(github_data)
    extractor = GitHubExtractor(
        client=client,
        token="",
        api_url=API_URL,
    )

    with pytest.raises(GitHubAPIError, match="GITHUB_TOKEN"):
        list(extractor.extract("github:octo/demo"))

    assert client.calls == []


def test_rate_limit_error_is_actionable(
    github_data: dict[str, Any],
) -> None:
    extractor = GitHubExtractor(
        client=FakeGitHubClient(
            github_data,
            rate_limited=True,
        ),
        token="",
        api_url=API_URL,
    )

    with pytest.raises(
        GitHubAPIError,
        match=r"rate limit.*GITHUB_TOKEN",
    ):
        list(
            extractor.extract_for_author(
                "github:octo/demo",
                "octocat",
            )
        )


def test_network_error_is_wrapped(
    github_data: dict[str, Any],
) -> None:
    extractor = GitHubExtractor(
        client=FakeGitHubClient(
            github_data,
            network_failure=True,
        ),
        token="",
        api_url=API_URL,
    )

    with pytest.raises(ConnectorError, match="request failed"):
        list(
            extractor.extract_for_author(
                "github:octo/demo",
                "octocat",
            )
        )


@pytest.mark.parametrize(
    "source",
    [
        "github:",
        "github:only-owner",
        "github:owner/repo/extra",
        "resume:cv.md",
    ],
)
def test_malformed_source_is_rejected(source: str) -> None:
    extractor = GitHubExtractor(
        client=object(),
        token="",
        api_url=API_URL,
    )

    with pytest.raises(GitHubAPIError, match="github:owner/repo"):
        list(
            extractor.extract_for_author(
                source,
                "octocat",
            )
        )


def test_cli_import_with_author_saves_draft(
    cli_env: Path,
    github_data: dict[str, Any],
) -> None:
    original = default_registry.get("github")
    default_registry.unregister("github")
    default_registry.register(
        GitHubExtractor(
            client=FakeGitHubClient(github_data),
            token="",
            api_url=API_URL,
        )
    )
    try:
        result = runner.invoke(
            app,
            [
                "import",
                "github:octo/demo",
                "--author",
                "octocat",
                "--yes",
            ],
        )
    finally:
        default_registry.unregister("github")
        default_registry.register(original)

    assert result.exit_code == 0, result.output
    experiences = ExperienceStore(cli_env).list_all()
    assert len(experiences) == 1
    assert experiences[0].status is Status.draft
    assert experiences[0].source.origin is SourceOrigin.github
