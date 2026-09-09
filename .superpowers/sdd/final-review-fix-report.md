# Final review fix report

Applied the five findings from the whole-branch code review on
`past-items-picker` in one commit.

## Finding 1 (CRITICAL) — option cap and title length violate Meta's limits

- `app/services/flows.py`: `MAX_PAST_ITEMS` lowered from `30` to `20`, with the
  comment rewritten to say the cap is Meta's documented CheckboxGroup limit
  (not an arbitrary payload-size choice). Added `MAX_TITLE_CHARS = 30`.
- `build_items_payload` now truncates the option `title` to `MAX_TITLE_CHARS`
  while keeping the full text as the `id` (the id is what comes back in the
  flow completion and gets added to the list, so it must stay untruncated).
- Promoted `app/services/whatsapp.py`'s private `_truncate(text, limit)` to a
  public `truncate(text, limit)` (identical body/docstring behaviour), updated
  its one existing caller in that file (`build_list_message`'s `SectionRow`
  title), and imported it in `app/services/flows.py` instead of duplicating
  it. Confirmed via `grep -rn "_truncate\b"` that no other file referenced the
  old private name.
- `tests/test_flows.py`: kept the existing
  `test_build_items_payload_uses_text_as_id_and_title` (still valid for short
  names), added
  `test_build_items_payload_truncates_long_titles_but_keeps_full_id` (40-char
  Hebrew name -> `id` unchanged, `title` shortened and `<= MAX_TITLE_CHARS`),
  and added `test_max_past_items_matches_metas_checkbox_group_cap` with a
  comment explaining *why* 20 (Meta's documented cap), not just asserting the
  number.

## Finding 2 (Important) — `.env.example` missing `WA_PAST_ITEMS_FLOW_ID`

Added `WA_PAST_ITEMS_FLOW_ID=` to `.env.example` right after
`WA_BUSINESS_ACCOUNT_ID`, with a comment mirroring `app/config.py`'s
(`empty disables the feature ... set it to the flow id printed by
scripts/setup_flow.py`).

## Finding 3 (Important) — migration reads as optional but is mandatory

- `README.md`, "Past-items picker" -> "One-time setup" step 1: reworded to
  lead with **mandatory, not opt-in**, explains that every `items` query now
  selects `cleared` and `init_db()` never alters existing tables, and states
  plainly that skipping the migration breaks *every* command (add, list, buy,
  clear), not just the picker. The migration must run **before** deploying
  the new code.
- Added a blockquote note at the top of "Deploying to Railway" -> "Steps"
  cross-referencing the "Migrate the database" step above via an anchor link,
  so someone following the deploy steps top-to-bottom cannot miss it.

## Finding 4 (Minor) — test that cannot fail

`tests/test_processing.py::test_past_items_button_when_flow_not_configured`
now also asserts `"עדיין לא מוכן" in fake_wa.sent[0]["text"]` — a substring
unique to the "not configured" reply (`"הפיצ'ר הזה עדיין לא מוכן 🙏"`), distinct
from the "no history" fallback's text (`"אין עדיין היסטוריה של קניות ..."`).
This pins the unconfigured-guard path instead of only checking the buttons
both fallbacks share.

## Finding 5 (Minor) — stale README

- Added a row to "Commands the bot understands":
  `| \`פריטים קודמים\` | opens the past-items picker (Flow) |`.
- Added to the project-layout tree: `flows.py` under `app/services/` and
  `setup_flow.py` under `scripts/`, one-line descriptions matching the style
  of their neighbours.
- Added a note under the "Create the flow" step: re-running
  `scripts/setup_flow.py` creates a second flow and fails on the duplicate
  name; use `python scripts/setup_flow.py --update FLOW_ID` to push a changed
  screen to the existing flow instead.

## Commands run

```
$ git status && git branch --show-current
On branch past-items-picker
Untracked files: .superpowers/
past-items-picker

# Baseline, before any changes
$ .venv/bin/pytest -q
........................................................                 [100%]
56 passed in 0.91s

$ .venv/bin/ruff check app tests scripts
Found 12 errors. [*] 12 fixable
$ .venv/bin/ruff check app tests
Found 9 errors. [*] 9 fixable
$ .venv/bin/ruff check scripts
Found 3 errors. [*] 3 fixable
```

(baseline matches the brief: 9 in app+tests, 3 pre-existing in scripts/)

```
# After all edits
$ .venv/bin/python -c "import app.services.lists, app.services.flows, app.processing, app.services.whatsapp"
PARSE_OK   (no output, exit 0)

$ .venv/bin/pytest -q
..........................................................               [100%]
58 passed in 0.83s

$ .venv/bin/ruff check app tests scripts
Found 12 errors. [*] 12 fixable

$ .venv/bin/ruff check app tests | grep -E "\-\->"
   --> app/db/repository.py:142:35
   --> app/db/repository.py:161:43
   --> app/db/repository.py:176:39
  --> app/db/session.py:9:1
  --> app/db/session.py:69:36
  --> app/domain/models.py:11:1
  --> app/processing.py:82:24
  --> app/worker.py:47:28
  --> app/worker.py:53:28
```

All 9 app/tests ruff findings are in pre-existing, untouched files
(`repository.py`, `session.py`, `models.py`, `worker.py`) plus one pre-existing
finding in `processing.py` at a line unrelated to this change (line 82,
`logger.exception` call in `_process_audio`, untouched). None are in
`flows.py`, `whatsapp.py`, or the test files edited — ruff baseline preserved
exactly (12 total, same split as before: 9 app+tests / 3 scripts).

```
$ git diff --stat
 .env.example             |  4 ++++
 README.md                | 20 +++++++++++++++++---
 app/services/flows.py    | 22 +++++++++++++++++-----
 app/services/whatsapp.py |  4 ++--
 tests/test_flows.py      | 16 ++++++++++++++++
 tests/test_processing.py |  1 +
 6 files changed, 57 insertions(+), 10 deletions(-)
```

Reviewed the full `git diff` output: no unintended changes to unrelated
README sections, and all Hebrew strings (curly-quote strings included) are
untouched/intact — confirmed by the parse check and by inspection of the
diff hunks above.

## Verification summary

1. `.venv/bin/pytest` — 58 passed (56 baseline + 2 new tests in
   `tests/test_flows.py`; the one new assertion in `test_processing.py` was
   added to an existing test, not a new test).
2. `.venv/bin/ruff check app tests scripts` — 12 findings, identical to
   baseline (9 app+tests pre-existing, 3 scripts pre-existing). No new
   findings introduced.
3. `.venv/bin/python -c "import app.services.lists, app.services.flows, app.processing, app.services.whatsapp"` — succeeds silently.
4. `git diff` reviewed in full — scoped to the intended files and findings
   only.
