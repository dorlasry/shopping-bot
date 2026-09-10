# Past-Items Interactive-List Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the past-items picker as an interactive list message when no Flow id is configured, so the feature works on accounts where Meta blocks Flow sends.

**Architecture:** `WA_PAST_ITEMS_FLOW_ID` becomes the delivery selector — set sends the existing Flow, empty sends a `SectionList` whose rows carry `readd:<item text>`. Tapping a row routes through the existing `add` intent and then re-shows the picker minus that item, giving sequential multi-select. The Flow code is untouched and returns the day Meta's integrity gate clears.

**Tech Stack:** Python 3.12, pywa 3.9, SQLAlchemy 2.0, pytest, ruff.

## Global Constraints

- **Nothing about the Flow path changes.** `app/services/flows.py`, `scripts/setup_flow.py`, `_process_flow_completion`, the `flow_completion` job kind and their tests stay exactly as they are.
- **The selector is `settings.wa_past_items_flow_id`**: truthy → Flow, empty → interactive list. No new setting.
- **The "הפיצ'ר הזה עדיין לא מוכן 🙏" branch is deleted.** With a fallback there is always a working path, so that dead-end no longer exists.
- WhatsApp limits already encoded in `app/services/whatsapp.py`: at most `MAX_ROWS` (10) tappable rows, `SectionRow` title 24 chars (use the existing `truncate`), list button title ≤20 chars.
- A `SectionRow` callback id is capped at **200 characters**; `Item.text` is `String(200)`, so an over-long callback is possible and must be skipped rather than sent.
- One interactive component per message: a confirmation that precedes a list goes out as plain text, matching `_process_selection`'s existing `buy:` flow.
- Existing dedup convention: item text compared with `.strip().lower()`.
- Hebrew strings are user-facing copy — match them character for character. Note `app/services/lists.py` contains curly quotes (`“` U+201C, `”` U+201D) inside double-quoted Python strings; you should not need to touch that file, but never rewrite those as straight quotes.
- Baseline before this plan: `.venv/bin/pytest` is green, and `.venv/bin/ruff check app tests` reports 9 pre-existing findings in files this plan does not touch. Introduce no new ones.

---

## File Structure

- **Modify** `app/services/whatsapp.py` — add `build_past_items_message` plus its two constants, beside the existing `build_list_message` it mirrors.
- **Modify** `app/processing.py` — split `_send_past_items` into a query helper and the two delivery branches; add the `readd:` selection branch.
- **Modify** `README.md` — document the selector.
- **Modify** `tests/test_whatsapp.py`, `tests/test_processing.py`.

---

### Task 1: The list message builder

**Files:**
- Modify: `app/services/whatsapp.py` (constants near line 19-20; new function after `build_list_message`)
- Test: `tests/test_whatsapp.py`

**Interfaces:**
- Produces: `build_past_items_message(texts: list[str]) -> tuple[str, SectionList | None]`, and the constants `MAX_PAST_LISTED = 20` and `MAX_CALLBACK_CHARS = 200`. Tasks 2 and 3 use all three.
- Consumes: the existing `truncate(text, limit)`, `MAX_ROWS`, `Section`, `SectionRow`, `SectionList` in this module.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_whatsapp.py`, and add `from app.services.whatsapp import build_past_items_message` plus `from pywa.types import SectionList` to its imports:

```python
def test_past_items_message_empty():
    body, section = build_past_items_message([])
    assert section is None
    assert "היסטוריה" in body


def test_past_items_message_lists_and_makes_rows():
    body, section = build_past_items_message(["חלב", "גבינה"])

    assert "1. חלב" in body
    assert "2. גבינה" in body
    assert isinstance(section, SectionList)
    rows = section.sections[0].rows
    assert [r.callback_data for r in rows] == ["readd:חלב", "readd:גבינה"]
    assert [r.title for r in rows] == ["חלב", "גבינה"]


def test_past_items_message_caps_tappable_rows_at_ten():
    texts = [f"פריט {n}" for n in range(1, 13)]

    body, section = build_past_items_message(texts)

    assert len(section.sections[0].rows) == 10
    # All twelve are still readable in the body, and the note explains that
    # only the first ten are tappable.
    assert "12. פריט 12" in body
    assert "אפשר להקיש על 10 הראשונים" in body


def test_past_items_message_truncates_row_title_but_not_callback():
    long_name = "נייר טואלט אקסטרה רך 24 גלילים במבצע"

    body, section = build_past_items_message([long_name])

    row = section.sections[0].rows[0]
    assert len(row.title) == 24
    assert row.title.endswith("…")
    # The callback keeps the full text, so the right item gets added.
    assert row.callback_data == f"readd:{long_name}"


