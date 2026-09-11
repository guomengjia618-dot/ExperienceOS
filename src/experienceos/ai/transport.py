"""Resilient HTTP transport and request metrics for model providers."""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError

logger = logging.getLogger("experienceos.ai.transport")


@dataclass(frozen=True)
class RequestMetrics:
    """Operational metadata safe to persist; never contains prompts or secrets."""

    provider: str
    model: str
    endpoint: str
    success: bool
    latency_ms: float
    retry_count: int
    status_code: int | None
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    estimated_cost_usd: float | None
    error_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HTTPResult:
    data: dict[str, Any]
    metrics: RequestMetrics


class OpenAIHTTPTransport:
    """POST JSON with bounded retries, backoff, jitter, and request tracing."""

    def __init__(
        self,
        config: AIConfig,
        *,
        provider_name: str,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self.provider_name = provider_name
        self._sleep = sleep
        self._random_value = random_value
        self.last_metrics: RequestMetrics | None = None

    def post(self, endpoint: str, payload: dict[str, Any]) -> HTTPResult:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - depends on installation extra
            raise AIProviderError(
                "httpx is required for AI features: pip install 'experienceos[ai]'"
            ) from exc

        api_key = os.environ.get(self.config.api_key_env, "")
        if not api_key:
            raise AIProviderError(
                f"missing API key: set ${self.config.api_key_env} "
                "(configured as ai.api_key_env in config.toml)"
            )

        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        started = time.perf_counter()
        max_retries = max(0, int(self.config.max_retries))
        request_id: str | None = None

        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=float(self.config.timeout_seconds),
                )
            except httpx.TimeoutException as exc:
                if self._retry_exception("timeout", attempt, max_retries, started):
                    continue
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type="timeout",
                    message=f"request to {self.config.base_url} timed out: {exc}",
                )
            except httpx.RequestError as exc:
                if self._retry_exception("network", attempt, max_retries, started):
                    continue
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type="network",
                    message=f"request to {self.config.base_url} failed: {exc}",
                )

            headers = getattr(response, "headers", {})
            request_id = headers.get("x-request-id") if headers else None
            status_code = int(response.status_code)
            if status_code == 429 or status_code >= 500:
                error_type = "rate_limit" if status_code == 429 else "server_error"
                delay = self._retry_delay(
                    attempt,
                    max_retries,
                    started,
                    headers.get("retry-after") if headers else None,
                )
                if delay is not None:
                    logger.warning(
                        "model request retry provider=%s status=%s request_id=%s "
                        "attempt=%s delay_seconds=%.3f",
                        self.provider_name,
                        status_code,
                        request_id or "-",
                        attempt + 1,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                summary = " ".join(response.text.split())[:300]
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type=error_type,
                    message=(
                        f"model API returned HTTP {status_code}"
                        f"{self._request_id_suffix(request_id)}: "
                        f"{summary or 'empty response'}"
                    ),
                    status_code=status_code,
                    request_id=request_id,
                )

            if status_code >= 400:
                summary = " ".join(response.text.split())[:300]
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type="http_error",
                    message=(
                        f"model API returned HTTP {status_code}"
                        f"{self._request_id_suffix(request_id)}: "
                        f"{summary or 'empty response'}"
                    ),
                    status_code=status_code,
                    request_id=request_id,
                )

            try:
                data = response.json()
            except ValueError:
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type="invalid_json",
                    message=(
                        "model API returned invalid JSON"
                        f"{self._request_id_suffix(request_id)}"
                    ),
                    status_code=status_code,
                    request_id=request_id,
                )
            if not isinstance(data, dict):
                self._raise_failure(
                    endpoint,
                    started,
                    attempt,
                    error_type="invalid_json",
                    message="model API returned a non-object JSON response",
                    status_code=status_code,
                    request_id=request_id,
                )
            metrics = self._metrics(
                endpoint,
                started,
                attempt,
                success=True,
                status_code=status_code,
                request_id=request_id,
                data=data,
            )
            self.last_metrics = metrics
            return HTTPResult(data=data, metrics=metrics)

        raise AssertionError("unreachable")

    def _retry_exception(
        self,
        error_type: str,
        attempt: int,
        max_retries: int,
        started: float,
    ) -> bool:
        delay = self._retry_delay(attempt, max_retries, started, None)
        if delay is None:
            return False
        logger.warning(
            "model request retry provider=%s error_type=%s attempt=%s delay_seconds=%.3f",
            self.provider_name,
            error_type,
            attempt + 1,
            delay,
        )
        self._sleep(delay)
        return True

    def _retry_delay(
        self,
        attempt: int,
        max_retries: int,
        started: float,
        retry_after: str | None,
    ) -> float | None:
        if attempt >= max_retries:
            return None
        elapsed = time.perf_counter() - started
        remaining = float(self.config.retry_time_budget_seconds) - elapsed
        if remaining <= 0:
            return None
        server_delay = self._parse_retry_after(retry_after)
        if server_delay is None:
            base = float(self.config.retry_base_seconds) * (2**attempt)
            delay = min(base, float(self.config.retry_max_seconds))
        else:
            delay = server_delay
        delay += self._random_value() * float(self.config.retry_jitter_seconds)
        if delay > remaining:
            return None
        return max(0.0, delay)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _request_id_suffix(request_id: str | None) -> str:
        return f" (request_id={request_id})" if request_id else ""

    def _metrics(
        self,
        endpoint: str,
        started: float,
        retry_count: int,
        *,
        success: bool,
        status_code: int | None,
        request_id: str | None,
        data: dict[str, Any] | None = None,
        error_type: str | None = None,
    ) -> RequestMetrics:
        usage = (data or {}).get("usage") or {}
        input_tokens = self._optional_int(
            usage.get("input_tokens", usage.get("prompt_tokens"))
        )
        output_tokens = self._optional_int(
            usage.get("output_tokens", usage.get("completion_tokens"))
        )
        total_tokens = self._optional_int(usage.get("total_tokens"))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        input_details = usage.get("input_tokens_details") or usage.get(
            "prompt_tokens_details"
        ) or {}
        output_details = usage.get("output_tokens_details") or usage.get(
            "completion_tokens_details"
        ) or {}
        estimated_cost = self._estimated_cost(input_tokens, output_tokens)
        return RequestMetrics(
            provider=self.provider_name,
            model=self.config.model,
            endpoint=endpoint,
            success=success,
            latency_ms=(time.perf_counter() - started) * 1000,
            retry_count=retry_count,
            status_code=status_code,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=self._optional_int(input_details.get("cached_tokens")),
            reasoning_tokens=self._optional_int(output_details.get("reasoning_tokens")),
            estimated_cost_usd=estimated_cost,
            error_type=error_type,
        )

    def _estimated_cost(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float | None:
        if input_tokens is None or output_tokens is None:
            return None
        input_rate = float(self.config.input_cost_per_million_usd)
        output_rate = float(self.config.output_cost_per_million_usd)
        if input_rate <= 0 and output_rate <= 0:
            return None
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return int(value) if value is not None else None

    def _raise_failure(
        self,
        endpoint: str,
        started: float,
        retry_count: int,
        *,
        error_type: str,
        message: str,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        metrics = self._metrics(
            endpoint,
            started,
            retry_count,
            success=False,
            status_code=status_code,
            request_id=request_id,
            error_type=error_type,
        )
        self.last_metrics = metrics
        logger.error(
            "model request failed provider=%s error_type=%s status=%s request_id=%s "
            "retries=%s",
            self.provider_name,
            error_type,
            status_code or "-",
            request_id or "-",
            retry_count,
        )
        raise AIProviderError(message, metadata=metrics.to_dict())
