"""The past-items WhatsApp Flow (static) and its payload helpers.

This is a *static* flow: it declares no endpoint and no data API version, so
Meta never calls us and no encryption keys are involved. Every value the screen
shows is supplied when the message is sent, via `flow_action_payload`, and the
user's ticks come back in the flow-completion message.

Pure builders only — nothing here sends anything, matching `whatsapp.py`.
"""

from __future__ import annotations

import json

from pywa import utils
from pywa.types.flows import (
    CheckboxGroup,
    CompleteAction,
    DataSource,
    FlowJSON,
    Footer,
    Form,
    Layout,
    Screen,
    ScreenData,
)

SCREEN_ID = "PAST_ITEMS"
ITEMS_KEY = "items"
PICKED_FIELD = "picked"
FORM_NAME = "past_items_form"

# Purchase history is unbounded over time (a shopping list is not), so the
# picker is capped to keep the message payload small.
MAX_PAST_ITEMS = 30

SCREEN_TITLE = "פריטים קודמים"
CHECKBOX_LABEL = "מה להוסיף לרשימה?"
SUBMIT_LABEL = "הוסף לרשימה"


def build_flow_json() -> FlowJSON:
    """The one-screen flow: tick past items, submit, done."""
    items = ScreenData(key=ITEMS_KEY, example=[DataSource(id="חלב", title="חלב")])
    picked = CheckboxGroup(
        name=PICKED_FIELD,
        data_source=items.ref,
        label=CHECKBOX_LABEL,
        required=True,
    )
    return FlowJSON(
        version=utils.Version.FLOW_JSON,
        screens=[
            Screen(
                id=SCREEN_ID,
                title=SCREEN_TITLE,
                terminal=True,
                data=[items],
                layout=Layout(
                    children=[
                        Form(
                            name=FORM_NAME,
                            children=[
                                picked,
                                Footer(
                                    label=SUBMIT_LABEL,
                                    on_click_action=CompleteAction(
                                        payload={PICKED_FIELD: picked.ref}
                                    ),
                                ),
                            ],
                        )
                    ]
                ),
            )
        ],
    )


def build_items_payload(texts: list[str]) -> dict:
    """The `flow_action_payload` that fills the checkbox at send time.

    The item text doubles as the option id, so the values the flow returns are
    the texts themselves — nothing has to be remembered between messages.
    """
    return {ITEMS_KEY: [{"id": text, "title": text} for text in texts]}


def picked_items(response: dict | None) -> list[str]:
    """The item texts the user ticked, from a flow-completion response."""
    if not response:
        return []
    picked = response.get(PICKED_FIELD)
    if isinstance(picked, str):
        try:
            picked = json.loads(picked)
        except ValueError:
            picked = [picked]
    if not isinstance(picked, list):
        return []
    return [str(p).strip() for p in picked if str(p).strip()]
