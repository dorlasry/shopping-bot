"""One-off: create (or update) the past-items Flow in your WhatsApp account.

Run once, then put the printed flow id in WA_PAST_ITEMS_FLOW_ID.

    python scripts/setup_flow.py                # create a new draft flow
    python scripts/setup_flow.py --update FLOW  # push the JSON to an existing flow

The flow is created as a DRAFT so it can be edited freely; publishing is a
separate, deliberate step once you are happy with it.
"""

from __future__ import annotations

import argparse

from pywa import WhatsApp

from app.config import settings
from app.services.flows import build_flow_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", metavar="FLOW_ID", help="update an existing flow")
    args = parser.parse_args()

    wa = WhatsApp(phone_id=settings.wa_phone_id, token=settings.wa_token)
    flow_json = build_flow_json()

    if args.update:
        result = wa.update_flow_json(flow_id=args.update, flow_json=flow_json)
        print(f"updated flow {args.update}: {result}")
        return

    created = wa.create_flow(
        name="past-items",
        categories=["OTHER"],
        flow_json=flow_json,
    )
    print(f"created flow: {created.id}")
    print(f"set WA_PAST_ITEMS_FLOW_ID={created.id}")


if __name__ == "__main__":
    main()
