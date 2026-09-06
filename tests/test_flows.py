"""Tests for the static past-items Flow definition and its payload helpers."""

from __future__ import annotations

import json

from app.services import flows


def test_build_items_payload_uses_text_as_id_and_title():
    assert flows.build_items_payload(["חלב", "גבינה"]) == {
        "items": [
            {"id": "חלב", "title": "חלב"},
            {"id": "גבינה", "title": "גבינה"},
        ]
    }


def test_build_items_payload_empty():
    assert flows.build_items_payload([]) == {"items": []}


def test_picked_items_from_list():
    assert flows.picked_items({"picked": ["חלב", "גבינה"]}) == ["חלב", "גבינה"]


def test_picked_items_from_json_string():
    # WhatsApp may deliver the array JSON-encoded.
    assert flows.picked_items({"picked": json.dumps(["חלב"])}) == ["חלב"]


def test_picked_items_when_nothing_selected():
    assert flows.picked_items({"picked": []}) == []
    assert flows.picked_items({}) == []
    assert flows.picked_items(None) == []


def test_flow_json_is_static_and_wires_the_checkbox():
    data = json.loads(flows.build_flow_json().to_json())

    # A static flow declares no endpoint.
    assert "data_api_version" not in data
    assert "data_channel_uri" not in data

    screen = data["screens"][0]
    assert screen["id"] == "PAST_ITEMS"
    assert screen["terminal"] is True
    assert "items" in screen["data"]

    form = screen["layout"]["children"][0]
    checkbox, footer = form["children"]
    assert checkbox["type"] == "CheckboxGroup"
    assert checkbox["data-source"] == "${data.items}"
    assert footer["on-click-action"]["name"] == "complete"
    assert footer["on-click-action"]["payload"] == {"picked": "${form.picked}"}
