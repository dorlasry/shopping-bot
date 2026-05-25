"""Repository layer — every database read/write lives here.

Keeping all SQL in one place means the services and handlers never touch the ORM
directly; they call intention-revealing functions like `add_items` or
`mark_item_bought`. This makes the business logic readable and the data access
easy to test or swap.

Each function takes an explicit `Session` so the caller controls the transaction
boundary (see app.db.session.get_session).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Family, Item, ItemStatus, ShoppingList, User

# --- Family / User ---------------------------------------------------------

# MVP behavior: there is a single default family that everyone joins. This makes
# a two-phone couple demo work out of the box. The Family entity + invite_code
# already exist, so the next step (real onboarding with multiple families) is a
# small extension rather than a rewrite.
_DEFAULT_FAMILY_NAME = "משפחת דמו"


def _new_invite_code() -> str:
    """Short, human-shareable code (used by onboarding in the next step)."""
    return secrets.token_hex(3).upper()  # e.g. "9F3A1C"


def get_or_create_default_family(session: Session) -> Family:
    family = session.scalars(select(Family).limit(1)).first()
    if family is None:
        family = Family(name=_DEFAULT_FAMILY_NAME, invite_code=_new_invite_code())
        session.add(family)
        session.flush()  # assign family.id without ending the transaction
        # Every family needs an active list.
        session.add(ShoppingList(family_id=family.id))
        session.flush()
    return family


def get_or_create_user(session: Session, phone_number: str, display_name: str) -> User:
    user = session.scalars(
        select(User).where(User.phone_number == phone_number)
    ).first()
    if user is not None:
        # Keep the display name fresh if WhatsApp gives us a better one.
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        return user

    family = get_or_create_default_family(session)
    user = User(
        phone_number=phone_number,
        display_name=display_name or "",
        family_id=family.id,
    )
    session.add(user)
    session.flush()
    return user


# --- Lists -----------------------------------------------------------------


def get_active_list(session: Session, family_id: int) -> ShoppingList:
    lst = session.scalars(
        select(ShoppingList)
        .where(ShoppingList.family_id == family_id, ShoppingList.is_active.is_(True))
        .limit(1)
    ).first()
    if lst is None:
        lst = ShoppingList(family_id=family_id)
        session.add(lst)
        session.flush()
    return lst


# --- Items -----------------------------------------------------------------


def add_items(
    session: Session, list_id: int, added_by_id: int, texts: list[str]
) -> list[Item]:
    """Add items, skipping ones already on the list as NEEDED (case-insensitive)."""
    existing = {
        i.text.strip().lower()
        for i in get_needed_items(session, list_id)
    }
    created: list[Item] = []
    for raw in texts:
        text = raw.strip()
        if not text or text.lower() in existing:
            continue
        item = Item(list_id=list_id, text=text, added_by_id=added_by_id)
        session.add(item)
        created.append(item)
        existing.add(text.lower())
    session.flush()
    return created


def remove_items_by_text(session: Session, list_id: int, texts: list[str]) -> list[str]:
    """Delete needed items whose text matches (case-insensitive). Returns names removed."""
    wanted = {t.strip().lower() for t in texts if t.strip()}
    removed: list[str] = []
    for item in get_needed_items(session, list_id):
        if item.text.strip().lower() in wanted:
            removed.append(item.text)
            session.delete(item)
    session.flush()
    return removed


def get_needed_items(session: Session, list_id: int) -> list[Item]:
    return list(
        session.scalars(
            select(Item)
            .where(Item.list_id == list_id, Item.status == ItemStatus.NEEDED)
            .order_by(Item.created_at)
        )
    )


def get_item(session: Session, item_id: int) -> Item | None:
    return session.get(Item, item_id)


def mark_item_bought(session: Session, item_id: int, bought_by_id: int) -> Item | None:
    item = session.get(Item, item_id)
    if item is None or item.status == ItemStatus.BOUGHT:
        return item
    item.status = ItemStatus.BOUGHT
    item.bought_by_id = bought_by_id
    item.bought_at = datetime.now(timezone.utc)
    session.flush()
    return item


def mark_items_bought_by_text(
    session: Session, list_id: int, bought_by_id: int, texts: list[str]
) -> list[str]:
    """Mark needed items bought by matching their text (case-insensitive).

    This powers the voice/text multi-mark: "קניתי חלב גבינה ולחם" marks all three
    at once. Returns the names actually marked (so the caller can confirm them).
    """
    wanted = {t.strip().lower() for t in texts if t.strip()}
    marked: list[str] = []
    for item in get_needed_items(session, list_id):
        if item.text.strip().lower() in wanted:
            item.status = ItemStatus.BOUGHT
            item.bought_by_id = bought_by_id
            item.bought_at = datetime.now(timezone.utc)
            marked.append(item.text)
    session.flush()
    return marked


def mark_all_bought(session: Session, list_id: int, bought_by_id: int) -> list[str]:
    """Mark every needed item on the list as bought (powers 'קניתי הכל').

    Returns the names marked, so the caller can confirm and celebrate.
    """
    marked: list[str] = []
    for item in get_needed_items(session, list_id):
        item.status = ItemStatus.BOUGHT
        item.bought_by_id = bought_by_id
        item.bought_at = datetime.now(timezone.utc)
        marked.append(item.text)
    session.flush()
    return marked


def clear_bought(session: Session, list_id: int) -> int:
    """Delete all bought items from the list. Returns the count removed."""
    bought = session.scalars(
        select(Item).where(Item.list_id == list_id, Item.status == ItemStatus.BOUGHT)
    ).all()
    for item in bought:
        session.delete(item)
    session.flush()
    return len(bought)


def get_family_members(session: Session, family_id: int) -> list[User]:
    return list(
        session.scalars(select(User).where(User.family_id == family_id))
    )
