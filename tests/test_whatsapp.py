"""Tests for app.services.whatsapp's pure message builders."""

from __future__ import annotations

from pywa.types import Button, SectionList

from app.services.whatsapp import build_past_items_message, quick_command_buttons


def test_quick_command_buttons():
    assert quick_command_buttons() == [
        Button(title="רשימה", callback_data="cmd:list"),
        Button(title="פריטים קודמים", callback_data="cmd:past_items"),
        Button(title="עזרה", callback_data="cmd:help"),
    ]


def test_past_items_message_empty():
    body, section = build_past_items_message([])
    assert section is None
    assert "היסטוריה" in body


def test_past_items_message_lists_and_makes_rows():
    body, section = build_past_items_message(["חלב", "גבינה"])

    assert "1. חלב" in body
    assert "2. גבינה" in body
    assert isinstance(section, SectionList)
    rows = section.sections[0].rows
    assert [r.callback_data for r in rows] == ["readd:חלב", "readd:גבינה"]
    assert [r.title for r in rows] == ["חלב", "גבינה"]


def test_past_items_message_caps_tappable_rows_at_ten():
    texts = [f"פריט {n}" for n in range(1, 13)]

    body, section = build_past_items_message(texts)

    assert len(section.sections[0].rows) == 10
    # All twelve are still readable in the body, and the note explains that
    # only the first ten are tappable.
    assert "12. פריט 12" in body
    assert "אפשר להקיש על 10 הראשונים" in body


def test_past_items_message_truncates_row_title_but_not_callback():
    long_name = "נייר טואלט אקסטרה רך 24 גלילים במבצע"

    _body, section = build_past_items_message([long_name])

    row = section.sections[0].rows[0]
    assert len(row.title) == 24
    assert row.title.endswith("…")
    # The callback keeps the full text, so the right item gets added.
    assert row.callback_data == f"readd:{long_name}"


def test_past_items_message_skips_item_too_long_for_a_callback():
    huge = "א" * 200

    body, section = build_past_items_message(["חלב", huge])

    assert [r.callback_data for r in section.sections[0].rows] == ["readd:חלב"]
    # It is still offered in the body, where it can be added by typing.
    assert huge in body
