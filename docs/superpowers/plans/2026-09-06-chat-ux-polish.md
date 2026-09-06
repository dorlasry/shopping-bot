# Chat UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typing indicator/read-receipt to the worker, and attach the
already-built quick-reply buttons to every reply that ends a turn without a
list message following it.

**Architecture:** Both changes live entirely in `app/processing.py` (the
worker's per-job dispatcher). Feature B (typing indicator) adds one call at
the top of `process_job()`. Feature A (quick buttons) adds one helper,
`_send_final()`, and swaps specific `wa.send_message(...)` call sites to use
it. No new modules, no schema changes, no changes to `app/services/whatsapp.py`
(`quick_command_buttons()` already exists and is correct).

**Tech Stack:** Python 3.11, pytest, pywa (`WhatsApp.indicate_typing`,
`Button`, `SectionList`), SQLAlchemy (in-memory SQLite for tests).

## Global Constraints

- A WhatsApp message can carry at most one interactive component: either the
  tappable item list (`SectionList`) or up to 3 reply buttons — never both.
  This is why buttons are attached only where no list message follows.
- `_indicate_typing`'s call to `wa.indicate_typing` must be wrapped in
  `try/except Exception`, logged at `warning` level, and never propagate — a
  cosmetic feature must not block real job processing.
- New tests live in `tests/test_processing.py`, follow the existing style in
  `tests/test_lists.py` (plain functions, the shared `session` fixture from
  `tests/conftest.py`, no real network/Claude/OpenAI/WhatsApp calls).
- Dev dependencies (pytest) are not currently installed in `.venv`; Task 1
  installs them.

---

## File Structure

- **Modify:** `app/processing.py` — add `_indicate_typing()` (Task 1) and
  `_send_final()` (Task 2); swap specific call sites (Task 2).
- **Create:** `tests/test_processing.py` — `FakeWhatsApp` test double, a
  `patch_get_session` fixture, and behavioral tests for both features.

---

### Task 1: Typing indicator (read receipt + "typing…" bubble)

**Files:**
- Modify: `app/processing.py:32-42` (`process_job`)
- Create: `tests/test_processing.py`

**Interfaces:**
- Produces: `processing._indicate_typing(wa: WhatsApp, job: IncomingJob) -> None`
  — called from `process_job` before dispatch. Task 2 does not call this
  directly but must not remove or rename it.
- Produces (test infra, reused by Task 2): `FakeWhatsApp` class with
  `.sent: list[dict]` (each `{"to": str, "text": str, "buttons": Any | None}`)
  and `.typing_calls: list[str]`; the `patch_get_session` autouse fixture in
  `tests/test_processing.py`.

- [ ] **Step 1: Install dev dependencies**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs `pytest` (and `ruff`) into `.venv` without error.

- [ ] **Step 2: Create `tests/test_processing.py` with test infra and the failing tests**

```python
"""Tests for the worker-side job processing (app.processing).

Uses a FakeWhatsApp double instead of the real pywa client — no network calls.
DB access reuses the in-memory `session` fixture from conftest.py by
monkeypatching app.processing.get_session to yield it directly.
"""

from __future__ import annotations

import contextlib

import pytest

from app import processing
from app.domain.schemas import ParsedIntent
from app.queue.base import IncomingJob
from app.services.lists import HELP_TEXT


class FakeWhatsApp:
    """Records send_message/indicate_typing calls instead of hitting the network."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.typing_calls: list[str] = []

    def send_message(self, *, to, text, buttons=None, **kwargs):
        self.sent.append({"to": to, "text": text, "buttons": buttons})

    def indicate_typing(self, *, message_id, **kwargs):
        self.typing_calls.append(message_id)


@pytest.fixture(autouse=True)
def patch_get_session(monkeypatch, session):
    @contextlib.contextmanager
    def _fake_get_session():
        yield session

    monkeypatch.setattr(processing, "get_session", _fake_get_session)


def test_indicate_typing_called_for_message(monkeypatch, session):
    monkeypatch.setattr(
        processing, "parse_message", lambda text: ParsedIntent(action="help")
    )
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="message",
        phone="972500000001",
        name="Tester",
        message_id="wamid.1",
        text="עזרה",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.1"]


def test_indicate_typing_called_for_audio(monkeypatch, session):
    monkeypatch.setattr(processing.transcription, "is_enabled", lambda: False)
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="audio",
        phone="972500000002",
        name="Tester",
        message_id="wamid.2",
        media_id="media123",
        mime_type="audio/ogg",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.2"]


def test_indicate_typing_called_for_selection(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="selection",
        phone="972500000003",
        name="Tester",
        message_id="wamid.3",
        callback_data="buy:9999",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.3"]


def test_indicate_typing_called_for_button(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000004",
        name="Tester",
        message_id="wamid.4",
        callback_data="cmd:help",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.4"]


def test_indicate_typing_failure_does_not_block_reply(monkeypatch, session):
    monkeypatch.setattr(
        processing, "parse_message", lambda text: ParsedIntent(action="help")
    )
    fake_wa = FakeWhatsApp()

    def boom(*, message_id, **kwargs):
        raise RuntimeError("boom")

    fake_wa.indicate_typing = boom
    job = IncomingJob(
        kind="message",
        phone="972500000005",
        name="Tester",
        message_id="wamid.5",
        text="עזרה",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 1
    assert fake_wa.sent[0]["to"] == "972500000005"
    assert fake_wa.sent[0]["text"] == HELP_TEXT
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v`
Expected: 4 tests FAIL —
`test_indicate_typing_called_for_message`,
`test_indicate_typing_called_for_audio`,
`test_indicate_typing_called_for_selection`, and
`test_indicate_typing_called_for_button` each fail with
`assert [] == ["wamid.N"]`, since nothing calls `indicate_typing` yet.

`test_indicate_typing_failure_does_not_block_reply` already PASSES at this
point — `process_job` never calls `wa.indicate_typing`, so the `boom`
override is never triggered, and the help reply is sent normally. That's
expected and fine: this test's real job is to prove the try/except in Step 4
doesn't swallow the reply, which Step 5 re-confirms once `boom` actually gets
called.

- [ ] **Step 4: Implement `_indicate_typing` and wire it into `process_job`**

In `app/processing.py`, replace:

```python
def process_job(wa: WhatsApp, job: IncomingJob) -> None:
    if job.kind == "message":
        _process_message(wa, job)
    elif job.kind == "audio":
        _process_audio(wa, job)
    elif job.kind == "selection":
        _process_selection(wa, job)
    elif job.kind == "button":
        _process_button(wa, job)
    else:  # pragma: no cover - defensive
        logger.warning("unknown job kind: %r", job.kind)
```

with:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_processing.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/processing.py tests/test_processing.py
git commit -m "$(cat <<'EOF'
Add typing indicator + read receipt to worker job processing

wa.indicate_typing marks the incoming message read and shows a
"typing..." bubble while the worker does the real work (Claude parse,
transcription, DB), so a slow turn no longer looks like a dropped
message. Called once at the top of process_job for every job kind;
wrapped in try/except so a failure here never blocks the actual reply.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Quick-reply buttons on dead-end replies

**Files:**
- Modify: `app/processing.py:48-150` (`_process_audio`, `_handle_text`,
  `_process_selection`, `_process_button`, `_send_list`)
- Modify: `tests/test_processing.py` (append tests)

**Interfaces:**
- Consumes: `processing._indicate_typing` and `FakeWhatsApp` /
  `patch_get_session` from Task 1 (already in place; not modified here).
  `wa_msg.quick_command_buttons() -> list[Button]` from
  `app/services/whatsapp.py` (already exists, unchanged).
- Produces: `processing._send_final(wa: WhatsApp, phone: str, text: str) -> None`
  — sends `text` with `buttons=wa_msg.quick_command_buttons()` attached. Used
  by every "dead-end" reply (no list message follows in the same turn).

- [ ] **Step 1: Append the failing tests to `tests/test_processing.py`**

Add these imports to the top of the file (alongside the existing ones):

```python
from app.db import repository as repo
from app.services import whatsapp as wa_msg
from pywa.types import SectionList
```

Append these tests at the end of the file:

```python
def test_help_button_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000006",
        name="Tester",
        message_id="wamid.6",
        callback_data="cmd:help",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000006",
            "text": HELP_TEXT,
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def test_stale_selection_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="selection",
        phone="972500000007",
        name="Tester",
        message_id="wamid.7",
        callback_data="buy:9999",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000007",
            "text": "הפריט כבר לא קיים ברשימה.",
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def test_add_item_message_no_buttons_before_list(monkeypatch, session):
    monkeypatch.setattr(
        processing,
        "parse_message",
        lambda text: ParsedIntent(action="add", items=["חלב"]),
    )
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="message",
        phone="972500000008",
        name="Tester",
        message_id="wamid.8",
        text="תביא חלב",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 2
    assert fake_wa.sent[0]["buttons"] is None
    assert "הוספתי" in fake_wa.sent[0]["text"]
    assert isinstance(fake_wa.sent[1]["buttons"], SectionList)


def test_cmd_clear_button_no_buttons_before_list(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000009",
        name="Tester",
        message_id="wamid.9",
        callback_data="cmd:clear",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 2
    assert fake_wa.sent[0]["buttons"] is None
    assert fake_wa.sent[0]["text"].startswith("ניקיתי")


def test_cmd_list_empty_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000010",
        name="Tester",
        message_id="wamid.10",
        callback_data="cmd:list",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000010",
            "text": "הרשימה ריקה 🎉",
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v -k "quick_buttons or no_buttons_before_list"`
Expected: `test_help_button_gets_quick_buttons`,
`test_stale_selection_gets_quick_buttons`, and
`test_cmd_list_empty_gets_quick_buttons` FAIL (currently `buttons` is `None`,
not `wa_msg.quick_command_buttons()`).
`test_add_item_message_no_buttons_before_list` and
`test_cmd_clear_button_no_buttons_before_list` should already PASS (those
call sites aren't changing) — confirming they pass today is the point: this
proves Task 2 doesn't need to touch those paths.

- [ ] **Step 3: Add `_send_final` and swap the dead-end call sites**

In `app/processing.py`, replace the body of `_process_audio`:

```python
def _process_audio(wa: WhatsApp, job: IncomingJob) -> None:
    """Voice note: download → transcribe (Hebrew) → process as if it were text."""
    if not transcription.is_enabled():
        wa.send_message(
            to=job.phone, text="זיהוי קולי עדיין לא מוגדר 🙏 נסו לכתוב הודעת טקסט."
        )
        return
    if not job.media_id:
        return

    try:
        audio_bytes, mime_type = download_media(job.media_id)
        transcript = transcription.transcribe(audio_bytes, mime_type)
    except Exception:  # noqa: BLE001 — a bad recording must not crash the worker
        logger.exception("voice transcription failed for %s", job.message_id)
        wa.send_message(
            to=job.phone, text="לא הצלחתי להבין את ההקלטה 🎤 נסו שוב או כתבו טקסט."
        )
        return

    if not transcript:
        wa.send_message(to=job.phone, text="לא שמעתי כלום בהקלטה 🤔 נסו שוב.")
        return

    # Echo what we heard so the user can catch any mis-transcription, then act.
    wa.send_message(to=job.phone, text=f"🎤 שמעתי: {transcript}")
    _handle_text(wa, job.phone, job.name, transcript)
```

with:

```python
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
```

Replace the body of `_handle_text`:

```python
def _handle_text(wa: WhatsApp, phone: str, name: str, text: str) -> None:
    """Core text pipeline, shared by typed messages and transcribed voice notes."""
    # Unsupported message types (image, sticker, document) arrive with no text.
    # Answer kindly instead of running an empty message through Claude.
    if not text.strip():
        wa.send_message(
            to=phone,
            text="אני קורא טקסט ומאזין להקלטות קוליות 🙂 כתבו או הקליטו מה להביא.",
        )
        return

    # Parse OUTSIDE the DB session (network call to Claude).
    intent = parse_message(text)
    with get_session() as session:
        user = repo.get_or_create_user(session, phone, name)
        result = handle_intent(session, user, intent)
        if result.reply_text:
            wa.send_message(to=phone, text=result.reply_text)
        if result.show_list:
            _send_list(wa, phone, session, user)
```

with:

```python
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
        if result.reply_text:
            # A list message follows only when show_list is True — skip the
            # quick buttons then so we don't send two interactive messages.
            if result.show_list:
                wa.send_message(to=phone, text=result.reply_text)
            else:
                _send_final(wa, phone, result.reply_text)
        if result.show_list:
            _send_list(wa, phone, session, user)
```

Replace the body of `_process_selection`:

```python
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
```

with:

```python
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
            _send_final(wa, job.phone, "הפריט כבר לא קיים ברשימה.")
            return
        wa.send_message(to=job.phone, text=f"סימנתי שנקנה: {item.text} ✓")
        _send_list(wa, job.phone, session, user)
```

In `_process_button`, replace:

```python
        elif data == "cmd:help":
            wa.send_message(to=job.phone, text=HELP_TEXT)
```

with:

```python
        elif data == "cmd:help":
            _send_final(wa, job.phone, HELP_TEXT)
```

Replace the body of `_send_list` and add `_send_final` right after it:

```python
def _send_list(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    active_list = repo.get_active_list(session, user.family_id)
    needed = repo.get_needed_items(session, active_list.id)
    body, section_list = wa_msg.build_list_message(needed)
    if section_list is None:
        wa.send_message(to=phone, text=body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)
```

with:

```python
def _send_list(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    active_list = repo.get_active_list(session, user.family_id)
    needed = repo.get_needed_items(session, active_list.id)
    body, section_list = wa_msg.build_list_message(needed)
    if section_list is None:
        _send_final(wa, phone, body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)


def _send_final(wa: WhatsApp, phone: str, text: str) -> None:
    """Send a reply that ends the turn (no list message follows), with the
    quick-command buttons attached so the user has something to tap next."""
    wa.send_message(to=phone, text=text, buttons=wa_msg.quick_command_buttons())
```

- [ ] **Step 4: Run the full test file to verify everything passes**

Run: `.venv/bin/pytest tests/test_processing.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `.venv/bin/pytest -v`
Expected: all tests across `tests/test_lists.py`, `tests/test_repository.py`,
and `tests/test_processing.py` PASS.

- [ ] **Step 6: Commit**

```bash
git add app/processing.py tests/test_processing.py
git commit -m "$(cat <<'EOF'
Wire quick-reply buttons into dead-end replies

quick_command_buttons() (רשימה/נקה/עזרה) existed but was never called.
A new _send_final() helper attaches it to every reply that ends a turn
without a list message following (greeting/help/unknown/errors/empty
list), while leaving confirmations that are immediately followed by
the tappable item list unchanged, since a WhatsApp message can only
carry one interactive component at a time.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Manual Verification (optional, after both tasks)

If you want to see this live rather than just in tests:

```bash
cp .env.example .env   # fill in WA_*, ANTHROPIC_API_KEY (QUEUE_BACKEND=memory)
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
python scripts/simulate_webhook.py "עזרה"
```

Expected: the simulated reply now carries the three quick-reply buttons
(רשימה / נקה / עזרה) since help is a dead-end. Check the server log for the
`indicate_typing` call preceding it (or watch a real WhatsApp chat via ngrok
for the "typing…" bubble).
