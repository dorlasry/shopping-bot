"""Download media (voice notes, images, etc.) from the WhatsApp Cloud API.

WhatsApp doesn't put the audio bytes in the webhook — it sends a media *id*.
Fetching the file is a two-step Graph API call:
  1. GET /{media_id}              -> JSON with a short-lived `url` + `mime_type`
  2. GET that url (with auth)     -> the actual binary

Both requests require the Bearer access token; the media URL is NOT public.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_GRAPH = "https://graph.facebook.com/v21.0"


def download_media(media_id: str) -> tuple[bytes, str]:
    """Return (content_bytes, mime_type) for a WhatsApp media id."""
    headers = {"Authorization": f"Bearer {settings.wa_token}"}
    with httpx.Client(timeout=30) as client:
        meta = client.get(f"{_GRAPH}/{media_id}", headers=headers)
        meta.raise_for_status()
        info = meta.json()
        url = info["url"]
        mime_type = info.get("mime_type", "audio/ogg")

        media = client.get(url, headers=headers)
        media.raise_for_status()
        logger.info(
            "downloaded media %s (%s, %d bytes)", media_id, mime_type, len(media.content)
        )
        return media.content, mime_type
