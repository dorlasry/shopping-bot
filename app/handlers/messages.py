"""Free-text message handler — thin producer.

Receives the WhatsApp text event, enqueues a job, and returns. The actual
parsing + DB work + reply happens in the worker (app.processing).
"""

from __future__ import annotations

from pywa import WhatsApp
from pywa.types import Message

from app.handlers.commands import enqueue_message
from app.logging_config import get_logger
from app.queue.base import MessageQueue

logger = get_logger(__name__)


def register(wa: WhatsApp, queue: MessageQueue) -> None:
    @wa.on_message
    def on_text_message(_: WhatsApp, msg: Message) -> None:
        logger.info("enqueue message from %s: %r", msg.from_user.wa_id, msg.text)
        enqueue_message(queue, msg)
