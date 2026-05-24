"""Job processing — the consumer-side work.

This is what the worker runs for each dequeued job. It mirrors the old inline
handler logic, but sends replies via the WhatsApp client (`wa.send_message`)
because the worker is a separate process and has no `msg` object to reply to.

Reused by both:
  - the standalone worker (Redis backend, separate process)
  - the in-process worker thread (memory backend, single process)
"""

from __future__ import annotations

from pywa import WhatsApp
from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.session import get_session
from app.domain.models import User
from app.logging_config import get_logger
from app.queue.base import IncomingJob
from app.services import whatsapp as wa_msg
from app.services.lists import HELP_TEXT, handle_intent
from app.services.parser import parse_message

logger = get_logger(__name__)


def process_job(wa: WhatsApp, job: IncomingJob) -> None:
    if job.kind == "message":
        _process_message(wa, job)
    elif job.kind == "selection":
        _process_selection(wa, job)
    elif job.kind == "button":
        _process_button(wa, job)
    else:  # pragma: no cover - defensive
        logger.warning("unknown job kind: %r", job.kind)


# --- per-kind handlers -----------------------------------------------------


def _process_message(wa: WhatsApp, job: IncomingJob) -> None:
    # Parse OUTSIDE the DB session (network call to Claude).
    intent = parse_message(job.text or "")
    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        result = handle_intent(session, user, intent)
        if result.reply_text:
            wa.send_message(to=job.phone, text=result.reply_text)
        if result.show_list:
            _send_list(wa, job.phone, session, user)


def _process_selection(wa: WhatsApp, job: IncomingJob) -> None:
    data = job.callback_data or ""
    if not data.startswith("buy:"):
        return
    try:
        item_id = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        logger.warning("bad buy callback data: %r", data)
        return

    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        item = repo.mark_item_bought(session, item_id, user.id)
        if item is None:
            wa.send_message(to=job.phone, text="הפריט כבר לא קיים ברשימה.")
            return
        wa.send_message(to=job.phone, text=f"סימנתי שנקנה: {item.text} ✓")
        _send_list(wa, job.phone, session, user)


def _process_button(wa: WhatsApp, job: IncomingJob) -> None:
    data = job.callback_data or ""
    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        if data == "cmd:list":
            _send_list(wa, job.phone, session, user)
        elif data == "cmd:clear":
            active_list = repo.get_active_list(session, user.family_id)
            count = repo.clear_bought(session, active_list.id)
            wa.send_message(to=job.phone, text=f"ניקיתי {count} פריטים שנקנו. ✨")
            _send_list(wa, job.phone, session, user)
        elif data == "cmd:help":
            wa.send_message(to=job.phone, text=HELP_TEXT)
        else:
            logger.warning("unknown command button: %r", data)


# --- helpers ---------------------------------------------------------------


def _send_list(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    active_list = repo.get_active_list(session, user.family_id)
    needed = repo.get_needed_items(session, active_list.id)
    body, section_list = wa_msg.build_list_message(needed)
    if section_list is None:
        wa.send_message(to=phone, text=body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)
