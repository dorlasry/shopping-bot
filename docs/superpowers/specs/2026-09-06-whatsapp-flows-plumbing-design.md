# WhatsApp Flows plumbing: static past-items picker

Date: 2026-09-06

## Context

The user asked for a way to see previously-bought items and pick them again.
The natural WhatsApp UI for "pick several things at once" is a **Flow** — Meta's
multi-screen form system, the only WhatsApp component that supports true
multi-select (`CheckboxGroup`). Interactive list messages, which this bot
already uses for the buy-list, are single-select by design: one tap fires and
closes the sheet.

Flows are a separate subsystem from the past-items feature itself: they need an
RSA key pair, a public key registered with Meta, a Flow definition created and
published, and a public HTTPS endpoint that receives **encrypted** data-exchange
requests. None of that is specific to past items, and all of it is unfamiliar
territory for this codebase.

So the work is split into two projects:

1. **This spec** — prove the entire Flow pipeline works end to end, using a
   screen with hardcoded placeholder items. No real data, no real list changes.
2. **Next project** — replace the placeholder data with a real
   most-recently-bought query and wire submission into the existing `add`
   logic. That project also owns the data-model work (bought items are
   currently deleted by `clear_bought`, so history does not survive today).

Building the real screen shape in step 1 — rather than a throwaway "hello
world" — means step 2 changes the data source and the submit handler, not the
plumbing.

## Why this is thin in Python

pywa (already a dependency) wraps the whole Flows lifecycle:

- `WhatsApp.set_business_public_key()` — registers the public key with Meta.
- `WhatsApp.create_flow()` / `update_flow_json()` / `publish_flow()` — create
  and publish a Flow from a `FlowJSON` object, no dashboard JSON editing.
- `@WhatsApp.on_flow_request(endpoint)` — registers the encrypted
  data-exchange endpoint on the existing FastAPI app; pywa handles
  decryption/encryption given the private key.
- `@WhatsApp.on_flow_completion` — fires when the user submits the Flow.
- `pywa.types.flows` provides `FlowJSON`, `Screen`, `Layout`, `Form`,
  `CheckboxGroup`, `DataSource`, `Footer`, `CompleteAction`, `FlowButton`.

There is therefore no encryption code, no Graph API calls, and no Flow JSON
authored by hand in this project. The app-level surface is: config, one screen
definition, one request handler, one completion handler, one trigger, and a
one-off setup script.

## Design

### Configuration (`app/config.py`)

Three new settings, all defaulting to empty so existing local dev, tests, and
the current production deployment keep working untouched:

- `wa_flow_private_key: str = ""`
- `wa_flow_private_key_password: str = ""`
- `wa_past_items_flow_id: str = ""`

This mirrors the existing optional-feature pattern (`openai_api_key` empty
disables voice notes via `transcription.is_enabled()`).

### Keys (user-run, not automated)

The user generates the RSA key pair themselves and sets the private key as a
Railway variable, exactly as `WA_APP_SECRET` and the other credentials are
handled today. The implementation plan will carry the exact `openssl` commands;
the assistant does not generate, hold, or paste key material.

The **public** key is registered with Meta once via
`wa.set_business_public_key(...)` from the setup script below.

### Setup script (`scripts/setup_flow.py`)

A one-off script, matching the existing `scripts/` pattern (`try_parser.py`,
`simulate_webhook.py`). It:

1. Reads the public key PEM from a path given as a CLI argument.
2. Calls `wa.set_business_public_key(pem)`.
3. Builds the `FlowJSON` (see below) and calls `wa.create_flow(...)` with
   `publish=True`.
4. Prints the returned `flow_id` so the user can set `WA_PAST_ITEMS_FLOW_ID`.

Re-running against an existing Flow uses `update_flow_json()` + `publish_flow()`
rather than creating a duplicate.

### The screen (`app/services/flows.py`)

