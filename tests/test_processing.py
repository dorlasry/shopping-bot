"""Tests for the worker-side job processing (app.processing).

Uses a FakeWhatsApp double instead of the real pywa client — no network calls.
DB access reuses the in-memory `session` fixture from conftest.py by
monkeypatching app.processing.get_session to yield it directly.
"""

from __future__ import annotations

import contextlib

import pytest
from pywa.types import FlowButton, SectionList

from app import processing
from app.domain.schemas import ParsedIntent
from app.queue.base import IncomingJob
from app.services import whatsapp as wa_msg
from app.services.lists import HELP_TEXT


class FakeWhatsApp:
    """Records send_message/indicate_typing calls instead of hitting the network."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.typing_calls: list[str] = []

    def send_message(self, *, to, text, buttons=None, **kwargs):
        self.sent.append({"to": to, "text": text, "buttons": buttons})

    def indicate_typing(self, *, message_id, **kwargs):
        self.typing_calls.append(message_id)


@pytest.fixture(autouse=True)
def patch_get_session(monkeypatch, session):
    @contextlib.contextmanager
    def _fake_get_session():
        yield session

    monkeypatch.setattr(processing, "get_session", _fake_get_session)


def test_indicate_typing_called_for_message(monkeypatch, session):
    monkeypatch.setattr(
        processing, "parse_message", lambda text: ParsedIntent(action="help")
    )
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="message",
        phone="972500000001",
        name="Tester",
        message_id="wamid.1",
        text="עזרה",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.1"]
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()


def test_indicate_typing_called_for_audio(monkeypatch, session):
    monkeypatch.setattr(processing.transcription, "is_enabled", lambda: False)
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="audio",
        phone="972500000002",
        name="Tester",
        message_id="wamid.2",
        media_id="media123",
        mime_type="audio/ogg",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.2"]


def test_audio_disabled_gets_quick_buttons(monkeypatch, session):
    monkeypatch.setattr(processing.transcription, "is_enabled", lambda: False)
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="audio",
        phone="972500000015",
        name="Tester",
        message_id="wamid.15",
        media_id="media123",
        mime_type="audio/ogg",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000015",
            "text": "זיהוי קולי עדיין לא מוגדר 🙏 נסו לכתוב הודעת טקסט.",
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def test_indicate_typing_called_for_selection(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="selection",
        phone="972500000003",
        name="Tester",
        message_id="wamid.3",
        callback_data="buy:9999",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.3"]


def test_indicate_typing_called_for_button(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000004",
        name="Tester",
        message_id="wamid.4",
        callback_data="cmd:help",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.typing_calls == ["wamid.4"]


def test_indicate_typing_failure_does_not_block_reply(monkeypatch, session):
    monkeypatch.setattr(
        processing, "parse_message", lambda text: ParsedIntent(action="help")
    )
    fake_wa = FakeWhatsApp()

    def boom(*, message_id, **kwargs):
        raise RuntimeError("boom")

    fake_wa.indicate_typing = boom
    job = IncomingJob(
        kind="message",
        phone="972500000005",
        name="Tester",
        message_id="wamid.5",
        text="עזרה",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 1
    assert fake_wa.sent[0]["to"] == "972500000005"
    assert fake_wa.sent[0]["text"] == HELP_TEXT


def test_help_button_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000006",
        name="Tester",
        message_id="wamid.6",
        callback_data="cmd:help",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000006",
            "text": HELP_TEXT,
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def test_stale_selection_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="selection",
        phone="972500000007",
        name="Tester",
        message_id="wamid.7",
        callback_data="buy:9999",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000007",
            "text": "הפריט כבר לא קיים ברשימה.",
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def test_add_item_message_no_buttons_before_list(monkeypatch, session):
    monkeypatch.setattr(
        processing,
        "parse_message",
        lambda text: ParsedIntent(action="add", items=["חלב"]),
    )
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="message",
        phone="972500000008",
        name="Tester",
        message_id="wamid.8",
        text="תביא חלב",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 2
    assert fake_wa.sent[0]["buttons"] is None
    assert "הוספתי" in fake_wa.sent[0]["text"]
    assert isinstance(fake_wa.sent[1]["buttons"], SectionList)


def test_cmd_clear_button_no_buttons_before_list(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000009",
        name="Tester",
        message_id="wamid.9",
        callback_data="cmd:clear",
    )

    processing.process_job(fake_wa, job)

    assert len(fake_wa.sent) == 2
    assert fake_wa.sent[0]["buttons"] is None
    assert fake_wa.sent[0]["text"].startswith("ניקיתי")


def test_cmd_list_empty_gets_quick_buttons(session):
    fake_wa = FakeWhatsApp()
    job = IncomingJob(
        kind="button",
        phone="972500000010",
        name="Tester",
        message_id="wamid.10",
        callback_data="cmd:list",
    )

    processing.process_job(fake_wa, job)

    assert fake_wa.sent == [
        {
            "to": "972500000010",
            "text": "הרשימה ריקה 🎉",
            "buttons": wa_msg.quick_command_buttons(),
        }
    ]


def _past_items_job(phone="972500000020", message_id="wamid.20"):
    return IncomingJob(
        kind="button",
        phone=phone,
        name="Tester",
        message_id=message_id,
        callback_data="cmd:past_items",
    )


def test_past_items_button_sends_flow(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "12345")
    monkeypatch.setattr(
        processing.repo, "get_past_bought_items", lambda *a, **k: ["חלב", "גבינה"]
    )
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    button = fake_wa.sent[0]["buttons"]
    assert isinstance(button, FlowButton)
    assert button.flow_id == "12345"
    assert button.flow_action_payload == {
        "items": [{"id": "חלב", "title": "חלב"}, {"id": "גבינה", "title": "גבינה"}]
    }


def test_past_items_button_without_history(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "12345")
    monkeypatch.setattr(processing.repo, "get_past_bought_items", lambda *a, **k: [])
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    assert "היסטוריה" in fake_wa.sent[0]["text"]
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()


def test_past_items_button_when_flow_not_configured(monkeypatch, session):
    monkeypatch.setattr(processing.settings, "wa_past_items_flow_id", "")
    fake_wa = FakeWhatsApp()

    processing.process_job(fake_wa, _past_items_job())

    assert len(fake_wa.sent) == 1
    assert fake_wa.sent[0]["buttons"] == wa_msg.quick_command_buttons()
