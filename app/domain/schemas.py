"""Pydantic schemas used at the boundaries (parser output, etc.).

These are NOT database models — they're the typed shapes we pass around in code.
The most important one is ParsedIntent: the structured result of running a free-text
Hebrew message through Claude.
"""

from typing import Literal

from pydantic import BaseModel, Field

# The set of things a user can intend with a message.
Action = Literal["add", "remove", "view", "clear", "greeting", "help", "unknown"]


class ParsedIntent(BaseModel):
    """Structured interpretation of a user's free-text message."""

    action: Action = "unknown"
    # For add/remove: the item names extracted from the message (in Hebrew).
    items: list[str] = Field(default_factory=list)
