"""Business logic: turn a ParsedIntent into an action + a reply.

This is the brain that sits between "we understood the message" and "we touched
the database / replied to the user". Handlers stay thin by delegating here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.models import User
from app.domain.schemas import ParsedIntent

HELP_TEXT = (
    "אני בוט רשימת קניות 🛒\n"
    "• כתבו לי מה להביא: “תביא חלב וגבינה”\n"
    "• סימון שנקנה: “קניתי חלב וגבינה” (או “קניתי הכל”) ✓\n"
    "• להסרה: “תוריד את הביצים”\n"
    "• לצפייה: “רשימה” או “מה יש”\n"
    "• לניקוי שנקנה: “נקה”"
)


@dataclass
class ActionResult:
    """What the handler should do after business logic runs."""

    reply_text: str
    # When True, the handler should ALSO send the interactive list message so the
    # user can tap items to mark them bought.
    show_list: bool = False


def handle_intent(session: Session, user: User, intent: ParsedIntent) -> ActionResult:
    active_list = repo.get_active_list(session, user.family_id)

    match intent.action:
        case "add":
            created = repo.add_items(session, active_list.id, user.id, intent.items)
            if not created:
                return ActionResult("לא הוספתי כלום (אולי כבר ברשימה?)")
            names = ", ".join(i.text for i in created)
            return ActionResult(f"הוספתי: {names} ✅", show_list=True)

        case "bought":
            marked = repo.mark_items_bought_by_text(
                session, active_list.id, user.id, intent.items
            )
            if not marked:
                return ActionResult("לא מצאתי את הפריטים האלה ברשימה 🤔")
            return ActionResult(f"סימנתי שנקנו: {', '.join(marked)} ✓", show_list=True)

        case "bought_all":
            marked = repo.mark_all_bought(session, active_list.id, user.id)
            if not marked:
                return ActionResult("הרשימה כבר ריקה 🎉")
            return ActionResult(
                f"כל הכבוד! סימנתי שהכל נקנה ✓ ({len(marked)} פריטים) 🎉",
                show_list=True,
            )

        case "remove":
            removed = repo.remove_items_by_text(session, active_list.id, intent.items)
            if not removed:
                return ActionResult("לא מצאתי את הפריטים האלה ברשימה.")
            return ActionResult(f"הסרתי: {', '.join(removed)} 🗑️", show_list=True)

        case "view":
            needed = repo.get_needed_items(session, active_list.id)
            if not needed:
                return ActionResult("הרשימה ריקה 🎉")
            return ActionResult("", show_list=True)

        case "clear":
            count = repo.clear_bought(session, active_list.id)
            return ActionResult(f"ניקיתי {count} פריטים שנקנו. ✨", show_list=True)

        case "greeting":
            return ActionResult(
                "היי! 👋 אני בוט רשימת הקניות שלכם 🛒\n"
                'כתבו (או הקליטו!) מה להביא — למשל "תביא חלב וגבינה".\n'
                'כשקניתם, אמרו "קניתי חלב וגבינה" ואסמן ✓\n'
                'לצפייה ברשימה: "רשימה".'
            )

        case "help":
            return ActionResult(HELP_TEXT)

        case _:  # "unknown"
            return ActionResult(
                "לא הבנתי 🤔 נסו למשל “תביא חלב” או כתבו “עזרה”."
            )
