"""WhatsApp message construction (pywa).

Pure builders: these functions turn domain objects into pywa interactive-message
objects. They do NOT send anything — the handler decides when/where to send,
which keeps this module easy to unit-test.

WhatsApp constraints baked in here:
  - An interactive list message allows at most 10 rows total.
  - A SectionRow title is capped at 24 chars; the list button title at 20.
  - Reply buttons: at most 3 per message.
"""

from __future__ import annotations

from pywa.types import Button, Section, SectionList, SectionRow

from app.domain.models import Item

LIST_BUTTON_TITLE = "סמן שנקנה"  # must be <= 20 chars
MAX_ROWS = 10


def build_list_message(items: list[Item]) -> tuple[str, SectionList | None]:
    """Return (body_text, interactive_list).

    If the list is empty, interactive_list is None and the caller should just
    send the body text.
    """
    if not items:
        return "הרשימה ריקה 🎉", None

    shown = items[:MAX_ROWS]
    rows = [
        SectionRow(
            title=_truncate(item.text, 24),
            callback_data=f"buy:{item.id}",
            description="הקש כדי לסמן שנקנה",
        )
        for item in shown
    ]
    section = Section(title="לקנות", rows=rows)

    body = "🛒 הרשימה שלכם:"
    if len(items) > MAX_ROWS:
        body += f"\n(מוצגים {MAX_ROWS} מתוך {len(items)} — נקו או סמנו כדי לראות עוד)"

    return body, SectionList(button_title=LIST_BUTTON_TITLE, sections=[section])


def quick_command_buttons() -> list[Button]:
    """Three reply buttons for the common actions."""
    return [
        Button(title="רשימה", callback_data="cmd:list"),
        Button(title="נקה", callback_data="cmd:clear"),
        Button(title="עזרה", callback_data="cmd:help"),
    ]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
