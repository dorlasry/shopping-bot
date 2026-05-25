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

    # Body shows EVERY item numbered, so the whole list is readable at a glance.
    lines = [f"{idx}. {item.text}" for idx, item in enumerate(items, start=1)]
    body = "🛒 הרשימה שלכם:\n" + "\n".join(lines)

    # WhatsApp interactive lists cap at 10 rows, so only the first 10 are tappable.
    # Items beyond that are still listed above and can be marked by voice/text.
    tappable = items[:MAX_ROWS]
    if len(items) > MAX_ROWS:
        body += (
            f"\n\nאפשר להקיש לסימון על {MAX_ROWS} הראשונים, "
            'או פשוט לומר "קניתי <שם הפריט>" לכל פריט אחר.'
        )
    else:
        body += "\n\nהקישו על הכפתור למטה כדי לסמן מה שכבר נקנה 👇"

    # No row description — WhatsApp echoes it into the user's selection bubble,
    # which makes that confirmation look cluttered/redundant.
    rows = [
        SectionRow(title=_truncate(item.text, 24), callback_data=f"buy:{item.id}")
        for item in tappable
    ]
    section = Section(title="לקנות", rows=rows)

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
