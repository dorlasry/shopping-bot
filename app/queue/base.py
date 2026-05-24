"""Queue interface + the job payload that travels through it.

`IncomingJob` is the minimal, serializable description of a WhatsApp event that
the web process extracts and hands to a worker. Keeping it small and JSON-friendly
means any backend (Redis list, SQS message, Kafka record) can carry it unchanged.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Literal

JobKind = Literal["message", "selection", "button", "audio"]


@dataclass
class IncomingJob:
    kind: JobKind
    phone: str
    name: str
    message_id: str
    # Present for kind == "message":
    text: str | None = None
    # Present for kind in ("selection", "button"):
    callback_data: str | None = None
    # Present for kind == "audio" (a voice note):
    media_id: str | None = None
    mime_type: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(raw: str | bytes) -> IncomingJob:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return IncomingJob(**json.loads(raw))


class MessageQueue(ABC):
    """Abstract producer/consumer queue with simple at-least-once dedup support."""

    @abstractmethod
    def enqueue(self, job: IncomingJob) -> None:
        """Add a job to the queue (producer side; called by the web process)."""

    @abstractmethod
    def dequeue(self, timeout: int = 5) -> IncomingJob | None:
        """Block up to `timeout` seconds for the next job. Returns None on timeout."""

    @abstractmethod
    def seen(self, message_id: str) -> bool:
        """Atomically check-and-mark a message id.

        Returns True if this id was ALREADY processed (caller should skip),
        False if it's new (caller should process). Protects against Meta's
        webhook retries causing duplicate actions.
        """

    def close(self) -> None:  # optional override
        """Release any resources (connections). No-op by default."""
