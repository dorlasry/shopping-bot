# Past-Items Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user tap "פריטים קודמים", tick several previously-bought items in a WhatsApp Flow, and have them all added back to the shopping list.

**Architecture:** Purchase history is preserved by marking bought items `cleared` instead of deleting them. A repository query returns the most-recently-bought distinct item texts. The worker sends a **static** WhatsApp Flow (no endpoint, no RSA keys) whose checkbox options travel in `flow_action_payload` at send time. The user's selections arrive as a normal webhook update, get enqueued as a new `flow_completion` job, and are added through the existing `handle_intent(action="add")` path.

**Tech Stack:** Python 3.12, FastAPI, pywa 3.9, SQLAlchemy 2.0, pytest, ruff.

## Global Constraints

- **Static flow only.** No `data_api_version`, no `data_channel_uri`, no endpoint, no RSA keys, no `set_business_public_key`. All screen data is supplied at send time.
- **`WA_PAST_ITEMS_FLOW_ID` defaults to `""`.** When empty, the feature degrades to a friendly Hebrew message — never a crash. This mirrors how an unset `OPENAI_API_KEY` disables voice notes.
- **The flow stays in DRAFT** while testing: `FlowButton(mode=FlowStatus.DRAFT)`. Publishing is a later, deliberate step.
- **Past-items cap is 30** (`MAX_PAST_ITEMS`). Purchase history is unbounded over time, unlike a shopping list.
- **Checkbox `DataSource.id` is the item text itself**, so the values returned by the flow are the texts — no id→text mapping has to survive between messages.
- **Reply buttons are capped at 3 by WhatsApp.** After this change they are exactly: רשימה / פריטים קודמים / עזרה.
- Existing dedup convention: compare item text with `.strip().lower()`.
- Run tests with `.venv/bin/pytest`, lint with `.venv/bin/ruff check app tests`. The repo has 9 pre-existing ruff findings in files this plan does not touch; do not "fix" those, but introduce no new ones.

---

## File Structure

- **Modify** `app/domain/models.py` — add `Item.cleared`.
- **Modify** `app/db/repository.py` — `clear_bought` marks instead of deletes; add `get_past_bought_items`.
- **Create** `app/services/flows.py` — the static FlowJSON, the send-time payload builder, and the completion-response parser. Pure functions only; sends nothing (same contract as `app/services/whatsapp.py`).
- **Modify** `app/config.py` — add `wa_past_items_flow_id`.
- **Modify** `app/domain/schemas.py`, `app/services/parser.py`, `app/services/lists.py` — the `past_items` intent.
- **Modify** `app/services/whatsapp.py` — the third quick-reply button.
- **Modify** `app/queue/base.py`, `app/handlers/commands.py`, `app/handlers/interactions.py` — the `flow_completion` job kind and its producer.
- **Modify** `app/processing.py` — send the flow; process a completion.
- **Create** `scripts/setup_flow.py` — one-off flow creation.
- **Create** `tests/test_flows.py`; **modify** `tests/test_repository.py`, `tests/test_lists.py`, `tests/test_whatsapp.py`, `tests/test_processing.py`.

---

### Task 1: Preserve purchase history

**Files:**
- Modify: `app/domain/models.py:77-105` (the `Item` model)
- Modify: `app/db/repository.py:181-189` (`clear_bought`)
- Test: `tests/test_repository.py`

