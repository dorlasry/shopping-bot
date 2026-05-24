"""Interactive handlers — thin producers.

List-row taps (CallbackSelection) and button taps (CallbackButton) are enqueued
and processed by the worker, exactly like text messages.
"""

from __future__ import annotations

from pywa import WhatsApp
from pywa.types import CallbackButton, CallbackSelection

from app.handlers.commands import enqueue_callback
from app.logging_config import get_logger
from app.queue.base import MessageQueue

logger = get_logger(__name__)


def register(wa: WhatsApp, queue: MessageQueue) -> None:
    @wa.on_callback_selection
    def on_list_selection(_: WhatsApp, sel: CallbackSelection) -> None:
        logger.info("enqueue selection from %s: %r", sel.from_user.wa_id, sel.data)
        enqueue_callback(queue, sel, "selection")

    @wa.on_callback_button
    def on_command_button(_: WhatsApp, btn: CallbackButton) -> None:
        logger.info("enqueue button from %s: %r", btn.from_user.wa_id, btn.data)
        enqueue_callback(queue, btn, "button")
