"""Tests for app.services.whatsapp's pure message builders."""

from __future__ import annotations

from pywa.types import Button

from app.services.whatsapp import quick_command_buttons


def test_quick_command_buttons():
    assert quick_command_buttons() == [
        Button(title="רשימה", callback_data="cmd:list"),
        Button(title="פריטים קודמים", callback_data="cmd:past_items"),
        Button(title="עזרה", callback_data="cmd:help"),
    ]
