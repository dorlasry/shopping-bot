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
from pywa.types import FlowButton
from pywa.types.flows import FlowActionType, FlowStatus
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repository as repo
from app.db.session import get_session
from app.domain.models import User
from app.domain.schemas import ParsedIntent
from app.logging_config import get_logger
from app.queue.base import IncomingJob
from app.services import flows as flow_msg
from app.services import transcription
from app.services import whatsapp as wa_msg
from app.services.lists import HELP_TEXT, ActionResult, handle_intent
from app.services.media import download_media
from app.services.parser import parse_message

logger = get_logger(__name__)


def process_job(wa: WhatsApp, job: IncomingJob) -> None:
    _indicate_typing(wa, job)
    if job.kind == "message":
        _process_message(wa, job)
    elif job.kind == "audio":
        _process_audio(wa, job)
    elif job.kind == "selection":
        _process_selection(wa, job)
    elif job.kind == "button":
        _process_button(wa, job)
    elif job.kind == "flow_completion":
        _process_flow_completion(wa, job)
    else:  # pragma: no cover - defensive
        logger.warning("unknown job kind: %r", job.kind)


def _indicate_typing(wa: WhatsApp, job: IncomingJob) -> None:
    """Mark the incoming message read and show a typing bubble.

    Best-effort only: WhatsApp auto-dismisses this when we send our reply (or
    after 25s), and a failure here must never block real job processing.
    """
    try:
        wa.indicate_typing(message_id=job.message_id)
    except Exception:  # noqa: BLE001 — cosmetic only, never fatal
        logger.warning("indicate_typing failed for %s", job.message_id)


# --- per-kind handlers -----------------------------------------------------


def _process_message(wa: WhatsApp, job: IncomingJob) -> None:
    _handle_text(wa, job.phone, job.name, job.text or "")


def _process_audio(wa: WhatsApp, job: IncomingJob) -> None:
    """Voice note: download → transcribe (Hebrew) → process as if it were text."""
    if not transcription.is_enabled():
        _send_final(wa, job.phone, "זיהוי קולי עדיין לא מוגדר 🙏 נסו לכתוב הודעת טקסט.")
        return
    if not job.media_id:
        return

    try:
        audio_bytes, mime_type = download_media(job.media_id)
        transcript = transcription.transcribe(audio_bytes, mime_type)
    except Exception:  # noqa: BLE001 — a bad recording must not crash the worker
        logger.exception("voice transcription failed for %s", job.message_id)
        _send_final(wa, job.phone, "לא הצלחתי להבין את ההקלטה 🎤 נסו שוב או כתבו טקסט.")
        return

    if not transcript:
        _send_final(wa, job.phone, "לא שמעתי כלום בהקלטה 🤔 נסו שוב.")
        return

    # Echo what we heard so the user can catch any mis-transcription, then act.
    wa.send_message(to=job.phone, text=f"🎤 שמעתי: {transcript}")
    _handle_text(wa, job.phone, job.name, transcript)


def _handle_text(wa: WhatsApp, phone: str, name: str, text: str) -> None:
    """Core text pipeline, shared by typed messages and transcribed voice notes."""
    # Unsupported message types (image, sticker, document) arrive with no text.
    # Answer kindly instead of running an empty message through Claude.
    if not text.strip():
        _send_final(
            wa, phone, "אני קורא טקסט ומאזין להקלטות קוליות 🙂 כתבו או הקליטו מה להביא."
        )
        return

    # Parse OUTSIDE the DB session (network call to Claude).
    intent = parse_message(text)
    with get_session() as session:
        user = repo.get_or_create_user(session, phone, name)
        result = handle_intent(session, user, intent)
        _deliver(wa, phone, session, user, result)


def _process_selection(wa: WhatsApp, job: IncomingJob) -> None:
    data = job.callback_data or ""
    if data.startswith("buy:"):
        _process_buy(wa, job, data)
    elif data.startswith("readd:"):
        _process_readd(wa, job, data)
    else:
        logger.warning("unknown selection callback data: %r", data)


def _process_buy(wa: WhatsApp, job: IncomingJob, data: str) -> None:
    try:
        item_id = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        logger.warning("bad buy callback data: %r", data)
        return

    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        item = repo.mark_item_bought(session, item_id, user.id)
        if item is None:
            _send_final(wa, job.phone, "הפריט כבר לא קיים ברשימה.")
            return
        wa.send_message(to=job.phone, text=f"סימנתי שנקנה: {item.text} ✓")
        _send_list(wa, job.phone, session, user)


