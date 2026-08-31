"""Email-in ingest for grandparents and ambient contributions (TASK-804, PRD 27, PRD 11).

Grandparents can send a voice note, photo, or story simply by sending an email.
The mailbox parser operates strictly in the interface layer.
"""

from __future__ import annotations

import email
from datetime import UTC, datetime
from email.policy import default
from typing import Any

from anuvritti.application.capture import CaptureSparkCommand, CaptureSparkUseCase
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceKind, SourceRef
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import ChildId, FamilyId, MediaId, MemberId
from anuvritti.shared.result import Ok, Result


class EmailIngestHandler:
    """Parses incoming emails and creates Sparks / media in the archive."""

    def __init__(
        self,
        *,
        capture_spark: CaptureSparkUseCase,
        media_store: Any,
    ) -> None:
        self._capture_spark = capture_spark
        self._media_store = media_store

    def process_raw_email(
        self,
        raw_bytes: bytes,
        *,
        family_id: FamilyId,
        author_id: MemberId,
        child_id: ChildId | None = None,
    ) -> Result[Spark, DomainError]:
        msg = email.message_from_bytes(raw_bytes, policy=default)

        subject = str(msg.get("Subject", "")).strip()
        sender = str(msg.get("From", "")).strip()

        # Extract text body
        body_text = ""
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part:
            body_text = body_part.get_content().strip()

        title = subject if subject else (body_text[:60] if body_text else "A message from family")

        # Extract audio / photo attachments if present
        voice_media_id: MediaId | None = None
        for part in msg.iter_attachments():
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            if content_type.startswith("audio/"):
                now = datetime.now(UTC)
                save_res = self._media_store.put(
                    family_id,
                    content=payload,
                    mime_type=content_type,
                    at=now,
                )
                if save_res.is_ok():
                    voice_media_id = save_res.unwrap().id
                    break

        command = CaptureSparkCommand(
            family_id=family_id,
            owner_id=author_id,
            subject_child_id=child_id,
            source=SourceRef(
                kind=SourceKind.TEXT,
                text=body_text or title,
                title=title,
                creator=sender or "Family",
            ),
            note=body_text if (subject and body_text) else None,
        )

        spark_res = self._capture_spark.execute(command)
        if spark_res.is_err():
            return spark_res

        spark = spark_res.unwrap()
        if voice_media_id is not None:
            why_res = spark.record_why(
                text=body_text if body_text else None,
                voice_media_id=str(voice_media_id),
                at=spark.created_at,
            )
            if why_res.is_ok():
                spark = why_res.unwrap()

        return Ok(spark)
