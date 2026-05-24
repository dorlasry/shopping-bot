"""Web entrypoint: FastAPI + pywa client + queue producer.

Run locally with:
    uvicorn app.main:app --reload --port 8000

Roles:
  - pywa mounts the WhatsApp webhook (GET verify + POST receive) on `app` at "/",
    verifies Meta's signature with WA_APP_SECRET, and dispatches to our handlers.
  - Our handlers enqueue jobs (producer). They do NOT do the heavy work.
  - A worker consumes the queue:
      * QUEUE_BACKEND=redis  -> run `python -m app.worker` separately (production).
      * QUEUE_BACKEND=memory -> we start an in-process worker thread below so the
        whole thing runs with one command and no Redis (local/demo).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pywa import WhatsApp

from app.config import settings
from app.db.session import init_db
from app.handlers import interactions, messages
from app.logging_config import configure_logging, get_logger
from app.queue.factory import build_queue

configure_logging()
logger = get_logger(__name__)

# One shared queue instance for the web process (producer).
queue = build_queue()

# pywa attaches its webhook routes to `app` (created below) and verifies signatures.
# We build the client after the app so we can pass server=app.


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.queue_backend == "memory":
        # Single-process mode: run the consumer in a background thread against the
        # SAME in-memory queue instance the producer uses.
        from app.worker import run_loop_in_thread

        run_loop_in_thread(wa, queue)
        logger.info("in-process worker thread started (memory backend)")
    logger.info("shopping-bot web started (backend=%s)", settings.queue_backend)
    yield


app = FastAPI(title="shopping-bot", lifespan=lifespan)

wa = WhatsApp(
    phone_id=settings.wa_phone_id,
    token=settings.wa_token,
    server=app,
    verify_token=settings.wa_verify_token,
    app_secret=settings.wa_app_secret,
)

# Register thin producer handlers.
messages.register(wa, queue)
interactions.register(wa, queue)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
