"""OpenAI-compatible embeddings API: батчи, retry с backoff (04_rag_design.md)."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Protocol

import httpx

from vetvopros.config.settings import Settings

log = logging.getLogger(__name__)

DEFAULT_BATCH = 32
MAX_RETRIES = 4


class EmbeddingRequestError(Exception):
    """Ошибка HTTP/API эмбеддингов (сеть, 4xx/5xx, неверный ответ)."""


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class EmbeddingClient:
    """Синхронный клиент `/v1/embeddings`; ключ и base URL как у LLM."""

    def __init__(self, settings: Settings, *, batch_size: int = DEFAULT_BATCH) -> None:
        self._settings = settings
        self._batch_size = max(1, batch_size)
        base = settings.llm_base_url or "https://api.openai.com/v1"
        self._base = base.rstrip("/")
        self._timeout = float(settings.llm.request_timeout_seconds)
        self._api_key = settings.llm_api_key

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key.strip():
            raise EmbeddingRequestError("LLM_API_KEY / OPENAI_API_KEY is empty")

        model = self._settings.rag.embedding_model
        expected_dim = self._settings.rag.embedding_dimensions
        out: list[list[float]] = []
        url = f"{self._base}/embeddings"

        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors = self._post_embeddings_with_retry(url, model, batch)
            for vec in vectors:
                if len(vec) != expected_dim:
                    msg = f"embedding dim {len(vec)} != config {expected_dim}"
                    raise EmbeddingRequestError(msg)
            out.extend(vectors)

        return out

    def _post_embeddings_with_retry(
        self,
        url: str,
        model: str,
        batch: list[str],
    ) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"model": model, "input": batch}

        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    self._backoff_sleep(attempt, response)
                    continue
                response.raise_for_status()
                return self._parse_embeddings_response(response.json(), len(batch))
            except EmbeddingRequestError:
                raise
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response is not None and (
                    e.response.status_code == 429 or e.response.status_code >= 500
                ):
                    self._backoff_sleep(attempt, e.response)
                    continue
                log.warning("embedding_http_error", extra={"status": e.response.status_code})
                raise EmbeddingRequestError(str(e)) from e
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_err = e
                self._backoff_sleep(attempt, None)
            except Exception as e:
                log.exception("embedding_unexpected_error")
                raise EmbeddingRequestError(str(e)) from e

        msg = f"embeddings failed after {MAX_RETRIES} attempts"
        if last_err:
            raise EmbeddingRequestError(msg) from last_err
        raise EmbeddingRequestError(msg)

    def _backoff_sleep(self, attempt: int, response: httpx.Response | None) -> None:
        retry_after: float | None = None
        if response is not None:
            ra = response.headers.get("retry-after")
            if ra:
                try:
                    retry_after = float(ra)
                except ValueError:
                    retry_after = None
        base = 0.8 * (2**attempt) + random.random() * 0.2
        delay = retry_after if retry_after is not None else base
        delay = min(delay, 30.0)
        log.warning(
            "embedding_retry_backoff",
            extra={"structured": {"attempt": attempt, "sleep_s": round(delay, 2)}},
        )
        time.sleep(delay)

    def _parse_embeddings_response(self, data: dict[str, Any], batch_len: int) -> list[list[float]]:
        items = data.get("data")
        if not isinstance(items, list) or len(items) != batch_len:
            raise EmbeddingRequestError("invalid embeddings response: data")

        if batch_len == 0:
            return []

        has_index = any(
            isinstance(item, dict) and isinstance(item.get("index"), int) for item in items
        )
        if not has_index:
            out_seq: list[list[float]] = []
            for item in items:
                if not isinstance(item, dict):
                    raise EmbeddingRequestError("invalid embeddings response: item")
                emb = item.get("embedding")
                if not isinstance(emb, list):
                    raise EmbeddingRequestError("invalid embeddings response: embedding")
                out_seq.append([float(x) for x in emb])
            return out_seq

        by_index: list[list[float] | None] = [None] * batch_len
        for item in items:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            emb = item.get("embedding")
            if isinstance(idx, int) and isinstance(emb, list):
                floats = [float(x) for x in emb]
                if 0 <= idx < batch_len:
                    by_index[idx] = floats

        if any(v is None for v in by_index):
            raise EmbeddingRequestError("invalid embeddings response: missing index")
        return [v for v in by_index if v is not None]
