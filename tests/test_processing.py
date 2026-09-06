"""Tests for the worker-side job processing (app.processing).

Uses a FakeWhatsApp double instead of the real pywa client — no network calls.
DB access reuses the in-memory `session` fixture from conftest.py by
monkeypatching app.processing.get_session to yield it directly.
"""

from __future__ import annotations

import contextlib

import pytest

from app import processing
from app.domain.schemas import ParsedIntent
from app.queue.base import IncomingJob
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
