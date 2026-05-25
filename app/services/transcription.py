"""Speech-to-text for Hebrew voice notes, via OpenAI Whisper.

Claude can't transcribe audio, so we use OpenAI's transcription API. We pin the
language to Hebrew ("he") for much better accuracy on short shopping phrases.

`transcribe` raises on API errors; the caller (worker) catches and replies
gracefully so a bad recording never crashes the worker.
"""

from __future__ import annotations

from openai import OpenAI

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Biasing prompt: Whisper uses this as context to spell domain words correctly.
# Listing common Hebrew grocery terms + command verbs sharply reduces errors on
# "difficult words" (brand names, less-common produce, etc.).
_VOCAB_PROMPT = (
    "הודעה לרשימת קניות בעברית. "
    "מילים נפוצות: חלב, גבינה, לחם, ביצים, חמאה, יוגורט, קוטג', שמנת, "
    "עגבניות, מלפפון, בצל, שום, פלפל, תפוחי אדמה, גזר, חסה, לימון, "
    "עוף, בשר, דגים, סלמון, אורז, פסטה, קמח, סוכר, מלח, שמן, "
    "קפה, תה, מיץ, מים, שוקולד, ביסקוויטים, נייר טואלט, סבון. "
    "פעלים: תביא, צריך, תוסיף, קניתי, קנינו, לקחתי, תמחק, תוריד."
)


def is_enabled() -> bool:
    """Voice transcription is only available when an OpenAI key is configured."""
    return bool(settings.openai_api_key)


def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Transcribe audio bytes to Hebrew text. Returns the transcript (may be empty)."""
    # Whisper infers the format from the filename extension, so derive it from the
    # mime type (e.g. "audio/ogg; codecs=opus" -> "ogg").
    subtype = mime_type.split("/")[-1].split(";")[0].strip() if mime_type else "ogg"
    ext = subtype or "ogg"

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.audio.transcriptions.create(
        model=settings.whisper_model,
        file=(f"voice.{ext}", audio_bytes),
        language="he",
        prompt=_VOCAB_PROMPT,
    )
    text = (response.text or "").strip()
    logger.info("transcribed %d bytes -> %r", len(audio_bytes), text)
    return text
