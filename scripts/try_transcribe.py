"""Test Hebrew speech-to-text locally on an audio file — no WhatsApp needed.

The voice-note equivalent of try_parser.py: feed it a local audio file and it
prints the transcript, so you can verify Whisper + Hebrew before wiring it to
WhatsApp.

Usage:
    python scripts/try_transcribe.py path/to/voice.ogg
    python scripts/try_transcribe.py recording.m4a

Requires OPENAI_API_KEY in your .env.
"""

from __future__ import annotations

import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, ".")
from app.services import transcription  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/try_transcribe.py <audio-file>")
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    if not transcription.is_enabled():
        print("OPENAI_API_KEY is not set in .env — voice transcription is disabled.")
        sys.exit(1)

    mime_type = mimetypes.guess_type(str(path))[0] or "audio/ogg"
    audio_bytes = path.read_bytes()
    print(f"Transcribing {path.name} ({mime_type}, {len(audio_bytes)} bytes)…\n")

    text = transcription.transcribe(audio_bytes, mime_type)
    print(f"Transcript: {text!r}" if text else "(empty transcript)")


if __name__ == "__main__":
    main()
