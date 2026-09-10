"""Tests for app.services.whatsapp's pure message builders."""

from __future__ import annotations

from pywa.types import Button, SectionList

from app.domain.models import Item
from app.services.whatsapp import (
    build_list_message,
    build_past_items_message,
    quick_command_buttons,
)


def _items(*texts):
    return [
        Item(id=n, text=text, list_id=1, added_by_id=1)
        for n, text in enumerate(texts, start=1)
    ]


def test_list_message_offers_a_past_items_row():
    _body, section = build_list_message(_items("חלב", "גבינה"))

    # The shopping items come first, then a section holding the shortcut, so
    # פריטים קודמים is reachable from every list without a second message.
    assert [s.title for s in section.sections] == ["לקנות", "עוד"]
    shortcut = section.sections[1].rows[0]
    assert shortcut.title == "פריטים קודמים"
    assert shortcut.callback_data == "cmd:past_items"


def test_list_message_leaves_room_for_the_shortcut_row():
    _body, section = build_list_message(_items(*[f"פריט {n}" for n in range(1, 13)]))

    # WhatsApp caps a list at 10 rows across ALL sections, so items give one up.
    assert len(section.sections[0].rows) == 9
    assert sum(len(s.rows) for s in section.sections) == 10


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


def test_past_items_message_without_any_usable_row():
    huge = "א" * 200

    body, section = build_past_items_message([huge])

    assert section is None
    assert huge in body
