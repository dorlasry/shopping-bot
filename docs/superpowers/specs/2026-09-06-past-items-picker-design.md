# Past-items picker: multi-select re-add via a static WhatsApp Flow

Date: 2026-09-06

## Goal

Let a user see items the family has bought before, tick several of them at
once, and have them added back to the current list.

## Why a Flow, and why a *static* one

WhatsApp interactive list messages — what the bot already uses for the buy-list
— are single-select: one tap fires and closes the sheet. The only WhatsApp
component supporting true multi-select is a **Flow** (`CheckboxGroup`).

Flows come in two kinds:

- **Dynamic**: the server answers screen actions over an encrypted data-exchange
  endpoint. Needs an RSA key pair, the public key registered with Meta, and a
  public HTTPS endpoint.
- **Static**: every screen value is supplied *when the message is sent*, the
  user fills it in on-device, and the answers arrive in the completion message.
  **No endpoint, no keys, no encryption setup.**

The past items are already known at send time — the worker queries them from the
database before sending — so a **static flow** is sufficient. An earlier draft of
this design assumed a dynamic flow and split the work into a separate
infrastructure project; that split is dropped, because none of that
infrastructure is needed.

Meta's docs confirm the mechanism: when the first screen's parameters "are known
when the message is sent", they can be supplied via the
`flow_action_payload.data` message field. pywa exposes this as
`Screen(data=[ScreenData(...)])` + `.ref`, populated through
`FlowButton(flow_action_payload=...)`.

## Data model

Bought items do not survive today: `clear_bought` (the "נקה" action) deletes
them outright. To keep history:

- Add `Item.cleared: bool` (default `False`).
- `clear_bought` sets `cleared=True` on items that are `BOUGHT` and not yet
  cleared, instead of deleting them. It returns the same count, so the
  "ניקיתי N פריטים שנקנו" confirmation and its idempotency are unchanged.
- `get_needed_items` is untouched — it already filters on `status == NEEDED`.

`remove_items_by_text` keeps deleting: items removed without ever being bought
are not history.

**This requires a one-time manual migration**, because the project has no
migration tooling (`init_db()` only creates tables that do not already exist):

```sql
ALTER TABLE items ADD COLUMN cleared BOOLEAN NOT NULL DEFAULT FALSE;
```

The user runs this against production Postgres themselves. Fresh databases and
the test suite get the column automatically from `create_all()`.

## History query

New repository function:

```
get_past_bought_items(session, family_id, exclude_texts, limit=30) -> list[str]
```

- Scoped to the family (join `ShoppingList`), not a single list, so history
  survives future multi-list changes.
- Considers every item that ever reached `BOUGHT`, whether or not it was later
  cleared.
- De-duplicates case-insensitively (`lower(text)`), matching the existing dedup
  convention in `add_items`, and returns the exact text of the most recent
  purchase for each distinct item.
- Ordered most-recently-bought first.
- Excludes anything whose lowercased text is in `exclude_texts` — the caller
  passes the currently-needed items, so the picker never offers something
  already on the list.
- Capped at `limit` (30). Purchase history is unbounded over time, unlike a
  shopping list; 30 keeps the message payload small.

Implemented with a `row_number()` window function partitioned by
`lower(Item.text)` ordered by `bought_at desc`, then filtering to rank 1. This
works on both SQLite (tests) and Postgres (production).

## The Flow

Defined in a new `app/services/flows.py`, alongside the existing pure builders:

- One screen, `PAST_ITEMS`, declaring `ScreenData(key="items", example=[...])`.
- A `Form` containing a `CheckboxGroup(name="picked", data_source=<items ref>)`.
- A `Footer` whose `on_click_action` is a `CompleteAction` returning the picked
  values.

The screen is created once via a one-off `scripts/setup_flow.py` (matching the
existing `scripts/` pattern), which calls `wa.create_flow(...)` and prints the
flow id for the user to set as `WA_PAST_ITEMS_FLOW_ID`. The flow stays in
**draft** while testing (`FlowButton(mode=FlowStatus.DRAFT)`); publishing is a
later, deliberate step.

## Trigger and round trip

1. Quick-reply buttons return to three (WhatsApp's max):
   רשימה / **פריטים קודמים** / עזרה. The parser also gains a `past_items`
   action so text and voice work too, consistent with every other command.
2. The worker handles it: query needed items → query past items excluding them →
   send a message whose `buttons=` is a `FlowButton` carrying
   `flow_action_payload={"items": [{"id": ..., "title": ...}, ...]}`.
3. The user ticks items and submits.
4. The completion arrives at the **web** service as a normal webhook update.
   Following the existing producer/worker split, the handler enqueues a job
   (new `IncomingJob` kind `flow_completion`, carrying the picked texts) and
   returns immediately.
5. The worker processes that job through the **existing** `add` path —
   `handle_intent(session, user, ParsedIntent(action="add", items=picked))` —
   so it reuses the current confirmation text, the duplicate guard, and the
   follow-up list display with no new business logic.

## Empty and unconfigured states

- No purchase history yet → friendly Hebrew text, with the quick-reply buttons
  attached (the existing dead-end pattern).
- `WA_PAST_ITEMS_FLOW_ID` unset → friendly "not ready yet" message rather than
  a crash, mirroring how an unset `OPENAI_API_KEY` disables voice notes.
- Nothing ticked → the completion carries no items; reply accordingly instead
  of calling `add_items` with an empty list.

## Configuration

One new optional setting in `app/config.py`: `wa_past_items_flow_id: str = ""`.
No keys, no endpoint URL. Only the worker needs it (it sends the trigger); the
web service needs no new configuration at all.

## Testing

Unit tests, no network, following the existing conventions:

- `get_past_bought_items`: dedup by case, recency ordering, exclusion of
  currently-needed items, the limit, and that cleared items still count as
  history — against the in-memory SQLite `session` fixture.
- `clear_bought`: marks instead of deletes, returns the same count, and a
  second call returns 0.
- The flow-payload builder: turns a list of item texts into the
  `flow_action_payload` structure.
- The trigger handler and the completion handler in `app/processing.py`, using
  the existing `FakeWhatsApp` double: flow button sent when configured, the
  fallback text when not, empty-history message, and that a completion job adds
  the picked items and shows the list.

The Flow rendering itself cannot be unit tested — that is manual verification in
a real chat, as with the bot's other outward-facing behavior.

## Risks to check during implementation

- **`flow_action_payload` size limit.** Meta caps message payloads; 30 short
  Hebrew item names should be well inside it, but the exact limit should be
  confirmed and the cap lowered if needed.
- **Draft-mode recipients.** Draft flows may only be openable by people with a
  role on the Meta app. The user's own number is already a test recipient, so
  this is expected to be fine, but it is unverified and should be confirmed at
  first manual test rather than assumed.
- **RTL rendering.** Hebrew labels inside Flow screens have not been exercised
  in this project; check the first render looks right.

## Out of scope

Dynamic flows (endpoint + RSA keys), publishing the flow to non-test users,
categories or frequency-based ranking, and any change to how items are removed.
