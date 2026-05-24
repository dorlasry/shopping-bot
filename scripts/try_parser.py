"""Run the Hebrew parser locally, no WhatsApp needed.

Great for a demo: prove the NLP works in isolation.

Usage:
    python scripts/try_parser.py "תביא חלב וגבינה ולחם"
    python scripts/try_parser.py            # runs a built-in set of examples
"""

from __future__ import annotations

import sys

# Allow running as `python scripts/try_parser.py` from the project root.
sys.path.insert(0, ".")

from app.services.parser import parse_message  # noqa: E402

EXAMPLES = [
    "תביא חלב וגבינה ולחם",
    "צריך ביצים",
    "תוריד את החלב",
    "מה יש ברשימה?",
    "נקה את מה שקנינו",
    "היי מה נשמע",
    "עזרה",
]


def main() -> None:
    args = sys.argv[1:]
    messages = args if args else EXAMPLES

    for text in messages:
        intent = parse_message(text)
        items = ", ".join(intent.items) if intent.items else "—"
        print(f"{text!r}")
        print(f"   action={intent.action!r}  items=[{items}]")
        print()


if __name__ == "__main__":
    main()
