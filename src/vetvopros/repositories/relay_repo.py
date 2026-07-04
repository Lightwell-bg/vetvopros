"""Сохранение связи bridge-сообщение → пациент для ответа специалиста reply."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import SpecialistRelayMap
from vetvopros.db.session import session_scope


class RelayRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def save_bridge(
        self,
        *,
        specialist_chat_id: int,
        bridge_message_id: int,
        patient_telegram_id: int,
        specialist_key: str,
    ) -> None:
        with session_scope(self._factory) as s:
            row = SpecialistRelayMap(
                specialist_chat_id=specialist_chat_id,
                bridge_message_id=bridge_message_id,
                patient_telegram_id=patient_telegram_id,
                specialist_key=specialist_key,
            )
            s.add(row)

    def find_patient_for_reply(self, *, specialist_chat_id: int, reply_to_message_id: int) -> int | None:
        with session_scope(self._factory) as s:
            row = s.scalar(
                select(SpecialistRelayMap).where(
                    SpecialistRelayMap.specialist_chat_id == specialist_chat_id,
                    SpecialistRelayMap.bridge_message_id == reply_to_message_id,
                )
            )
            if row is None:
                return None
            return int(row.patient_telegram_id)
