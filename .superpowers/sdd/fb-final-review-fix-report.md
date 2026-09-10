# Final whole-branch review — fixes applied

Branch: `past-items-list-fallback`. All six review findings addressed in one commit.

## Fix 1 (Important) — dead-end when every past item is too long for a callback

`build_past_items_message` returns `(body, None)` when every candidate row is
skipped (callback > 200 chars). `_send_past_items` already handled `None` via
`_send_final` (quick buttons attached); `_process_readd` did not — it sent
`buttons=None`, leaving the user with nothing to tap and no quick buttons.

Extracted the shared tail into a new helper in `app/processing.py`:

```python
def _send_past_items_list(wa: WhatsApp, phone: str, texts: list[str]) -> None:
    """Send the past-items picker as an interactive list."""
    body, section_list = wa_msg.build_past_items_message(texts)
    if section_list is None:
        _send_final(wa, phone, body)
    else:
        wa.send_message(to=phone, text=body, buttons=section_list)
```

Both `_send_past_items`'s non-flow path and the tail of `_process_readd` now
call this helper instead of duplicating the build-and-send logic.

## Fix 2 (Important) — config comment/`.env.example` described the deleted behaviour

`app/config.py` and `.env.example` both said an empty `wa_past_items_flow_id`
"disables the feature (the bot replies that it isn't ready yet)". That
behaviour was deleted by this branch. Reworded both comments to say empty
delivers the picker as an interactive list, and that setting the id printed
by `scripts/setup_flow.py` switches to the Flow.

## Fix 3 (Important) — README stale/contradictory in three places

1. Dropped the `(Flow)` parenthetical from the `פריטים קודמים` row in the
   "Commands the bot understands" table — the Flow is now opt-in, not the
   default.
2. Moved the Flow-specific prose ("Tapping **פריטים קודמים** opens a
   multi-select …", "It uses a *static* WhatsApp Flow …") and the
   Flow-only setup steps (business account id, create flow, set flow id)
   under a new `### Flow mode` sub-heading, so it reads as the opt-in path
   rather than sitting directly under the bullet list that says empty is
   the interactive-list default.
3. Pulled the database migration out into its own `### Migrate the database
   (required either way)` sub-heading, ahead of `### Flow mode`, since it is
   mandatory in both modes (SQLAlchemy loads the whole `Item` entity, so an
   unmigrated DB breaks every command). Changed the "empty" bullet to say
   "No Flow setup needed" instead of "No setup at all". Renumbered the
   Flow-only setup steps 1-3 (previously 2-4, since step 1 was the
   migration). Updated the "set" bullet's setup pointer to link to
   `#flow-mode`.

Changed nothing outside the past-items section and that one table row.

## Fix 4 (carried Minor) — untested branch that hid Fix 1

Added `test_past_items_message_without_any_usable_row` to
`tests/test_whatsapp.py`, covering the case where every offered item is too
long for a callback:

```python
def test_past_items_message_without_any_usable_row():
    huge = "א" * 200

    body, section = build_past_items_message([huge])

    assert section is None
    assert huge in body
```

## Fix 5 (carried Minor) — module docstring

Added a bullet to the constraints list at the top of
`app/services/whatsapp.py`:

```
  - A SectionRow's callback id is capped at 200 chars.
```

## Fix 6 (carried Minor) — why `_process_readd` never branches on the flow setting

Added a comment at the send site in `_process_readd` explaining that a
`readd:` callback can only originate from a list row (never a Flow), so the
refreshed picker is always the list regardless of
`settings.wa_past_items_flow_id`.

## Commands run

```
$ .venv/bin/python -c "import app.processing, app.services.whatsapp, app.config"
(no output — imports succeeded)

$ .venv/bin/pytest -q
....................................................................     [100%]
68 passed in 0.70s

$ .venv/bin/ruff check app tests
Found 9 errors.
[*] 9 fixable with the `--fix` option.
```

Ruff baseline confirmed: all 9 findings are pre-existing (3x UP017 in
`app/db/repository.py`, I001 in `app/db/session.py` and
`app/domain/models.py`, RUF100 in `app/db/session.py`, `app/processing.py`,
and two in `app/worker.py`). None are new, and none fall inside the lines
this change touched — the `app/processing.py` RUF100 is a pre-existing
`# noqa: BLE001` on the audio-transcription exception handler, unrelated to
the past-items code edited here.

`git diff` reviewed: no Hebrew string content changed (only English
comments/docstrings/README prose), and the README diff is confined to the
"Commands the bot understands" table row and the "Past-items picker"
section.
