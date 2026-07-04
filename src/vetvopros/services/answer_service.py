"""Orchestration: vet guardrails, billing, RAG + LLM."""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Literal

from vetvopros.config.paths import read_prompt_file, read_texts_file
from vetvopros.config.settings import Settings
from vetvopros.vet.guardrails import analysis_interpretation_system_prefix, evaluate
from vetvopros.repositories.message_repo import MessageRepository
from vetvopros.repositories.user_repo import UserRepository
from vetvopros.services.billing_service import SqlBillingService
from vetvopros.services.llm_service import LlmError, LlmService
from vetvopros.services.protocols import AnswerResult
from vetvopros.services.rag_service import ChunkHit, RagService

log = logging.getLogger(__name__)

_RAG_SYSTEM_SUFFIX = """
Дополнительно: пользователю показаны выдержки из внутреннего ветеринарного справочника (ниже в сообщении пользователя).
Отвечай в первую очередь по этим выдержкам: сохраняй важные детали (симптомы, формулировки, названия препаратов и дозировок для животных, источники), если они есть в тексте.
Формулируй ответ на русском языке. Не подмешивай англоязычные штампы, если в справочнике всё по-русски.
Если во фрагментах нет ответа на вопрос, скажи об этом кратко и дай только общие осторожные ориентиры в духе основной инструкции.
""".strip()

_MAX_HISTORY_CHARS_PER_MESSAGE = 1200


def _truncate_for_context(text: str, limit: int = _MAX_HISTORY_CHARS_PER_MESSAGE) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 3] + "..."


