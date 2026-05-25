"""Hebrew message parsing with Claude.

Turns free-text Hebrew like:
    "תביא חלב וגבינה ולחם"      -> add ["חלב", "גבינה", "לחם"]
    "תוריד את הביצים"           -> remove ["ביצים"]
    "מה יש ברשימה?"            -> view
    "נקה את הרשימה"            -> clear
into a structured ParsedIntent.

We ask Claude to return STRICT JSON and use a tool/JSON-mode style prompt. If the
model returns something unparseable (rare), we fall back to action="unknown" so the
bot degrades gracefully instead of crashing.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import settings
from app.domain.schemas import ParsedIntent
from app.logging_config import get_logger

logger = get_logger(__name__)

_client = Anthropic(api_key=settings.anthropic_api_key)

_SYSTEM_PROMPT = """You parse Hebrew (and sometimes English) WhatsApp messages \
for a shared shopping-list bot. Decide what the user wants and extract item names.

Return ONLY a JSON object, no prose, with this exact shape:
{"action": "<action>", "items": ["<item>", ...]}

Valid actions:
- "add": user wants to add items to the list, i.e. things still NEEDED \
(e.g. "תביא חלב", "צריך לחם", "תוסיף ביצים", "תקנה גבינה")
- "bought": user reports they ALREADY bought/got SPECIFIC items — mark them as \
purchased, do NOT delete them (e.g. "קניתי חלב", "קנינו גבינה ולחם", "כבר קניתי ביצים", "לקחתי עגבניות", "השגתי שמן")
- "bought_all": user reports they bought EVERYTHING on the list, with no specific \
items named (e.g. "קניתי הכל", "קנינו הכל", "לקחתי את הכל", "סיימתי את הקניות", "יש לי הכל"). items must be empty.
- "remove": user wants to remove/cancel items from the list because they're no \
longer wanted — NOT because they bought them (e.g. "תוריד את החלב", "מחק ביצים", "תמחק חלב", "הסר לחם", "כבר לא צריך עגבניות")
- "view": user wants to see the list (e.g. "מה יש", "רשימה", "תראה לי")
- "clear": user wants to clear/empty the bought items or list (e.g. "נקה", "תרוקן")
- "greeting": a greeting or small talk with no list action. Greetings may be in \
Hebrew, English, or transliteration (e.g. "היי", "שלום", "hi", "hello", "מה נשמע").
- "help": user asks what the bot can do (e.g. "עזרה", "מה אתה יודע לעשות")
- "unknown": none of the above / unclear

Rules for items:
- Extract clean singular item names without command words. "תביא חלב וגבינה" -> ["חלב", "גבינה"].
- Strip leading articles like "את", "ה" where natural ("את הביצים" -> "ביצים").
- Only add/remove/bought carry items; for all other actions, items must be an empty list.
- Keep item text in the user's original language (usually Hebrew)."""


def parse_message(text: str) -> ParsedIntent:
    """Parse a single user message into a ParsedIntent. Never raises on bad model output."""
    text = (text or "").strip()
    if not text:
        return ParsedIntent(action="unknown", items=[])

    try:
        response = _client.messages.create(
            model=settings.claude_model,
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        data = _extract_json(raw)
        intent = ParsedIntent.model_validate(data)
        # Defensive: clear items for actions that shouldn't carry any.
        if intent.action not in ("add", "remove", "bought"):
            intent.items = []
        return intent
    except Exception as exc:  # noqa: BLE001 — we want graceful degradation here
        logger.warning("parse_message failed for %r: %s", text, exc)
        return ParsedIntent(action="unknown", items=[])


def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of the model's reply, tolerating stray text/fencing."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Strip code fences like ```json ... ```
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in model reply: {raw!r}")
    return json.loads(raw[start : end + 1])