def test_past_items_message_skips_item_too_long_for_a_callback():
    huge = "א" * 200

    body, section = build_past_items_message(["חלב", huge])

    assert [r.callback_data for r in section.sections[0].rows] == ["readd:חלב"]
    # It is still offered in the body, where it can be added by typing.
    assert huge in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_whatsapp.py -v`
Expected: collection FAILS with `ImportError: cannot import name 'build_past_items_message' from 'app.services.whatsapp'`.

- [ ] **Step 3: Add the constants**

In `app/services/whatsapp.py`, replace:

```python
LIST_BUTTON_TITLE = "סמן שנקנה"  # must be <= 20 chars
MAX_ROWS = 10
```

with:

```python
LIST_BUTTON_TITLE = "סמן שנקנה"  # must be <= 20 chars
PAST_BUTTON_TITLE = "הוסיפו לרשימה"  # must be <= 20 chars
MAX_ROWS = 10

# How many past items the picker names in the body text. Only the first
# MAX_ROWS of them are tappable; the rest can be added by typing.
MAX_PAST_LISTED = 20

# WhatsApp caps a row's callback id at 200 characters.
MAX_CALLBACK_CHARS = 200
```

- [ ] **Step 4: Write the builder**

In `app/services/whatsapp.py`, add directly after `build_list_message`:

```python
def build_past_items_message(texts: list[str]) -> tuple[str, SectionList | None]:
    """Return (body_text, interactive_list) offering previously-bought items.

    Mirrors build_list_message: the body names everything on offer, and the
    first MAX_ROWS become tappable rows that add the item back to the list.
    If there is nothing to offer — or nothing that fits in a callback — the
    interactive list is None and the caller should just send the body.
    """
    if not texts:
        return "אין עדיין היסטוריה של קניות 🤷 קנו משהו קודם.", None

    lines = [f"{idx}. {text}" for idx, text in enumerate(texts, start=1)]
    body = "🕘 מה שקניתם בעבר:\n" + "\n".join(lines)

    # A pathologically long name cannot fit in a callback id, so it is offered
    # in the body only.
    rows = [
        SectionRow(title=truncate(text, 24), callback_data=f"readd:{text}")
        for text in texts[:MAX_ROWS]
        if len(f"readd:{text}") <= MAX_CALLBACK_CHARS
    ]
    if not rows:
        return body, None

    if len(texts) > len(rows):
        body += (
            f"\n\nאפשר להקיש על {len(rows)} הראשונים, "
            'או פשוט לכתוב "תביא <שם הפריט>" לכל פריט אחר.'
        )
    else:
        body += "\n\nהקישו על הכפתור למטה כדי להוסיף לרשימה 👇"

    section = Section(title="להוסיף שוב", rows=rows)
    return body, SectionList(button_title=PAST_BUTTON_TITLE, sections=[section])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_whatsapp.py -v`
Expected: all PASS, including the pre-existing `test_quick_command_buttons`.

- [ ] **Step 6: Commit**

```bash
git add app/services/whatsapp.py tests/test_whatsapp.py
git commit -m "$(cat <<'EOF'
Add the past-items interactive-list builder

Mirrors build_list_message: names every offered item in the body, makes
the first ten tappable with readd: callbacks, and skips any name too long
for WhatsApp's 200-character callback id.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The delivery selector

**Files:**
- Modify: `app/processing.py:200-233` (`_send_past_items`)
- Modify: `README.md:139-180` and the env-var table at `README.md:238`
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `wa_msg.build_past_items_message`, `wa_msg.MAX_PAST_LISTED` (Task 1); `flow_msg.MAX_PAST_ITEMS`; `repo.get_past_bought_items`.
- Produces: `_past_item_texts(session: Session, user: User, limit: int) -> list[str]` — Task 3 calls it.

- [ ] **Step 1: Update the outdated test and add the new ones**

In `tests/test_processing.py`, **replace** `test_past_items_button_when_flow_not_configured` — it asserts the "not ready" message, which this task deletes — with:

```python
def test_past_items_without_flow_sends_interactive_list(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    monkeypatch.setattr(
        processing.repo, "get_past_bought_items", lambda *a, **k: ["חלב", "גבינה"]
    )
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    section = fake_wa.sent[0]["buttons"]
    assert isinstance(section, SectionList)
    assert [r.callback_data for r in section.sections[0].rows] == [
        "readd:חלב",
        "readd:גבינה",
    ]


def test_past_items_without_flow_and_no_history(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    monkeypatch.setattr(processing.repo, "get_past_bought_items", lambda *a, **k: [])
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    assert "היסטוריה" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()
```

Leave `test_past_items_button_sends_flow` and `test_past_items_button_without_history` exactly as they are — the Flow path is unchanged.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v -k past_items`
Expected: `test_past_items_without_flow_sends_interactive_list` FAILS — with the flow id empty the current code sends the "not ready" text, so `buttons` is the quick-reply list, not a `SectionList`. `test_past_items_without_flow_and_no_history` FAILS on `"היסטוריה" in ...` for the same reason.

- [ ] **Step 3: Rewrite `_send_past_items`**

In `app/processing.py`, replace the whole of `_send_past_items` with:

```python
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
    body, section_list = wa_msg.build_past_items_message(past)
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
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS. `test_past_items_button_without_history` still passes because the builder's empty message contains the same "אין עדיין היסטוריה של קניות 🤷 קנו משהו קודם." text the deleted branch used.

