# Chat UX polish: quick-reply buttons + typing indicator

Date: 2026-09-06

## Context

The bot currently has two chat-UX gaps found while reviewing `app/processing.py`
and `app/services/whatsapp.py`:

1. `quick_command_buttons()` (רשימה / נקה / עזרה) is fully implemented in
   `app/services/whatsapp.py` but never called anywhere — dead code. Users must
   type a Hebrew command every time instead of tapping.
2. There is no read receipt or "typing…" feedback. The pipeline is
   webhook → queue → worker, and voice notes additionally go through
   transcription before a reply is sent, so on a slow turn the user has no
   signal the bot received the message and may re-send.

Both are scoped as small, additive changes to `app/processing.py`; no new
modules, no schema changes.

## Feature A: quick-reply buttons on dead-end replies

**Constraint:** a WhatsApp message carries at most one interactive component —
either the tappable item list (`SectionList`) or up to 3 reply buttons, never
both.

**Rule:** attach `quick_command_buttons()` to a reply whenever that reply ends
the turn (no list message follows it). Omit them whenever `_send_list` fires
right after in the same turn — the list itself is already the tap surface, and
a second interactive message immediately after it would be clutter.

Call sites in `app/processing.py` that gain buttons (all are currently
dead-ends with a bare `wa.send_message(to=..., text=...)`):

- `_handle_text`: the `handle_intent` result branch where `result.show_list`
  is `False` — covers greeting, help, unknown, "לא הוספתי כלום", "לא מצאתי",
  "הרשימה כבר ריקה" (bought_all on an empty list).
- Empty-text fallback ("אני קורא טקסט ומאזין להקלטות קוליות...").
- Audio dead-ends: transcription not enabled, transcription failed, empty
  transcript.
- `_process_selection`: "הפריט כבר לא קיים ברשימה" (stale row tapped).
- `_process_button`: the `cmd:help` branch (sends `HELP_TEXT`).
- `_send_list`: when the list is empty (`section_list is None`, currently a
  bare "הרשימה ריקה 🎉" text) — this becomes a dead-end reply too, so it gets
  buttons.

Call sites that stay plain (a list message follows in the same turn, so no
buttons): the `add`/`bought`/`remove`/`clear` confirmation texts in
`_handle_text`, the "🎤 שמעתי: ..." transcript echo (not a dead-end — text
processing continues right after), the "סימנתי שנקנה: ..." confirmation in
`_process_selection`, and the `cmd:clear` confirmation in `_process_button`.

**Implementation shape:** a small private helper in `processing.py`, e.g.
`_send_final(wa, phone, text)`, that sends with
`buttons=wa_msg.quick_command_buttons()`. Existing plain `wa.send_message`
calls before a list send are left untouched. No changes needed to
`app/services/whatsapp.py` — `quick_command_buttons()` is already correct.

## Feature B: typing indicator / read receipt

pywa's `WhatsApp.indicate_typing(message_id=...)` marks the incoming message
read and shows a "typing…" bubble, which WhatsApp auto-dismisses when our
reply is sent (or after 25s). It needs only `message_id`, which every
`IncomingJob` already carries for all four job kinds.

**Placement:** called once at the top of `process_job()` in
`app/processing.py`, before dispatching by `job.kind`. This intentionally
lives in the **worker**, not the producer handlers — the producer's job is to
ACK Meta instantly and enqueue (per the existing architecture), so it must not
make an extra network call to Meta before returning. The worker is already
about to do the real work (Claude parse, DB write, or transcription), which is
exactly when "seen + typing" should appear.

**Error handling:** wrapped in `try/except Exception`, logged at `warning`
level and swallowed — same defensive style already used around transcription
in `_process_audio`. A failed typing-indicator call must never block or crash
real job processing.

## Testing

New file `tests/test_processing.py`, following the existing pattern in
`tests/test_lists.py` (construct inputs directly, no real Claude/WhatsApp/DB
network calls — DB uses the existing in-memory `session` fixture).

A `FakeWhatsApp` test double replaces the real `pywa.WhatsApp` client,
recording `send_message` and `indicate_typing` calls (to, text, buttons
present/absent) without making network calls. `parse_message`,
`transcription`, and `download_media` are monkeypatched per-test as needed so
no external services are touched.

Covered cases:

- `indicate_typing` is called exactly once per job, for each of the four job
  kinds (message, audio, selection, button).
- A dead-end reply (help/greeting/unknown/empty-list/stale-selection/audio
  errors) is sent with `quick_command_buttons()` attached.
- A reply followed by `_send_list` (add/bought/remove/clear, and the
  cmd:clear button) is sent *without* buttons attached — no double
  interactive message.
- `indicate_typing` failing (raises) does not prevent the job's actual reply
  from being sent.

## Out of scope

Everything else surfaced during exploration but not requested for this pass:
confirmation/undo for destructive actions (נקה, bought_all, remove), richer
error-message content, onboarding/family invites, categories/grouping. These
stay on the README roadmap, untouched here.
