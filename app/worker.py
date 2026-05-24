"""Worker: consumes jobs from the queue and processes them.

Two ways to run:

  1. Standalone (Redis backend, production-shaped):
         python -m app.worker
     Runs its own send-only WhatsApp client + queue, loops forever.

  2. In-process thread (memory backend, single-process local mode):
     app.main starts `run_loop_in_thread(wa, queue)` during startup so you can
     demo the whole thing with one command and no Redis.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable

from pywa import WhatsApp

from app.config import settings
from app.db.session import init_db
from app.logging_config import configure_logging, get_logger
from app.processing import process_job
from app.queue.base import MessageQueue
from app.queue.factory import build_queue

logger = get_logger(__name__)


def consume_loop(
    wa: WhatsApp, queue: MessageQueue, should_continue: Callable[[], bool]
) -> None:
    """Block on the queue and process jobs until `should_continue()` is False."""
    while should_continue():
        job = queue.dequeue(timeout=5)
        if job is None:
            continue  # timeout — loop again so we can check should_continue()
        if queue.seen(job.message_id):
            logger.info("skipping duplicate message %s", job.message_id)
            continue
        try:
            process_job(wa, job)
        except Exception:  # noqa: BLE001 — one bad job must not kill the worker
            logger.exception("failed to process job %s", job.message_id)


def run_loop_in_thread(wa: WhatsApp, queue: MessageQueue) -> threading.Thread:
    """Start consume_loop in a daemon thread (used by memory backend)."""
    thread = threading.Thread(
        target=lambda: consume_loop(wa, queue, lambda: True),
        name="worker",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    configure_logging()
    init_db()

    # Send-only client: no server/webhook, just used to send messages back.
    wa = WhatsApp(phone_id=settings.wa_phone_id, token=settings.wa_token)
    queue = build_queue()

    running = {"value": True}

    def _stop(*_: object) -> None:
        logger.info("shutdown signal received")
        running["value"] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("worker started (backend=%s)", settings.queue_backend)
    consume_loop(wa, queue, lambda: running["value"])
    queue.close()
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