One screen, `PAST_ITEMS`, containing a `Form` with a `CheckboxGroup` and a
`Footer` whose `on_click_action` is a `CompleteAction`. For this project the
checkbox `data_source` is a **hardcoded** list of a few Hebrew grocery items
(e.g. חלב, לחם, ביצים, גבינה) returned by a pure function — so it is unit
testable and so the next project has one obvious place to swap in real data.

`app/services/flows.py` holds:

- the screen/`FlowJSON` definition,
- a pure function returning the checkbox `DataSource` options,
- a pure function turning submitted selections into the reply text.

This matches the existing services layout (one concern per module,
`whatsapp.py` holds pure builders that send nothing).

### Endpoint (`app/main.py`, web service only)

`@wa.on_flow_request("/flow/past-items")` is registered on the FastAPI app in
`app/main.py`, with the private key supplied through the `WhatsApp(...)`
constructor (`business_private_key`, `business_private_key_password`) alongside
the existing credentials.

This lives on the **web** service specifically: it is a public HTTPS endpoint
Meta calls, and web is the only service with a public domain. The **worker**
does not need the private key — it only *sends* the trigger message, which
requires no decryption.

On `INIT` the handler returns the static options. On completion,
`@wa.on_flow_completion` replies with a plain WhatsApp text message listing what
was checked. It does **not** touch the database or the shopping list — proving
the round trip is the entire goal here.

### Trigger

The quick-reply buttons return to three (WhatsApp's maximum):
רשימה / **פריטים קודמים** / עזרה.

`cmd:past_items` is handled in `_process_button` (worker side) and sends a
message whose `buttons=` is a `FlowButton` pointing at
`settings.wa_past_items_flow_id`. Tapping that opens the Flow.

If `wa_past_items_flow_id` is empty, it replies with a friendly "not ready yet"
message instead — the same graceful-degradation pattern already used when
`OPENAI_API_KEY` is unset for voice notes.

## Error handling

- Unconfigured flow id or private key → friendly Hebrew message, never a crash.
- pywa raises typed Flow errors (`FlowRequestCannotBeDecrypted`,
  `FlowTokenNoLongerValid`, `FlowRequestSignatureAuthenticationFailed`); the
  request handler logs them and lets pywa acknowledge, consistent with the
  existing "one bad input must not kill the process" posture in
  `app/worker.py` and `app/processing.py`.

## Testing

Unit tests (pytest, in-memory, no network) cover the pure functions:

- the checkbox options builder returns the expected `DataSource` list,
- the completion-reply builder turns a set of selected values into the expected
  Hebrew text, including the empty-selection case,
- `cmd:past_items` sends a `FlowButton` when configured, and the fallback text
  when `wa_past_items_flow_id` is empty (using the existing `FakeWhatsApp`
  double in `tests/test_processing.py`).

The encrypted round-trip against Meta's servers **cannot** be unit tested. That
is manual verification: tap the button in a real chat, confirm the screen
renders, select items, submit, confirm the echo reply arrives. This matches how
the project already verifies its other outward-facing WhatsApp behavior.

## Open risk to validate during implementation

Whether Meta requires an app-review step before a published Flow can be
triggered from a normal message for real (non-preview) recipients, or whether
allowlisted test recipients are sufficient — as they are for the bot's existing
messaging. This is unverified. The implementation plan must check it against
Meta's current documentation before the setup script is run, and surface the
answer rather than assuming.

## Out of scope (belongs to the next project)

- Retaining purchase history: `clear_bought` currently deletes bought items,
  and `remove_items_by_text` deletes removed ones. Preserving history needs an
  `Item.cleared` boolean and a one-off `ALTER TABLE` against production
  Postgres (this project has no migration tooling; `init_db()` only creates
  tables that do not yet exist).
- `get_past_bought_items(...)`: distinct most-recently-bought item texts per
  family, excluding items already needed on the current list.
- Wiring submissions into `handle_intent(action="add")` so picked items are
  really added, with the existing confirmation and list refresh.