class VetAnswerService:
    def __init__(
        self,
        settings: Settings,
        users: UserRepository,
        billing: SqlBillingService,
        messages: MessageRepository,
        llm: LlmService,
        rag: RagService,
    ) -> None:
        self._settings = settings
        self._users = users
        self._billing = billing
        self._messages = messages
        self._llm = llm
        self._rag = rag

    @staticmethod
    def _fill_analysis_multiturn_template(template: str, *, prior: str, user_message: str) -> str:
        return template.replace("@@MVP_PRIOR@@", prior).replace("@@MVP_USER@@", user_message)

    def _analysis_user_block_for_llm(
        self,
        text: str,
        prior_transcript: str | None,
        *,
        kind: Literal["suggestions", "interpretation"],
    ) -> str:
        """User-сообщение для LLM; при многоходовом диалоге — из `prompts/analysis_multiturn_*.md`."""
        t = (text or "").strip()
        prior = (prior_transcript or "").strip()
        if not prior:
            return t
        rel = (
            self._settings.paths.prompt_analysis_multiturn_suggestions
            if kind == "suggestions"
            else self._settings.paths.prompt_analysis_multiturn_interpretation
        )
        tpl = read_prompt_file(self._settings, rel).strip()
        return self._fill_analysis_multiturn_template(tpl, prior=prior, user_message=t)

    def ask(self, user_id: int, text: str, *, username: str | None = None) -> AnswerResult:
        user = self._users.get_or_create(user_id, username)
        gr = evaluate(text, settings=self._settings)
        if gr.action in ("escalate", "block"):
            body = gr.response_text
            kind = "red_flag" if gr.action == "escalate" else "policy_block"
            self._persist_pair(
                user.id, text, body, "guardrail", {"kind": kind, "reason_code": gr.reason_code}
            )
            return AnswerResult(text=body, source="guardrail", metadata={"kind": kind, "reason_code": gr.reason_code})
        if not self._billing.can_answer(user_id):
            body = read_texts_file(self._settings, "limit_exceeded.md")
            self._persist_pair(user.id, text, body, "billing_block", {})
            return AnswerResult(text=body, source="billing_block", metadata={})

        # Pull recent thread from DB (so follow-up questions keep context).
        hist_limit = max(0, int(getattr(self._settings.llm, "history_messages", 8)))
        history = self._messages.list_for_user(user.id, limit=hist_limit)
        # list_for_user returns newest-first; reverse to oldest-first for LLM.
        history = list(reversed(history))

        hits = self._rag.retrieve(text)
        rag_meta = self._rag.message_metadata(hits)
        if hits:
            try:
                log.info(
                    "rag_hits",
                    extra={
                        "structured": {
                            "user_id": user_id,
                            "hits": len(hits),
                            "slugs": [h.document_slug for h in hits[:5]],
                            "min_similarity": float(self._settings.rag.min_similarity),
                        }
                    },
                )
            except Exception:
                # Логирование не должно влиять на ответ.
                pass

        system = self._llm.load_main_system_prompt()
        model_source = "rag_llm" if hits else "llm"

        # Build chat messages with persisted thread.
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in history:
            if m.role not in ("user", "assistant"):
                continue
            messages.append(
                {
                    "role": m.role,
                    "content": _truncate_for_context(m.content),
                }
            )

        # Attach RAG excerpts as additional context when available.
        user_prompt = text
        if hits:
            messages[0]["content"] = messages[0]["content"] + "\n\n" + _RAG_SYSTEM_SUFFIX
            excerpts: list[str] = []
            for i, h in enumerate(hits, start=1):
                chunk = _truncate_for_context(h.content, 1200)
                excerpts.append(
                    f"[{i}] Документ: {h.document_slug} (chunk {h.chunk_index}, score {h.score:.3f})\n{chunk}"
                )
            user_prompt = text + "\n\n---\nВЫДЕРЖКИ ИЗ СПРАВОЧНИКА:\n\n" + "\n\n---\n".join(excerpts)

        messages.append({"role": "user", "content": user_prompt})

        self._messages.add_message(
            user_id=user.id,
            role="user",
            content=text,
            source="user",
            metadata={"rag": rag_meta, "rag_used": bool(hits), "history_used": len(history)},
        )
        try:
            answer = self._llm.complete(messages)
        except LlmError as e:
            log.warning("llm_failure: %s", e)
            body = read_texts_file(self._settings, "error_generic.md")
            self._messages.add_message(
                user_id=user.id,
                role="assistant",
                content=body,
                source="error",
                metadata={"kind": "llm", "detail": str(e)[:500], "rag": rag_meta, "rag_used": bool(hits)},
            )
            return AnswerResult(text=body, source="error", metadata={})
        except Exception:
            log.exception("llm_failure")
            body = read_texts_file(self._settings, "error_generic.md")
            self._messages.add_message(
                user_id=user.id,
                role="assistant",
                content=body,
                source="error",
                metadata={"trace": traceback.format_exc()[-800:], "rag": rag_meta, "rag_used": bool(hits)},
            )
            return AnswerResult(text=body, source="error", metadata={})
        if not answer:
            body = read_texts_file(self._settings, "error_generic.md")
            self._messages.add_message(user_id=user.id, role="assistant", content=body, source="error", metadata={})
            return AnswerResult(text=body, source="error", metadata={})
        mid = self._messages.add_message(
            user_id=user.id,
            role="assistant",
            content=answer,
            source=model_source,
            metadata={"rag": rag_meta, "rag_used": bool(hits), "history_used": len(history)},
        )
        if not self._billing.check_and_consume_answer_credit(
            user_id, model_source, idempotency_key=str(mid)
        ):
            log.error(
                "billing_consume_failed_after_llm telegram_id=%s source=%s assistant_message_id=%s",
                user_id,
                model_source,
                mid,
            )
        return AnswerResult(text=answer, source=model_source, metadata={"rag_used": bool(hits), **rag_meta})

    def ask_analysis_suggestions(
        self,
        user_id: int,
        text: str,
        *,
        username: str | None = None,
        prior_transcript: str | None = None,
    ) -> AnswerResult:
        user = self._users.get_or_create(user_id, username)
        gr = evaluate(text, settings=self._settings)
        if gr.action in ("escalate", "block"):
            kind = "red_flag" if gr.action == "escalate" else "policy_block"
            return AnswerResult(
                text=gr.response_text,
                source="guardrail",
                metadata={"flow": "analysis_suggestions", "kind": kind, "reason_code": gr.reason_code},
            )
        if not self._billing.can_answer(user_id):
            body = read_texts_file(self._settings, "limit_exceeded.md")
            return AnswerResult(text=body, source="billing_block", metadata={"flow": "analysis_suggestions"})
        system = self._llm.load_analysis_suggestions_prompt()
        llm_user = self._analysis_user_block_for_llm(text, prior_transcript, kind="suggestions")
        try:
            answer = self._llm.complete_with_system(system, llm_user)
        except LlmError as e:
            log.warning("llm_analysis_suggestions: %s", e)
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(
                text=body,
                source="error",
                metadata={"flow": "analysis_suggestions", "detail": str(e)[:500]},
            )
        except Exception:
            log.exception("llm_analysis_suggestions")
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(text=body, source="error", metadata={"flow": "analysis_suggestions"})
        if not answer:
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(text=body, source="error", metadata={"flow": "analysis_suggestions"})
        self._messages.add_message(
            user_id=user.id,
            role="user",
            content=text,
            source="user",
            metadata={"flow": "analysis_suggestions"},
        )
        mid = self._messages.add_message(
            user_id=user.id,
            role="assistant",
            content=answer,
            source="analysis_suggestions",
            metadata={},
        )
        if not self._billing.check_and_consume_answer_credit(
            user_id, "analysis_suggestions", idempotency_key=str(mid)
        ):
            log.error(
                "billing_consume_failed_after_llm telegram_id=%s flow=analysis_suggestions assistant_message_id=%s",
                user_id,
                mid,
            )
        return AnswerResult(text=answer, source="analysis_suggestions", metadata={})

    def ask_analysis_interpretation(
        self,
        user_id: int,
        text: str,
        *,
        username: str | None = None,
        prior_transcript: str | None = None,
    ) -> AnswerResult:
        user = self._users.get_or_create(user_id, username)
        gr = evaluate(text, settings=self._settings)
        if gr.action in ("escalate", "block"):
            kind = "red_flag" if gr.action == "escalate" else "policy_block"
            return AnswerResult(
                text=gr.response_text,
                source="guardrail",
                metadata={"flow": "analysis_interpretation", "kind": kind, "reason_code": gr.reason_code},
            )
        if not self._billing.can_answer(user_id):
            body = read_texts_file(self._settings, "limit_exceeded.md")
            return AnswerResult(text=body, source="billing_block", metadata={"flow": "analysis_interpretation"})
        system = (
            analysis_interpretation_system_prefix(self._settings)
            + "\n\n"
            + self._llm.load_analysis_interpretation_prompt()
        )
        llm_user = self._analysis_user_block_for_llm(text, prior_transcript, kind="interpretation")
        try:
            answer = self._llm.complete_with_system(system, llm_user)
        except LlmError as e:
            log.warning("llm_analysis_interpretation: %s", e)
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(
                text=body,
                source="error",
                metadata={"flow": "analysis_interpretation", "detail": str(e)[:500]},
            )
        except Exception:
            log.exception("llm_analysis_interpretation")
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(text=body, source="error", metadata={"flow": "analysis_interpretation"})
        if not answer:
            body = read_texts_file(self._settings, "error_generic.md")
            return AnswerResult(text=body, source="error", metadata={"flow": "analysis_interpretation"})
        self._messages.add_message(
            user_id=user.id,
            role="user",
            content=text,
            source="user",
            metadata={"flow": "analysis_interpretation"},
        )
        mid = self._messages.add_message(
            user_id=user.id,
            role="assistant",
            content=answer,
            source="analysis_interpretation",
            metadata={},
        )
        if not self._billing.check_and_consume_answer_credit(
            user_id, "analysis_interpretation", idempotency_key=str(mid)
        ):
            log.error(
                "billing_consume_failed_after_llm telegram_id=%s flow=analysis_interpretation assistant_message_id=%s",
                user_id,
                mid,
            )
        return AnswerResult(text=answer, source="analysis_interpretation", metadata={})

    def _persist_pair(
        self,
        user_uuid: uuid.UUID,
        user_text: str,
        assistant_text: str,
        source: str,
        meta: dict,
    ) -> None:
        self._messages.add_message(
            user_id=user_uuid,
            role="user",
            content=user_text,
            source="user",
            metadata={},
        )
        self._messages.add_message(
            user_id=user_uuid,
            role="assistant",
            content=assistant_text,
            source=source,
            metadata=meta,
        )
