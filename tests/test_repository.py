"""Regression tests for the repository (data-access) layer."""

from app.db import repository as repo
from app.domain.models import ItemStatus


def _setup(session):
    user = repo.get_or_create_user(session, "972500000001", "Tester")
    lst = repo.get_active_list(session, user.family_id)
    return user, lst


def test_add_items_and_dedup(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב", "גבינה"])
    assert [i.text for i in created] == ["חלב", "גבינה"]

    # Adding חלב again must not create a duplicate.
    again = repo.add_items(session, lst.id, user.id, ["חלב"])
    assert again == []
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"חלב", "גבינה"}


def test_remove_items_by_text(session):
    user, lst = _setup(session)
    repo.add_items(session, lst.id, user.id, ["חלב", "גבינה"])
    removed = repo.remove_items_by_text(session, lst.id, ["חלב"])
    assert removed == ["חלב"]
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"גבינה"}


def test_mark_item_bought_single(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב"])
    item = repo.mark_item_bought(session, created[0].id, user.id)
    assert item is not None and item.status == ItemStatus.BOUGHT
    assert item.bought_by_id == user.id
    assert repo.get_needed_items(session, lst.id) == []


def test_mark_items_bought_by_text(session):
    user, lst = _setup(session)
    repo.add_items(session, lst.id, user.id, ["חלב", "גבינה", "לחם"])
    marked = repo.mark_items_bought_by_text(session, lst.id, user.id, ["חלב", "לחם"])
    assert set(marked) == {"חלב", "לחם"}
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"גבינה"}


def test_mark_all_bought(session):
    user, lst = _setup(session)
    repo.add_items(session, lst.id, user.id, ["חלב", "גבינה", "לחם"])
    marked = repo.mark_all_bought(session, lst.id, user.id)
    assert set(marked) == {"חלב", "גבינה", "לחם"}
    assert repo.get_needed_items(session, lst.id) == []


def test_clear_bought_counts_only_bought(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב", "גבינה"])
    repo.mark_item_bought(session, created[0].id, user.id)  # buy חלב
    count = repo.clear_bought(session, lst.id)
    assert count == 1
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"גבינה"}


def test_clear_bought_keeps_items_as_history(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב"])
    repo.mark_item_bought(session, created[0].id, user.id)

    repo.clear_bought(session, lst.id)

    # The row survives (it is purchase history now), but is marked cleared.
    item = repo.get_item(session, created[0].id)
    assert item is not None
    assert item.cleared is True


def test_clear_bought_is_idempotent(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב"])
    repo.mark_item_bought(session, created[0].id, user.id)

    assert repo.clear_bought(session, lst.id) == 1
    assert repo.clear_bought(session, lst.id) == 0


def test_two_users_share_one_family(session):
    a = repo.get_or_create_user(session, "111", "A")
    b = repo.get_or_create_user(session, "222", "B")
    # MVP: everyone joins the single default family → shared list.
    assert a.family_id == b.family_id


def _buy(session, user, lst, text, days_ago):
    """Add an item and mark it bought `days_ago` days ago."""
    from datetime import UTC, datetime, timedelta

    from app.domain.models import Item, ItemStatus

    item = Item(list_id=lst.id, text=text, added_by_id=user.id)
    item.status = ItemStatus.BOUGHT
    item.bought_by_id = user.id
    item.bought_at = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(item)
    session.flush()
    return item


def test_past_items_most_recent_first(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    _buy(session, user, lst, "גבינה", days_ago=5)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב", "גבינה"]


def test_past_items_deduplicates_by_text(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=9)
    _buy(session, user, lst, "גבינה", days_ago=5)
    _buy(session, user, lst, "חלב", days_ago=1)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב", "גבינה"]


def test_past_items_ignores_never_bought(session):
    user, lst = _setup(session)
    repo.add_items(session, lst.id, user.id, ["לחם"])
    _buy(session, user, lst, "חלב", days_ago=1)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב"]


def test_past_items_includes_cleared(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    repo.clear_bought(session, lst.id)

    assert repo.get_past_bought_items(session, user.family_id) == ["חלב"]


def test_past_items_excludes_given_texts(session):
    user, lst = _setup(session)
    _buy(session, user, lst, "חלב", days_ago=1)
    _buy(session, user, lst, "גבינה", days_ago=5)

    result = repo.get_past_bought_items(session, user.family_id, exclude_texts=[" ChLv ", "חלב"])
    assert result == ["גבינה"]


def test_past_items_respects_limit(session):
    user, lst = _setup(session)
    for day, text in enumerate(["א", "ב", "ג"], start=1):
        _buy(session, user, lst, text, days_ago=day)

    assert repo.get_past_bought_items(session, user.family_id, limit=2) == ["א", "ב"]
