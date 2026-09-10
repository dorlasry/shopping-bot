# Past-items picker: interactive-list fallback

Date: 2026-09-10

## Why

The past-items picker shipped as a WhatsApp Flow. Meta refuses to send it:

```
FlowBlockedByIntegrity — (#139000) Blocked by Integrity
"Integrity requirements not met."
```

This is an account-level gate, not a payload problem — Meta *created* the flow
(`1636524131437922`, DRAFT, no validation errors) and blocks only the send. It
is a common outcome for a free test number on an unverified business. No change
to the flow JSON, the payload, or the button can lift it; clearing it means
Meta Business Verification and a real phone number, on Meta's timeline.

So the feature needs a delivery mechanism that works on this account today. The
bot already has one: the interactive list message (`SectionList`) behind
`סמן שנקנה`, which sends fine.

## What changes, and what doesn't

Everything except the message itself is already built, tested and deployed:

- `Item.cleared` and the retained purchase history
- `get_past_bought_items(...)` — the ranked, de-duplicated, exclusion-aware query
- the `past_items` intent (text and voice) and the `פריטים קודמים` quick button
- `_send_past_items`'s query logic — which items to offer

Only the delivery changes: an interactive list instead of a `FlowButton`, and a
new callback branch to handle a tap.

**The Flow code stays.** It is correct, tested, and blocked only by the account.
It becomes reachable again the day verification clears.

## The switch

`WA_PAST_ITEMS_FLOW_ID` becomes the selector:

- **set** → send the Flow (current behaviour)
- **empty** → send the interactive list (new)

Since the list needs no configuration, this also **removes the "הפיצ'ר הזה עדיין
לא מוכן" dead-end entirely** — there is always a working path. That message and
its branch are deleted.

No new setting. On Railway the flow id simply gets cleared until Meta relents.

## The list message

A new `build_past_items_message(texts) -> tuple[str, SectionList | None]` in
`app/services/whatsapp.py`, mirroring the existing `build_list_message`:

- Body lists every offered item, numbered, so the whole set is readable even
  beyond the tappable rows.
- The first `MAX_ROWS` (10) become tappable `SectionRow`s; row titles are
  truncated with the existing `truncate(text, 24)`.
- Anything past 10 stays in the body text with a note that typing the name adds
  it — the same accommodation `build_list_message` already makes.
- Empty input returns `(message, None)` so the caller sends plain text.

The query keeps its existing `MAX_PAST_ITEMS` limit of 20, so a long history
shows 20 items with the first 10 tappable.

`callback_data` is `readd:<item text>`. The text, not an id: it routes straight
into the existing `add` intent with no second lookup, and `get_past_bought_items`
keeps its current signature and its tests. The cost is a length ceiling —
WhatsApp caps a row id at 200 characters — so `build_past_items_message` skips
any item whose callback would exceed it. `Item.text` is `String(200)`, so this
is reachable only by a pathological name; skipped items still appear in the body
text and can be added by typing.

## Tapping a row

`_process_selection` currently handles only `buy:`. It gains a `readd:` branch:

1. Extract the text after the first `:` (splitting once, so a colon inside an
   item name is harmless — the same parse `buy:` already uses).
2. Route through the existing add path:
   `handle_intent(session, user, ParsedIntent(action="add", items=[text]))`.
   That reuses the current confirmation copy, the duplicate guard, and all of
   the add semantics — no new business logic.
3. Send the confirmation as plain text, then **re-show the picker**, so the next
   item is one tap away. This is the sequential multi-select: tap, list
   reappears, tap again.

The just-added item drops out of the refreshed picker on its own — it is now
`NEEDED`, and the query already excludes currently-needed items. No bookkeeping.

**When the picker empties**, showing an empty picker would be a dead end, so the
follow-up becomes the current shopping list instead — which is what someone who
has just finished adding wants to see anyway.

## Message shapes

| Situation | Reply |
|---|---|
| Picker requested, history exists | body + tappable list |
| Picker requested, no history | existing `אין עדיין היסטוריה…` text, with quick buttons |
| Row tapped, items remain | `הוספתי: X ✅` then the refreshed picker |
| Row tapped, none remain | `הוספתי: X ✅` then the shopping list |
| Row tapped, already on the list | the existing duplicate reply from `add`, then the refreshed picker |

One interactive component per message throughout, matching the existing
convention: the confirmation goes out plain, the list follows.

## Testing

Extends the existing suites; no new infrastructure:

- `build_past_items_message`: numbering, the 10-row tappable cut with the
  remainder in body text, truncation of long row titles, the over-long callback
  skip, and the empty case.
- `_process_selection` with `readd:`: the item is really added to the database,
  the confirmation goes out plain, and the picker follows.
- The exhausted-picker case: the shopping list follows instead of an empty picker.
- The selector: flow id set → `FlowButton`; empty → `SectionList`.

The `FlowButton` tests stay as they are — that path is unchanged.

## Out of scope

Business verification (a Meta process, not code), publishing the flow, deleting
the created flow, and the deferred conversion of `סמן שנקנה` to multi-select —
which this discovery pushes further out, since that too would be blocked.