**Interfaces:**
- Produces: `Item.cleared: bool` (default `False`) and `clear_bought(session, list_id) -> int` which now marks rather than deletes. Task 2 relies on bought rows still existing after a clear.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repository.py`:

```python
def test_clear_bought_keeps_items_as_history(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב"])
    repo.mark_item_bought(session, created[0].id, user.id)

    repo.clear_bought(session, lst.id)

    # The row survives (it is purchase history now), but is marked cleared.
    item = repo.get_item(session, created[0].id)
    assert item is not None
    assert item.cleared is True


def test_clear_bought_is_idempotent(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב"])
    repo.mark_item_bought(session, created[0].id, user.id)

    assert repo.clear_bought(session, lst.id) == 1
    assert repo.clear_bought(session, lst.id) == 0
```

Also rename the existing `test_clear_bought_removes_only_bought` to `test_clear_bought_counts_only_bought` — it asserts the count and the remaining needed items, both still correct, but "removes" is no longer accurate.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_repository.py -v -k clear_bought`
Expected: `test_clear_bought_keeps_items_as_history` FAILS — `get_item` returns `None` because the row was deleted (and `Item` has no `cleared` attribute yet). `test_clear_bought_is_idempotent` FAILS on the second call returning 1, not 0.

- [ ] **Step 3: Add the `cleared` column**

In `app/domain/models.py`, inside `class Item`, directly after the `category` field:

```python
    # Reserved for the smart-categorization feature (e.g. "חלב" -> dairy).
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # True once "נקה" has cleared it off the active list. Bought items are kept
    # rather than deleted so they remain available as purchase history for the
    # past-items picker.
    cleared: Mapped[bool] = mapped_column(Boolean, default=False)
```

`Boolean` is already imported in this file.

- [ ] **Step 4: Make `clear_bought` mark instead of delete**

In `app/db/repository.py`, replace:

```python
def clear_bought(session: Session, list_id: int) -> int:
    """Delete all bought items from the list. Returns the count removed."""
    bought = session.scalars(
        select(Item).where(Item.list_id == list_id, Item.status == ItemStatus.BOUGHT)
    ).all()
    for item in bought:
        session.delete(item)
    session.flush()
    return len(bought)
```

with:

```python
def clear_bought(session: Session, list_id: int) -> int:
    """Mark bought items as cleared. Returns the count cleared.

    The rows are kept, not deleted, so past purchases stay available for the
    past-items picker. The `cleared` flag keeps this idempotent: a second call
    finds nothing left to clear, exactly as deleting used to.
    """
    bought = session.scalars(
        select(Item).where(
            Item.list_id == list_id,
            Item.status == ItemStatus.BOUGHT,
            Item.cleared.is_(False),
        )
    ).all()
    for item in bought:
        item.cleared = True
    session.flush()
    return len(bought)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_repository.py -v`
Expected: all PASS, including the renamed test.

- [ ] **Step 6: Commit**

```bash
git add app/domain/models.py app/db/repository.py tests/test_repository.py
git commit -m "$(cat <<'EOF'
Keep bought items as purchase history instead of deleting them

clear_bought now marks items cleared rather than deleting them, so past
purchases survive for the upcoming past-items picker. The returned count
and its idempotency are unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Query past bought items

**Files:**
- Modify: `app/db/repository.py` (imports + new function at the end of the Items section)
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `Item.cleared` from Task 1 (bought rows survive a clear).
- Produces: `get_past_bought_items(session, family_id, exclude_texts=(), limit=30) -> list[str]` — distinct item texts, most recently bought first. Tasks 5 and 7 call this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repository.py`:

```python
def _buy(session, user, lst, text, days_ago):
    """Add an item and mark it bought `days_ago` days ago."""
    from datetime import datetime, timedelta, timezone

    from app.domain.models import Item, ItemStatus

    item = Item(list_id=lst.id, text=text, added_by_id=user.id)
    item.status = ItemStatus.BOUGHT
    item.bought_by_id = user.id
    item.bought_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.add(item)
    session.flush()
    return item


def test_past_items_most_recent_first(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    _buy(session, user, lst, "גבינה", days_ago=5)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב", "גבינה"]


def test_past_items_deduplicates_by_text(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=9)
    _buy(session, user, lst, "גבינה", days_ago=5)
    _buy(session, user, lst, "חלב", days_ago=1)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב", "גבינה"]


def test_past_items_ignores_never_bought(session):
    user, lst = _setup(session)
    repo.add_items(session, lst.id, user.id, ["לחם"])
    _buy(session, user, lst, "חלב", days_ago=1)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב"]


def test_past_items_includes_cleared(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    repo.clear_bought(session, lst.id)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב"]


def test_past_items_excludes_given_texts(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    _buy(session, user, lst, "גבינה", days_ago=5)

    result = repo.get_past_bought_items(session, user.family_id, exclude_texts=[" ChLv ", "חלב"])
    assert result == ["גבינה"]


def test_past_items_respects_limit(session):
    user, lst = _setup(session)
    for day, text in enumerate(["א", "ב", "ג"], start=1):
        _buy(session, user, lst, text, days_ago=day)

    assert repo.get_past_bought_items(session, user.family_id, limit=2) == ["א", "ב"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_repository.py -v -k past_items`
Expected: all 6 FAIL with `AttributeError: module 'app.db.repository' has no attribute 'get_past_bought_items'`.

- [ ] **Step 3: Implement the query**

In `app/db/repository.py`, change the imports at the top:

```python
from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session
```

Then add at the end of the file:

```python
def get_past_bought_items(
    session: Session,
    family_id: int,
    exclude_texts: Iterable[str] = (),
    limit: int = 30,
) -> list[str]:
    """Distinct item texts the family has bought before, most recent first.

    Every item that ever reached BOUGHT counts, whether or not it was later
    cleared. Texts are de-duplicated case-insensitively (matching the dedup
    convention in `add_items`), keeping the spelling of the most recent
    purchase. `exclude_texts` is normally the currently-needed items, so the
    picker never offers something already on the list.
    """
    excluded = {t.strip().lower() for t in exclude_texts if t.strip()}

    # Rank each purchase within its item name, newest first, then keep rank 1 —
    # this gives one row per distinct name carrying its latest purchase date.
    rank = (
        func.row_number()
        .over(partition_by=func.lower(Item.text), order_by=Item.bought_at.desc())
        .label("rank")
    )
    latest = (
        select(Item.text, Item.bought_at, rank)
        .join(ShoppingList, ShoppingList.id == Item.list_id)
        .where(ShoppingList.family_id == family_id, Item.status == ItemStatus.BOUGHT)
        .subquery()
    )
    texts = session.execute(
        select(latest.c.text).where(latest.c.rank == 1).order_by(latest.c.bought_at.desc())
    ).scalars()

    result: list[str] = []
    for text in texts:
        if text.strip().lower() in excluded:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_repository.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db/repository.py tests/test_repository.py
git commit -m "$(cat <<'EOF'
Add get_past_bought_items query

Returns distinct item texts the family bought before, most recent first,
de-duplicated case-insensitively and excluding whatever is already on the
list.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The static flow definition

**Files:**
- Create: `app/services/flows.py`
- Create: `tests/test_flows.py`

**Interfaces:**
- Produces:
  - `SCREEN_ID = "PAST_ITEMS"`, `PICKED_FIELD = "picked"`, `ITEMS_KEY = "items"`, `MAX_PAST_ITEMS = 30`
  - `build_flow_json() -> FlowJSON` — used by `scripts/setup_flow.py` (Task 7)
  - `build_items_payload(texts: list[str]) -> dict` — the `flow_action_payload` for Task 5
  - `picked_items(response: dict | None) -> list[str]` — parses a completion for Task 6

- [ ] **Step 1: Write the failing tests**

Create `tests/test_flows.py`:

```python
"""Tests for the static past-items Flow definition and its payload helpers."""

from __future__ import annotations

import json

from app.services import flows


def test_build_items_payload_uses_text_as_id_and_title():
    assert flows.build_items_payload(["חלב", "גבינה"]) == {
        "items": [
            {"id": "חלב", "title": "חלב"},
            {"id": "גבינה", "title": "גבינה"},
        ]
    }


def test_build_items_payload_empty():
    assert flows.build_items_payload([]) == {"items": []}


def test_picked_items_from_list():
    assert flows.picked_items({"picked": ["חלב", "גבינה"]}) == ["חלב", "גבינה"]


def test_picked_items_from_json_string():
    # WhatsApp may deliver the array JSON-encoded.
    assert flows.picked_items({"picked": json.dumps(["חלב"])}) == ["חלב"]


def test_picked_items_when_nothing_selected():
    assert flows.picked_items({"picked": []}) == []
    assert flows.picked_items({}) == []
    assert flows.picked_items(None) == []


def test_flow_json_is_static_and_wires_the_checkbox():
    data = json.loads(flows.build_flow_json().to_json())

    # A static flow declares no endpoint.
    assert "data_api_version" not in data
    assert "data_channel_uri" not in data

    screen = data["screens"][0]
    assert screen["id"] == "PAST_ITEMS"
    assert screen["terminal"] is True
    assert "items" in screen["data"]

    form = screen["layout"]["children"][0]
    checkbox, footer = form["children"]
    assert checkbox["type"] == "CheckboxGroup"
    assert checkbox["data-source"] == "${data.items}"
    assert footer["on-click-action"]["name"] == "complete"
    assert footer["on-click-action"]["payload"] == {"picked": "${form.picked}"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_flows.py -v`
Expected: collection FAILS with `ModuleNotFoundError: No module named 'app.services.flows'`.

- [ ] **Step 3: Write the module**

Create `app/services/flows.py`:

```python
"""The past-items WhatsApp Flow (static) and its payload helpers.

This is a *static* flow: it declares no endpoint and no data API version, so
Meta never calls us and no encryption keys are involved. Every value the screen
shows is supplied when the message is sent, via `flow_action_payload`, and the
user's ticks come back in the flow-completion message.

Pure builders only — nothing here sends anything, matching `whatsapp.py`.
"""

from __future__ import annotations

import json

from pywa import utils
from pywa.types.flows import (
    CheckboxGroup,
    CompleteAction,
    DataSource,
    FlowJSON,
    Footer,
    Form,
    Layout,
    Screen,
    ScreenData,
)

SCREEN_ID = "PAST_ITEMS"
ITEMS_KEY = "items"
PICKED_FIELD = "picked"
FORM_NAME = "past_items_form"

# Purchase history is unbounded over time (a shopping list is not), so the
# picker is capped to keep the message payload small.
MAX_PAST_ITEMS = 30

SCREEN_TITLE = "פריטים קודמים"
CHECKBOX_LABEL = "מה להוסיף לרשימה?"
SUBMIT_LABEL = "הוסף לרשימה"


def build_flow_json() -> FlowJSON:
    """The one-screen flow: tick past items, submit, done."""
    items = ScreenData(key=ITEMS_KEY, example=[DataSource(id="חלב", title="חלב")])
    picked = CheckboxGroup(
        name=PICKED_FIELD,
        data_source=items.ref,
        label=CHECKBOX_LABEL,
        required=True,
    )
    return FlowJSON(
        version=utils.Version.FLOW_JSON,
        screens=[
            Screen(
                id=SCREEN_ID,
                title=SCREEN_TITLE,
                terminal=True,
                data=[items],
                layout=Layout(
                    children=[
                        Form(
                            name=FORM_NAME,
                            children=[
                                picked,
                                Footer(
                                    label=SUBMIT_LABEL,
                                    on_click_action=CompleteAction(
                                        payload={PICKED_FIELD: picked.ref}
                                    ),
                                ),
                            ],
                        )
                    ]
                ),
            )
        ],
    )


def build_items_payload(texts: list[str]) -> dict:
    """The `flow_action_payload` that fills the checkbox at send time.

    The item text doubles as the option id, so the values the flow returns are
    the texts themselves — nothing has to be remembered between messages.
    """
    return {ITEMS_KEY: [{"id": text, "title": text} for text in texts]}


def picked_items(response: dict | None) -> list[str]:
    """The item texts the user ticked, from a flow-completion response."""
    if not response:
        return []
    picked = response.get(PICKED_FIELD)
    if isinstance(picked, str):
        try:
            picked = json.loads(picked)
        except ValueError:
            picked = [picked]
    if not isinstance(picked, list):
        return []
    return [str(p).strip() for p in picked if str(p).strip()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_flows.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/flows.py tests/test_flows.py
git commit -m "$(cat <<'EOF'
Add the static past-items Flow definition and payload helpers

One terminal screen with a CheckboxGroup bound to send-time screen data,
so no endpoint or encryption keys are needed. Item text doubles as the
option id, so completions return the texts directly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The `past_items` intent and trigger button

**Files:**
- Modify: `app/config.py` (new setting)
- Modify: `app/domain/schemas.py:13-15` (the `Action` literal)
- Modify: `app/services/parser.py:35-49` (the prompt's action list)
- Modify: `app/services/lists.py` (`HELP_TEXT`, `ActionResult`, `handle_intent`)
- Modify: `app/services/whatsapp.py:58-64` (`quick_command_buttons`)
- Test: `tests/test_lists.py`, `tests/test_whatsapp.py`

**Interfaces:**
- Produces: `ActionResult.show_past_items: bool = False`; the `"past_items"` action; `settings.wa_past_items_flow_id`; a third quick-reply button with `callback_data="cmd:past_items"`. Task 5 consumes all of these.

- [ ] **Step 1: Write the failing tests**

In `tests/test_whatsapp.py`, replace `test_quick_command_buttons_has_list_and_help_only` with:

```python
def test_quick_command_buttons():
    assert quick_command_buttons() == [
        Button(title="רשימה", callback_data="cmd:list"),
        Button(title="פריטים קודמים", callback_data="cmd:past_items"),
        Button(title="עזרה", callback_data="cmd:help"),
    ]
```

Append to `tests/test_lists.py`:

```python
def test_past_items_intent(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="past_items"))
    assert res.show_past_items is True
    assert res.show_list is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_whatsapp.py tests/test_lists.py -v -k "quick_command_buttons or past_items"`
Expected: `test_quick_command_buttons` FAILS (only two buttons returned). `test_past_items_intent` FAILS with `AttributeError: 'ActionResult' object has no attribute 'show_past_items'`.

- [ ] **Step 3: Add the config setting**

In `app/config.py`, after the `queue_key` line:

```python
    queue_key: str = "shopping:incoming"

    # WhatsApp Flow for the past-items picker. Empty disables the feature
    # (the bot replies that it isn't ready yet) — set it to the flow id
    # printed by scripts/setup_flow.py.
    wa_past_items_flow_id: str = ""
```

- [ ] **Step 4: Add the action to the schema**

In `app/domain/schemas.py`, replace the `Action` literal:

```python
Action = Literal[
    "add",
    "remove",
    "bought",
    "bought_all",
    "view",
    "clear",
    "past_items",
    "greeting",
    "help",
    "unknown",
]
```

- [ ] **Step 5: Teach the parser the new action**

In `app/services/parser.py`, insert this entry into the system prompt's action list, directly after the `"clear"` line:

```python
- "clear": user wants to clear/empty the bought items or list (e.g. "נקה", "תרוקן")
- "past_items": user wants to see things they bought in the PAST so they can add \
some again (e.g. "פריטים קודמים", "מה קניתי בעבר", "היסטוריה", "תראה לי מה קניתי פעם"). items must be empty.
```

No other parser change is needed: the defensive `if intent.action not in ("add", "remove", "bought")` line already clears `items` for this action.

- [ ] **Step 6: Handle the intent**

In `app/services/lists.py`, extend `HELP_TEXT`:

```python
HELP_TEXT = (
    "אני בוט רשימת קניות 🛒\n"
    "• כתבו לי מה להביא: “תביא חלב וגבינה”\n"
    "• סימון שנקנה: “קניתי חלב וגבינה” (או “קניתי הכל”) ✓\n"
    "• להסרה: “תוריד את הביצים”\n"
    "• לצפייה: “רשימה” או “מה יש”\n"
    "• לניקוי שנקנה: “נקה”\n"
    "• פריטים שקניתם בעבר: “פריטים קודמים”"
)
```

Extend `ActionResult`:

```python
@dataclass
class ActionResult:
    """What the handler should do after business logic runs."""

    reply_text: str
    # When True, the handler should ALSO send the interactive list message so the
    # user can tap items to mark them bought.
    show_list: bool = False
    # When True, the handler should send the past-items Flow instead.
    show_past_items: bool = False
```

Add a case to `handle_intent`, directly after the `case "clear":` block:

```python
        case "past_items":
            return ActionResult("", show_past_items=True)
```

- [ ] **Step 7: Add the button**

In `app/services/whatsapp.py`, replace `quick_command_buttons`:

```python
def quick_command_buttons() -> list[Button]:
    """Reply buttons for the common actions (WhatsApp allows at most 3)."""
    return [
        Button(title="רשימה", callback_data="cmd:list"),
        Button(title="פריטים קודמים", callback_data="cmd:past_items"),
        Button(title="עזרה", callback_data="cmd:help"),
    ]
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS. Note `tests/test_processing.py` compares against `wa_msg.quick_command_buttons()` dynamically, so the third button does not break it.

- [ ] **Step 9: Commit**

```bash
git add app/config.py app/domain/schemas.py app/services/parser.py app/services/lists.py app/services/whatsapp.py tests/test_lists.py tests/test_whatsapp.py
git commit -m "$(cat <<'EOF'
Add the past_items intent and its quick-reply button

Recognised from text and voice through the parser, and available as the
third reply button (רשימה / פריטים קודמים / עזרה).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Send the flow from the worker

**Files:**
- Modify: `app/processing.py` (imports, `_handle_text`, `_process_button`, new helper)
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `settings.wa_past_items_flow_id`, `ActionResult.show_past_items`, `cmd:past_items` (Task 4); `repo.get_past_bought_items` (Task 2); `flows.build_items_payload`, `flows.SCREEN_ID`, `flows.MAX_PAST_ITEMS` (Task 3).
- Produces: `_send_past_items(wa, phone, session, user)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processing.py` (add `from pywa.types import FlowButton` to the imports at the top):

```python
def _past_items_job(phone="972500000020", message_id="wamid.20"):
    return IncomingJob(
        kind="button",
        phone=phone,
        name="Tester",
        message_id=message_id,
        callback_data="cmd:past_items",
    )


def test_past_items_button_sends_flow(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "12345")
    monkeypatch.setattr(
        processing.repo, "get_past_bought_items", lambda *a, **k: ["חלב", "גבינה"]
    )
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    button = fake_wa.sent[0]["buttons"]
    assert isinstance(button, FlowButton)
    assert button.flow_id == "12345"
    assert button.flow_action_payload == {
        "items": [{"id": "חלב", "title": "חלב"}, {"id": "גבינה", "title": "גבינה"}]
    }


def test_past_items_button_without_history(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "12345")
    monkeypatch.setattr(processing.repo, "get_past_bought_items", lambda *a, **k: [])
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    assert "היסטוריה" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()


def test_past_items_button_when_flow_not_configured(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v -k past_items`
Expected: all three FAIL. `cmd:past_items` currently hits the `else` branch of `_process_button`, which only logs, so nothing is sent and `len(fake_wa.sent) == 1` fails with `0 != 1`.

- [ ] **Step 3: Implement sending**

In `app/processing.py`, add to the imports:

```python
from pywa.types import FlowButton
from pywa.types.flows import FlowActionType, FlowStatus

from app.services import flows as flow_msg
```

Add the `show_past_items` branch in `_handle_text`, replacing its final two lines:

```python
        if result.show_list:
            _send_list(wa, phone, session, user)
        if result.show_past_items:
            _send_past_items(wa, phone, session, user)
```

Add the `cmd:past_items` branch in `_process_button`, directly after the `cmd:list` branch:

```python
        elif data == "cmd:past_items":
            _send_past_items(wa, job.phone, session, user)
```

Add the helper next to `_send_list`:

```python
def _send_past_items(wa: WhatsApp, phone: str, session: Session, user: User) -> None:
    """Send the past-items Flow, pre-filled with what the family bought before.

    The flow is static: its options travel with this message, so there is no
    endpoint for Meta to call back into.
    """
    if not settings.wa_past_items_flow_id:
        _send_final(wa, phone, "הפיצ'ר הזה עדיין לא מוכן 🙏")
        return

    active_list = repo.get_active_list(session, user.family_id)
    needed = {item.text for item in repo.get_needed_items(session, active_list.id)}
    past = repo.get_past_bought_items(
        session,
        user.family_id,
        exclude_texts=needed,
        limit=flow_msg.MAX_PAST_ITEMS,
    )
    if not past:
        _send_final(wa, phone, "אין עדיין היסטוריה של קניות 🤷 קנו משהו קודם.")
        return

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_processing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/processing.py tests/test_processing.py
git commit -m "$(cat <<'EOF'
Send the past-items Flow from the worker

Queries the family's past purchases (minus what is already on the list)
and ships them as the flow's screen data. Degrades to a friendly message
when there is no history or no flow id configured.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Receive the completion and add the picked items

**Files:**
- Modify: `app/queue/base.py:15-31` (`JobKind` + `IncomingJob`)
- Modify: `app/handlers/commands.py` (new producer helper)
- Modify: `app/handlers/interactions.py` (register the completion handler)
- Modify: `app/processing.py` (dispatch + handler)
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `flows.picked_items` (Task 3), `handle_intent` with `action="add"`.
- Produces: `IncomingJob(kind="flow_completion", picked=[...])`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processing.py`:

```python
def _completion_job(picked, phone="972500000021", message_id="wamid.21"):
    return IncomingJob(
        kind="flow_completion",
        phone=phone,
        name="Tester",
        message_id=message_id,
        picked=picked,
    )


def test_flow_completion_adds_picked_items(session):
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _completion_job(["חלב", "גבינה"]))

    assert "הוספתי" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] is None  # the list message follows
    assert isinstance(fake_wa.sent[1]["buttons"], SectionList)

    user = repo.get_or_create_user(session, "972500000021", "Tester")
    lst = repo.get_active_list(session, user.family_id)
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"חלב", "גבינה"}


def test_flow_completion_with_nothing_picked(session):
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _completion_job([]))

    assert len(fake_wa.sent) == 1
    assert "לא נבחרו" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()
```

These tests need the repository. Add this to the imports at the top of `tests/test_processing.py` (it imports `SectionList` and `wa_msg` already, but not `repo`):

```python
from app.db import repository as repo
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_processing.py -v -k flow_completion`
Expected: both FAIL with `TypeError: IncomingJob.__init__() got an unexpected keyword argument 'picked'`.

- [ ] **Step 3: Add the job kind**

In `app/queue/base.py`:

```python
JobKind = Literal["message", "selection", "button", "audio", "flow_completion"]


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
    # Present for kind == "flow_completion": the item texts the user ticked.
    picked: list[str] | None = None
```

`to_json`/`from_json` need no change — `asdict` and `json` handle a list of strings.

- [ ] **Step 4: Add the producer**

In `app/handlers/commands.py`:

```python
def enqueue_flow_completion(queue: MessageQueue, completion, picked: list[str]) -> None:
    """Enqueue the items a user ticked in the past-items flow."""
    queue.enqueue(
        IncomingJob(
            kind="flow_completion",
            phone=completion.from_user.wa_id,
            name=completion.from_user.name or "",
            message_id=completion.id,
            picked=picked,
        )
    )
```

In `app/handlers/interactions.py`, add the import and the handler:

```python
from app.handlers.commands import enqueue_callback, enqueue_flow_completion
from app.services import flows as flow_msg
```

```python
    @wa.on_flow_completion
    def on_past_items_flow(_: WhatsApp, completion: FlowCompletion) -> None:
        picked = flow_msg.picked_items(completion.response)
        logger.info(
            "enqueue flow completion from %s: %d item(s)",
            completion.from_user.wa_id,
            len(picked),
        )
        enqueue_flow_completion(queue, completion, picked)
```

with `FlowCompletion` added to the `pywa.types` import at the top of that file.

- [ ] **Step 5: Process the job**

In `app/processing.py`, add the dispatch branch in `process_job`, after the `button` branch:

```python
    elif job.kind == "flow_completion":
        _process_flow_completion(wa, job)
```

and the handler after `_process_button`:

```python
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
        if result.reply_text:
            if result.show_list:
                wa.send_message(to=job.phone, text=result.reply_text)
            else:
                _send_final(wa, job.phone, result.reply_text)
        if result.show_list:
            _send_list(wa, job.phone, session, user)
```

Add `from app.domain.schemas import ParsedIntent` to the imports.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS.

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check app tests`
Expected: no findings in the files this task touched (9 pre-existing findings elsewhere are fine).

- [ ] **Step 8: Commit**

```bash
git add app/queue/base.py app/handlers/commands.py app/handlers/interactions.py app/processing.py tests/test_processing.py
git commit -m "$(cat <<'EOF'
Add picked items from the past-items flow back to the list

Flow completions are enqueued as a new job kind and processed through the
existing add intent, so they reuse its confirmation, duplicate guard, and
list refresh.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Setup script and documentation

**Files:**
- Create: `scripts/setup_flow.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `flows.build_flow_json()` (Task 3).

- [ ] **Step 1: Write the script**

Create `scripts/setup_flow.py`:

```python
"""One-off: create (or update) the past-items Flow in your WhatsApp account.

Run once, then put the printed flow id in WA_PAST_ITEMS_FLOW_ID.

    python scripts/setup_flow.py                # create a new draft flow
    python scripts/setup_flow.py --update FLOW  # push the JSON to an existing flow

The flow is created as a DRAFT so it can be edited freely; publishing is a
separate, deliberate step once you are happy with it.
"""

from __future__ import annotations

import argparse

from pywa import WhatsApp

from app.config import settings
from app.services.flows import build_flow_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", metavar="FLOW_ID", help="update an existing flow")
    args = parser.parse_args()

    wa = WhatsApp(phone_id=settings.wa_phone_id, token=settings.wa_token)
    flow_json = build_flow_json()

    if args.update:
        result = wa.update_flow_json(flow_id=args.update, flow_json=flow_json)
        print(f"updated flow {args.update}: {result}")
        return

    created = wa.create_flow(
        name="past-items",
        categories=["OTHER"],
        flow_json=flow_json,
    )
    print(f"created flow: {created.id}")
    print(f"set WA_PAST_ITEMS_FLOW_ID={created.id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script builds valid JSON without calling Meta**

Run: `.venv/bin/python -c "from app.services.flows import build_flow_json; print(build_flow_json().to_json()[:200])"`
Expected: prints the start of the flow JSON, beginning `{"version": "7.3", "screens": [...`. This exercises everything the script does except the network calls.

- [ ] **Step 3: Document setup in the README**

Add this section to `README.md`, after the "Commands the bot understands" table:

```markdown
## Past-items picker (WhatsApp Flow)

Tapping **פריטים קודמים** opens a multi-select of things the family bought
before; ticking several adds them all back at once.

It uses a *static* WhatsApp Flow: the options are sent with the message, so
there is no callback endpoint and no encryption keys to manage.

### One-time setup

1. **Migrate the database.** Bought items are now kept as history instead of
   being deleted, which needs a new column. `init_db()` only creates missing
   tables, so run this once against your production Postgres:

   ```sql
   ALTER TABLE items ADD COLUMN cleared BOOLEAN NOT NULL DEFAULT FALSE;
   ```

   Fresh databases (and the test suite) get the column automatically.

2. **Create the flow** and note the id it prints:

   ```bash
   python scripts/setup_flow.py
   ```

3. **Set `WA_PAST_ITEMS_FLOW_ID`** to that id on the worker service. Until it is
   set, the button replies that the feature isn't ready yet.

The flow is created as a draft and sent with `mode=draft`, so only people with a
role on your Meta app can open it — which is what you want while testing.
```

Also add `WA_PAST_ITEMS_FLOW_ID` to the Railway environment-variable table in the README, described as "flow id from `scripts/setup_flow.py` (worker only)".

- [ ] **Step 4: Commit**

```bash
git add scripts/setup_flow.py README.md
git commit -m "$(cat <<'EOF'
Add the past-items flow setup script and docs

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Manual verification (after all tasks)

Automated tests cannot exercise Meta's rendering of the flow. Do this once:

1. Run the migration SQL against production Postgres.
2. `python scripts/setup_flow.py`, then set `WA_PAST_ITEMS_FLOW_ID` on the worker service and let it redeploy.
3. In WhatsApp: add a couple of items, mark them bought, then send `נקה`.
4. Tap **פריטים קודמים**. Expect a message with a "בחרו פריטים" button.
5. Tap it. **Check the three known risks here:**
   - the screen opens at all (draft-mode recipients — your number has a role on the app, so it should),
   - the Hebrew labels render right-to-left correctly,
   - all the items appear (if a long history is truncated, lower `MAX_PAST_ITEMS` in `app/services/flows.py`).
6. Tick two items and submit. Expect "הוספתי: ..." followed by the refreshed list.
7. Tap the button again — the two you just added should no longer be offered.