def _process_readd(wa: WhatsApp, job: IncomingJob, data: str) -> None:
    """Add back an item picked from the past-items list, then offer the rest.

    The item just added is now needed, so the query drops it from the refreshed
    picker on its own — tapping through several in a row needs no bookkeeping.
    """
    text = data.split(":", 1)[1].strip()
    if not text:
        logger.warning("empty readd callback data: %r", data)
        return

    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        result = handle_intent(session, user, ParsedIntent(action="add", items=[text]))
        if result.reply_text:
            wa.send_message(to=job.phone, text=result.reply_text)

        remaining = _past_item_texts(session, user, wa_msg.MAX_PAST_LISTED)
        if not remaining:
            # An empty picker would be a dead end; show what is on the list now.
            _send_list(wa, job.phone, session, user)
            return
        # A readd: callback can only come from a list row (the Flow has no such
        # callback), so the refreshed picker is always the list regardless of
        # settings.wa_past_items_flow_id.
        _send_past_items_list(wa, job.phone, remaining)


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
            _send_final(wa, job.phone, HELP_TEXT)
        elif data == "cmd:past_items":
            _send_past_items(wa, job.phone, session, user)
        else:
            logger.warning("unknown command button: %r", data)


def _process_flow_completion(wa: WhatsApp, job: IncomingJob) -> None:
    """Add the items the user ticked in the past-items flow.

    Routed through the normal `add` intent so it reuses the existing
    confirmation text, duplicate guard, and list refresh.
    """
    picked = job.picked or []
    if not picked:
        _send_final(wa, job.phone, "לא נבחרו פריטים 🤷")
        return

    with get_session() as session:
        user = repo.get_or_create_user(session, job.phone, job.name)
        result = handle_intent(session, user, ParsedIntent(action="add", items=picked))
        _deliver(wa, job.phone, session, user, result)


# --- helpers ---------------------------------------------------------------


def _deliver(
    wa: WhatsApp, phone: str, session: Session, user: User, result: ActionResult
) -> None:
    """Send an ActionResult: its text, then whatever follow-up it asks for."""
    if result.reply_text:
        # An interactive message follows only when show_list/show_past_items is
        # set — skip the quick buttons then, so we never send two in a row.
        if result.show_list or result.show_past_items:
            wa.send_message(to=phone, text=result.reply_text)
        else:
            _send_final(wa, phone, result.reply_text)
    if result.show_list:
        _send_list(wa, phone, session, user)
    if result.show_past_items:
        _send_past_items(wa, phone, session, user)


def _send_list(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    active_list = repo.get_active_list(session, user.family_id)
    needed = repo.get_needed_items(session, active_list.id)
    body, section_list = wa_msg.build_list_message(needed)
    if section_list is None:
        _send_final(wa, phone, body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)


def _send_past_items(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    """Offer items the family bought before, so they can be added again.

    Sent as a Flow when a flow id is configured, otherwise as an interactive
    list. The list needs no setup and works on accounts where Meta refuses to
    send Flows, so there is always a working path.
    """
    use_flow = bool(settings.wa_past_items_flow_id)
    past = _past_item_texts(
        session,
        user,
        flow_msg.MAX_PAST_ITEMS if use_flow else wa_msg.MAX_PAST_LISTED,
    )

    if use_flow and past:
        wa.send_message(
            to=phone,
            text="הנה מה שקניתם בעבר — בחרו מה להוסיף 👇",
            buttons=FlowButton(
                title="בחרו פריטים",
                flow_id=settings.wa_past_items_flow_id,
                flow_action_type=FlowActionType.NAVIGATE,
                flow_action_screen=flow_msg.SCREEN_ID,
                flow_action_payload=flow_msg.build_items_payload(past),
                mode=FlowStatus.DRAFT,
            ),
        )
        return

    # Also the empty-history path for the Flow: the builder owns that message,
    # so it reads the same whichever delivery is configured.
    _send_past_items_list(wa, phone, past)


def _send_past_items_list(wa: WhatsApp, phone: str, texts: list[str]) -> None:
    """Send the past-items picker as an interactive list."""
    body, section_list = wa_msg.build_past_items_message(texts)
    if section_list is None:
        _send_final(wa, phone, body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)


def _past_item_texts(session: Session, user: User, limit: int) -> list[str]:
    """Texts the family bought before, minus whatever is already on the list."""
    active_list = repo.get_active_list(session, user.family_id)
    needed = {item.text for item in repo.get_needed_items(session, active_list.id)}
    return repo.get_past_bought_items(
        session, user.family_id, exclude_texts=needed, limit=limit
    )


def _send_final(wa: WhatsApp, phone: str, text: str) -> None:
    """Send a reply that ends the turn (no list message follows), with the
    quick-command buttons attached so the user has something to tap next."""
    wa.send_message(to=phone, text=text, buttons=wa_msg.quick_command_buttons())
