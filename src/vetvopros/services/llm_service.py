"""OpenAI-compatible chat LLM: retries, rate limits, configurable log redaction."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from vetvopros.config.paths import read_prompt_file
from vetvopros.config.settings import Settings

log = logging.getLogger(__name__)


class LlmError(Exception):
    """LLM request failed. Message is safe for logs/UI (no API key or secret headers)."""


def _truncate_for_log(text: str, max_len: int = 120) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


class LlmService:
    """Synchronous chat completions with retries and optional payload redaction in logs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        base = settings.llm_base_url or "https://api.openai.com/v1"
        self._base = base.rstrip("/")
        self._timeout = float(settings.llm.request_timeout_seconds)
        self._max_retries = max(0, int(settings.llm.max_retries))
        self._backoff = float(settings.llm.retry_backoff_seconds)

    def load_main_system_prompt(self) -> str:
        return read_prompt_file(self._settings, self._settings.paths.system_prompt_file)

    def load_analysis_suggestions_prompt(self) -> str:
        return read_prompt_file(self._settings, self._settings.paths.prompt_analysis_suggestions)

    def load_analysis_interpretation_prompt(self) -> str:
        return read_prompt_file(self._settings, self._settings.paths.prompt_analysis_interpretation)

    def load_prompt_at(self, relative_path: str) -> str:
        """Load arbitrary prompt text from a path relative to repo root (as in config.ini [paths])."""
        return read_prompt_file(self._settings, relative_path)

    def complete_with_system(self, system_prompt: str, user_message: str, **kwargs: Any) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return self.complete(messages, **kwargs)

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        max_tokens = int(kwargs.get("max_tokens", self._settings.llm.max_output_tokens))
        model = str(kwargs.get("model", self._settings.llm.chat_model))
        url = f"{self._base}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        reduced = self._settings.llm.reduce_log_detail
        self._log_request_start(model, messages, reduced=reduced)
        t0 = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
                if self._should_retry_response(response) and attempt < self._max_retries:
                    wait = self._retry_delay_seconds(response, attempt)
                    log.warning(
                        "llm_retry",
                        extra={
                            "structured": {
                                "attempt": attempt + 1,
                                "status": response.status_code,
                                "wait_s": round(wait, 2),
                                "model": model,
                            }
                        },
                    )
                    time.sleep(wait)
                    continue
                if response.status_code >= 400:
                    api_detail = self._extract_api_error_detail(response)
                    msg = self._safe_status_message(response.status_code, api_detail)
                    log.error(
                        "llm_http_error",
                        extra={
                            "structured": {
                                "status": response.status_code,
                                "model": model,
                                "api_detail": _truncate_for_log(api_detail, 400) if api_detail else "",
                            }
                        },
                    )
                    raise LlmError(msg)
                data = response.json()
                text = self._content_from_response(data)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._log_success(model, text, elapsed_ms, reduced=reduced)
                return text
            except LlmError:
                raise
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = self._backoff * (2**attempt)
                    log.warning(
                        "llm_timeout_retry",
                        extra={
                            "structured": {
                                "attempt": attempt + 1,
                                "wait_s": round(wait, 2),
                                "model": model,
                            }
                        },
                    )
                    time.sleep(wait)
                    continue
            except httpx.RequestError as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = self._backoff * (2**attempt)
                    log.warning(
                        "llm_network_retry",
                        extra={
                            "structured": {
                                "attempt": attempt + 1,
                                "wait_s": round(wait, 2),
                                "model": model,
                                "err_type": type(e).__name__,
                            }
                        },
                    )
                    time.sleep(wait)
                    continue

        msg = "LLM request failed after retries (timeout or network)."
        if last_error:
            raise LlmError(msg) from last_error
        raise LlmError(msg)

    def _should_retry_response(self, response: httpx.Response) -> bool:
        return response.status_code in (429, 502, 503, 504)

    def _retry_delay_seconds(self, response: httpx.Response, attempt: int) -> float:
        base = self._backoff * (2**attempt)
        if response.status_code == 429:
            ra = response.headers.get("Retry-After")
            if ra:
                try:
                    return max(base, float(ra))
                except ValueError:
                    pass
        return base

    @staticmethod
    def _content_from_response(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        return (content or "").strip()

    def _log_request_start(self, model: str, messages: list[dict[str, Any]], *, reduced: bool) -> None:
        if reduced:
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            log.debug(
                "llm_request",
                extra={
                    "structured": {
                        "model": model,
                        "messages_count": len(messages),
                        "total_content_chars": total_chars,
                    }
                },
            )
            return
        preview: list[dict[str, str]] = []
        for m in messages:
            role = str(m.get("role", ""))
            content = str(m.get("content", ""))
            preview.append({"role": role, "content_preview": _truncate_for_log(content, 200)})
        log.debug(
            "llm_request",
            extra={"structured": {"model": model, "messages_preview": preview}},
        )

    def _log_success(self, model: str, text: str, elapsed_ms: float, *, reduced: bool) -> None:
        if reduced:
            log.info(
                "llm_response",
                extra={
                    "structured": {
                        "model": model,
                        "latency_ms": round(elapsed_ms, 1),
                        "output_chars": len(text),
                    }
                },
            )
            return
        log.info(
            "llm_response",
            extra={
                "structured": {
                    "model": model,
                    "latency_ms": round(elapsed_ms, 1),
                    "output_chars": len(text),
                    "output_preview": _truncate_for_log(text, 200),
                }
            },
        )

    @staticmethod
    def _extract_api_error_detail(response: httpx.Response) -> str:
        """Текст ошибки из тела ответа (OpenAI-style JSON или короткий plain)."""
        try:
            data = response.json()
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()[:800]
            if isinstance(err, str) and err.strip():
                return err.strip()[:800]
        except Exception:
            pass
        try:
            t = (response.text or "").strip()
            if t and len(t) <= 1200:
                return t[:800]
        except Exception:
            pass
        return ""

    @staticmethod
    def _safe_status_message(code: int, api_detail: str = "") -> str:
        base: str
        if code == 400:
            base = "LLM API rejected the request (HTTP 400)."
        elif code == 401:
            base = "LLM API rejected the key (unauthorized)."
        elif code == 403:
            base = "LLM API access forbidden for this key or model."
        elif code == 404:
            base = "LLM API endpoint or model not found."
        elif code == 429:
            base = "LLM API rate limit exceeded."
        elif code >= 500:
            base = "LLM API temporarily unavailable."
        else:
            base = f"LLM API error (HTTP {code})."
        if api_detail:
            return f"{base} — {api_detail}"
        return base
