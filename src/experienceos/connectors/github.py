"""GitHub repository connector (#007).

The connector reads repository metadata and author-attributed activity from
the GitHub REST API, then creates a single evidence-backed Experience draft.
It never writes to GitHub and never infers achievements absent from the API.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from experienceos.connectors.base import ExperienceDraft, parse_source
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, ExperienceType, SourceOrigin

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])")
_NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubAPIError(ConnectorError):
    """A GitHub request failed or returned an invalid response."""


class GitHubAPI:
    """Small testable wrapper around the GitHub REST API."""

    def __init__(
        self,
        client: Any,
        *,
        token: str = "",
        api_url: str = DEFAULT_API_URL,
        network_errors: tuple[type[BaseException], ...] = (OSError,),
    ) -> None:
        self._client = client
        self._api_url = api_url.rstrip("/")
        self._network_errors = network_errors
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ExperienceOS/0.1",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def _request(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(
                url,
                headers=self._headers,
                params=dict(params) if params is not None else None,
                timeout=30,
            )
        except self._network_errors as exc:
            raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc
        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        status = int(response.status_code)
        if 200 <= status < 300:
            return
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        message = (
            payload.get("message", "unknown error")
            if isinstance(payload, dict)
            else "unknown error"
        )
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        if status in {403, 429} and (
            headers.get("x-ratelimit-remaining") == "0" or "rate limit" in message.casefold()
        ):
            raise GitHubAPIError(
                "GitHub API rate limit exceeded; set GITHUB_TOKEN or retry after the limit resets"
            )
        if status == 401:
            raise GitHubAPIError("GitHub authentication failed; check GITHUB_TOKEN")
        if status == 404:
            raise GitHubAPIError("GitHub repository or resource was not found")
        raise GitHubAPIError(f"GitHub API returned HTTP {status}: {message}")

    @staticmethod
    def _next_url(headers: Mapping[str, Any]) -> str | None:
        link = next(
            (str(value) for key, value in headers.items() if str(key).lower() == "link"),
            "",
        )
        match = _NEXT_LINK_RE.search(link)
        return match.group(1) if match else None

    def object(self, path: str) -> dict[str, Any]:
        response = self._request(f"{self._api_url}{path}")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise GitHubAPIError("GitHub API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub API returned an object with the wrong shape")
        return payload

    def pages(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self._api_url}{path}"
        current_params = params
        items: list[dict[str, Any]] = []
        while url:
            response = self._request(url, current_params)
            current_params = None
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise GitHubAPIError("GitHub API returned invalid JSON") from exc
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise GitHubAPIError("GitHub API returned a list with the wrong shape")
            items.extend(payload)
            url = self._next_url(response.headers)
        return items


class GitHubExtractor:
    """Extract one evidence-backed draft from github:owner/repo."""

    name = "github"

    def __init__(
        self,
        *,
        client: Any | None = None,
        token: str | None = None,
        api_url: str = DEFAULT_API_URL,
    ) -> None:
        self._client = client
        self._token = token
        self._api_url = api_url

    def can_handle(self, source: str) -> bool:
        scheme, _ = parse_source(source)
        return scheme == "github"

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        yield self._extract_one(source, author=None)

    def extract_for_author(self, source: str, author: str) -> Iterator[ExperienceDraft]:
        author = author.strip()
        if not author:
            raise GitHubAPIError("--author must not be empty")
        yield self._extract_one(source, author=author)

    @contextmanager
    def _api(self) -> Iterator[GitHubAPI]:
        token = self._token if self._token is not None else os.environ.get(GITHUB_TOKEN_ENV, "")
        if self._client is not None:
            yield GitHubAPI(
                self._client,
                token=token,
                api_url=self._api_url,
            )
            return
        try:
            import httpx
        except ImportError as exc:
            raise GitHubAPIError(
                "httpx is required for GitHub imports: pip install 'experienceos[github]'"
            ) from exc
        with httpx.Client(follow_redirects=True) as client:
            yield GitHubAPI(
                client,
                token=token,
                api_url=self._api_url,
                network_errors=(OSError, httpx.HTTPError),
            )

    def _extract_one(self, source: str, author: str | None) -> ExperienceDraft:
        repository = self._repository_name(source)
        token = self._token if self._token is not None else os.environ.get(GITHUB_TOKEN_ENV, "")
        if author is None and not token:
            raise GitHubAPIError(
                "GITHUB_TOKEN is required when --author is omitted so the "
                "authenticated GitHub user can be identified"
            )

        with self._api() as api:
            if author is None:
                author_payload = api.object("/user")
                author = self._required_text(author_payload, "login", "authenticated user")
            repo = api.object(f"/repos/{repository}")
            languages = api.object(f"/repos/{repository}/languages")
            commits = api.pages(
                f"/repos/{repository}/commits",
                params={"author": author, "per_page": 100},
            )
            issue_items = api.pages(
                f"/repos/{repository}/issues",
                params={
                    "creator": author,
                    "state": "all",
                    "per_page": 100,
                },
            )

        pull_requests = [item for item in issue_items if "pull_request" in item]
        issues = [item for item in issue_items if "pull_request" not in item]
        repo_url = self._required_text(repo, "html_url", "repository")
        full_name = str(repo.get("full_name") or repository)
        title = str(repo.get("name") or repository.split("/", 1)[1])
        activity_dates = self._activity_dates(commits, issue_items)
        fallback_dates = [
            repo.get("created_at"),
            repo.get("pushed_at"),
            repo.get("updated_at"),
        ]
        months = [
            month for value in (activity_dates or fallback_dates) if (month := self._month(value))
        ]
        if not months:
            raise GitHubAPIError("GitHub repository response did not contain usable dates")

        contributions = self._contributions(commits, pull_requests)
        evidence = self._evidence(repo_url, commits, pull_requests, issues)
        technology = [
            name
            for name, _bytes in sorted(
                languages.items(),
                key=lambda item: int(item[1]) if isinstance(item[1], int) else 0,
                reverse=True,
            )
        ]
        license_data = repo.get("license")
        experience_type = (
            ExperienceType.open_source
            if not repo.get("private", False) and isinstance(license_data, dict)
            else ExperienceType.other
        )
        context = (
            f"GitHub activity for @{author}: {len(commits)} commit(s), "
            f"{len(pull_requests)} pull request(s), and "
            f"{len(issues)} issue(s)."
        )
        return ExperienceDraft.create(
            origin=SourceOrigin.github,
            ref=repo_url,
            title=title,
            type=experience_type,
            period={"start": min(months), "end": max(months)},
            context=context,
            description=str(repo.get("description") or f"GitHub repository {full_name}"),
            technology=technology,
            contribution=contributions,
            evidence=evidence,
            tags=["github"],
        )

    @staticmethod
    def _repository_name(source: str) -> str:
        scheme, payload = parse_source(source)
        repository = payload.strip().removesuffix(".git")
        if scheme != "github" or not _REPOSITORY_RE.fullmatch(repository):
            raise GitHubAPIError(
                "GitHub source must use github:owner/repo (without a URL or .git suffix)"
            )
        return repository

    @staticmethod
    def _required_text(
        payload: Mapping[str, Any],
        key: str,
        label: str,
    ) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise GitHubAPIError(f"GitHub {label} response is missing {key!r}")
        return value.strip()

    @staticmethod
    def _month(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        match = _MONTH_RE.match(value)
        return match.group(0) if match else None

    @classmethod
    def _activity_dates(
        cls,
        commits: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> list[Any]:
        dates: list[Any] = []
        for commit in commits:
            details = commit.get("commit")
            if isinstance(details, dict):
                author = details.get("author")
                if isinstance(author, dict):
                    dates.append(author.get("date"))
        dates.extend(item.get("created_at") for item in issues)
        return dates

    @staticmethod
    def _contributions(
        commits: list[dict[str, Any]],
        pull_requests: list[dict[str, Any]],
    ) -> list[str]:
        values: list[str] = []
        for commit in commits:
            details = commit.get("commit")
            message = details.get("message") if isinstance(details, dict) else None
            if isinstance(message, str) and message.strip():
                values.append(message.splitlines()[0].strip())
        values.extend(
            title.strip()
            for item in pull_requests
            if isinstance((title := item.get("title")), str) and title.strip()
        )
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(value)
        return unique

    @staticmethod
    def _evidence(
        repo_url: str,
        commits: list[dict[str, Any]],
        pull_requests: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        raw: list[tuple[EvidenceKind, str, str]] = [
            (
                EvidenceKind.repo,
                repo_url,
                "GitHub repository",
            ),
        ]
        for kind, items in (
            (EvidenceKind.commit, commits),
            (EvidenceKind.pull_request, pull_requests),
            (EvidenceKind.issue, issues),
        ):
            for item in items:
                location = item.get("html_url")
                if not isinstance(location, str) or not location.strip():
                    continue
                if kind is EvidenceKind.commit:
                    details = item.get("commit")
                    description = details.get("message", "") if isinstance(details, dict) else ""
                    description = str(description).splitlines()[0]
                else:
                    description = str(item.get("title") or "")
                raw.append(
                    (
                        kind,
                        location.strip(),
                        description.strip(),
                    )
                )
        seen: set[str] = set()
        evidence: list[dict[str, str]] = []
        for kind, location, description in raw:
            if location in seen:
                continue
            seen.add(location)
            evidence.append(
                {
                    "kind": kind.value,
                    "location": location,
                    "description": description,
                }
            )
        return evidence
