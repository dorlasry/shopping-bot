"""Helpers that turn pywa updates into queue jobs.

The web process does as little as possible: extract the fields we need from the
pywa update and enqueue. All real work happens later in the worker. This keeps
the webhook response fast so Meta never times out and retries.
"""

from __future__ import annotations

from app.queue.base import IncomingJob, JobKind, MessageQueue


def enqueue_message(queue: MessageQueue, msg) -> None:
    queue.enqueue(
        IncomingJob(
            kind="message",
            phone=msg.from_user.wa_id,
            name=msg.from_user.name or "",
            message_id=msg.id,
            text=msg.text or "",
        )
    )


def enqueue_callback(queue: MessageQueue, update, kind: JobKind) -> None:
    queue.enqueue(
        IncomingJob(
            kind=kind,
            phone=update.from_user.wa_id,
            name=update.from_user.name or "",
            message_id=update.id,
            callback_data=update.data or "",
        )
    )


def enqueue_audio(queue: MessageQueue, msg) -> None:
    """Enqueue a voice note for transcription + processing in the worker."""
    queue.enqueue(
        IncomingJob(
            kind="audio",
            phone=msg.from_user.wa_id,
            name=msg.from_user.name or "",
            message_id=msg.id,
            media_id=msg.audio.id,
            mime_type=getattr(msg.audio, "mime_type", "audio/ogg"),
        )
    )


def enqueue_flow_completion(queue: MessageQueue, completion, picked: list[str]) -> None:
    """Enqueue the items a user ticked in the past-items flow."""
    queue.enqueue(
        IncomingJob(
            kind="flow_completion",
            phone=completion.from_user.wa_id,
            name=completion.from_user.name or "",
            message_id=completion.id,
            picked=picked,
        )
    )
