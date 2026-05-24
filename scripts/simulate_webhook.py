"""Simulate a WhatsApp Cloud API webhook locally — like a Postman call, but it
builds a realistic payload AND signs it correctly so pywa accepts it.

This lets you exercise the whole pipe (webhook -> signature check -> handler ->
queue -> worker -> parser -> DB -> reply) on your laptop, with NO Meta and NO
ngrok involved.

Prereqs:
  - Your local server is running:  uvicorn app.main:app --port 8000
  - For a self-contained loop, use QUEUE_BACKEND=memory in .env so the worker
    runs in-process (otherwise also run `python -m app.worker`).
  - .env must have WA_APP_SECRET set to the SAME value the server uses (it does,
    since both read the same .env) — that's what makes the signature match.

Usage:
  # a text message
  python scripts/simulate_webhook.py "תביא חלב וגבינה"
  python scripts/simulate_webhook.py "רשימה"

  # tapping a list row (marks item id 3 bought)
  python scripts/simulate_webhook.py --buy 3 --title "חלב"

  # tapping a reply button
  python scripts/simulate_webhook.py --button cmd:list

  # options
  python scripts/simulate_webhook.py "תביא לחם" --url http://localhost:8000/ \
      --phone 972500000001 --name "דור"

After sending, watch your uvicorn (and worker) terminal to see it processed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request

# Load the same settings the server uses (this also loads .env).
sys.path.insert(0, ".")
from app.config import settings  # noqa: E402


def _message_envelope(message: dict, phone: str, name: str) -> dict:
    """Wrap a single message object in the full WhatsApp webhook structure."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_LOCAL_SIM",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": settings.wa_phone_id,
                            },
                            "contacts": [
                                {"profile": {"name": name}, "wa_id": phone}
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _base_message(phone: str) -> dict:
    return {
        "from": phone,
        "id": f"wamid.SIM{int(time.time() * 1000)}",
        "timestamp": str(int(time.time())),
    }


def build_text(phone: str, name: str, text: str) -> dict:
    msg = _base_message(phone)
    msg.update({"type": "text", "text": {"body": text}})
    return _message_envelope(msg, phone, name)


def build_list_reply(phone: str, name: str, row_id: str, title: str) -> dict:
    msg = _base_message(phone)
    msg.update(
        {
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": row_id, "title": title},
            },
        }
    )
    return _message_envelope(msg, phone, name)


def build_button_reply(phone: str, name: str, button_id: str, title: str) -> dict:
    msg = _base_message(phone)
    msg.update(
        {
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": button_id, "title": title},
            },
        }
    )
    return _message_envelope(msg, phone, name)


def sign(body: bytes) -> str:
    """Compute Meta's X-Hub-Signature-256 header value over the raw body."""
    digest = hmac.new(
        settings.wa_app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def post(url: str, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"→ {resp.status} {resp.reason}")
            print(f"  response: {resp.read().decode() or '(empty)'}")
            print("\nSent ✓  Now check your uvicorn/worker logs for processing.")
    except urllib.error.HTTPError as e:
        print(f"→ {e.code} {e.reason}")
        print(f"  body: {e.read().decode()}")
        if e.code == 401:
            print(
                "\n401 = signature rejected. Make sure WA_APP_SECRET in .env matches "
                "the running server's value."
            )
    except urllib.error.URLError as e:
        print(f"✗ Could not reach {url}: {e.reason}")
        print("  Is the server running?  uvicorn app.main:app --port 8000")


def main() -> None:
    p = argparse.ArgumentParser(description="Simulate a WhatsApp webhook locally.")
    p.add_argument("text", nargs="?", help="text message body (e.g. 'תביא חלב')")
    p.add_argument("--buy", metavar="ITEM_ID", help="simulate tapping a list row: buy:<ITEM_ID>")
    p.add_argument("--button", metavar="DATA", help="simulate a button tap (e.g. cmd:list)")
    p.add_argument("--title", default="", help="display title for the tapped row/button")
    p.add_argument("--url", default="http://localhost:8000/", help="local webhook URL")
    p.add_argument("--phone", default="972500000001", help="sender phone (wa_id)")
    p.add_argument("--name", default="Local Tester", help="sender display name")
    args = p.parse_args()

    chosen = [bool(args.text), bool(args.buy), bool(args.button)]
    if sum(chosen) != 1:
        p.error("provide exactly ONE of: a text argument, --buy, or --button")

    if args.text:
        print(f"Simulating TEXT from {args.phone}: {args.text!r}")
        payload = build_text(args.phone, args.name, args.text)
    elif args.buy:
        row_id = f"buy:{args.buy}"
        print(f"Simulating LIST TAP from {args.phone}: {row_id}")
        payload = build_list_reply(args.phone, args.name, row_id, args.title or "פריט")
    else:
        print(f"Simulating BUTTON TAP from {args.phone}: {args.button}")
        payload = build_button_reply(args.phone, args.name, args.button, args.title or "כפתור")

    post(args.url, payload)


if __name__ == "__main__":
    main()