- [ ] **Step 5: Document the selector**

In `README.md`, change the heading at line 139 from `## Past-items picker (WhatsApp Flow)` to `## Past-items picker`, and insert this paragraph directly beneath it, before the existing setup steps:

```markdown
The picker has two delivery modes, chosen by whether `WA_PAST_ITEMS_FLOW_ID` is
set:

- **set** — a WhatsApp Flow with checkboxes, so several items can be picked at
  once. Needs the one-time setup below.
- **empty** — an interactive list: tap an item to add it, and the list comes
  straight back minus that item, so you tap through several in a row. No setup
  at all.

Start with the list. Meta blocks Flow sends on accounts that don't meet its
integrity requirements (error `139000`, common on unverified businesses and test
numbers), and the list has no such gate. Set the flow id once Flows work for
your account.
```

Then update the env-var table row at line 238 to read:

```markdown
| `WA_PAST_ITEMS_FLOW_ID` | flow id from `scripts/setup_flow.py` (worker only). Leave empty to use the interactive list instead |
```

- [ ] **Step 6: Commit**

```bash
git add app/processing.py tests/test_processing.py README.md
git commit -m "$(cat <<'EOF'
Fall back to an interactive list when no flow id is set

Meta blocks Flow sends on accounts failing its integrity checks, so the
picker now delivers as an ordinary list message unless a flow id is
configured. That removes the "not ready yet" dead-end: there is always a
working path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Tapping a row re-adds the item

**Files:**
- Modify: `app/processing.py:114-131` (`_process_selection`)
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `_past_item_texts` (Task 2), `wa_msg.build_past_items_message` and `wa_msg.MAX_PAST_LISTED` (Task 1), the existing `handle_intent`, `_send_list`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processing.py`:

```python
def _readd_job(text, phone="972500000030", message_id="wamid.30"):
    return IncomingJob(
        kind="selection",
        phone=phone,
        name="Tester",
        message_id=message_id,
        callback_data=f"readd:{text}",
    )


def test_readd_adds_the_item_then_offers_the_rest(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    monkeypatch.setattr(
        processing.repo, "get_past_bought_items", lambda *a, **k: ["גבינה"]
    )
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _readd_job("חלב"))

    # Confirmation goes out plain, so the list that follows is the only
    # interactive message.
    assert "הוספתי" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] is None
    assert isinstance(fake_wa.sent[1]["buttons"], SectionList)

    user = repo.get_or_create_user(session, "972500000030", "Tester")
    lst = repo.get_active_list(session, user.family_id)
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"חלב"}


def test_readd_shows_the_shopping_list_when_history_is_exhausted(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    monkeypatch.setattr(processing.repo, "get_past_bought_items", lambda *a, **k: [])
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _readd_job("חלב"))

    assert "הוספתי" in fake_wa.sent[0]["text"]
    # The follow-up is the shopping list, not an empty picker.
    assert "הרשימה שלכם" in fake_wa.sent[1]["text"]


def test_unknown_selection_prefix_sends_nothing(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="selection",
        phone="972500000031",
        name="Tester",
        message_id="wamid.31",
        callback_data="bogus:1",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v -k "readd or unknown_selection"`
Expected: both `readd` tests FAIL with `IndexError: list index out of range` on `fake_wa.sent[0]` — `_process_selection` returns immediately for anything not starting with `buy:`, so nothing is sent. `test_unknown_selection_prefix_sends_nothing` already PASSES (that early return is the current behaviour); it is there to pin it once the branching is rewritten.

- [ ] **Step 3: Split the selection handler**

In `app/processing.py`, replace the whole of `_process_selection` with:

```python
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
        body, section_list = wa_msg.build_past_items_message(remaining)
        wa.send_message(to=job.phone, text=body, buttons=section_list)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS, including the pre-existing `buy:` tests (`test_stale_selection_gets_quick_buttons` and the ones covering a successful mark-bought), whose behaviour is unchanged by the split.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check app tests`
Expected: 9 findings, all pre-existing and in files this plan does not touch.

- [ ] **Step 6: Commit**

```bash
git add app/processing.py tests/test_processing.py
git commit -m "$(cat <<'EOF'
Add items back by tapping a row in the past-items list

A readd: tap routes through the existing add intent, then the picker
returns minus that item, so several can be added in a row. When the
history is exhausted the shopping list follows instead of an empty picker.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Manual verification (after all tasks)

On Railway, **clear** `WA_PAST_ITEMS_FLOW_ID` on the worker service and let it redeploy. Then in WhatsApp:

1. `תביא חלב וגבינה` → `קניתי הכל` → `נקה`
2. Tap **פריטים קודמים**. Expect the numbered body and a **הוסיפו לרשימה** button.
3. Open it, tap חלב. Expect `הוספתי: חלב ✅` then the picker again, now showing only גבינה.
4. Tap גבינה. Expect the confirmation, then the shopping list — the picker is exhausted.
5. Tap **פריטים קודמים** again. Expect `אין עדיין היסטוריה של קניות 🤷` — both items are back on the list, so neither is offered.
