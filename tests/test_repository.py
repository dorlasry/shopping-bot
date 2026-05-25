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


def test_clear_bought_removes_only_bought(session):
    user, lst = _setup(session)
    created = repo.add_items(session, lst.id, user.id, ["חלב", "גבינה"])
    repo.mark_item_bought(session, created[0].id, user.id)  # buy חלב
    count = repo.clear_bought(session, lst.id)
    assert count == 1
    assert {i.text for i in repo.get_needed_items(session, lst.id)} == {"גבינה"}


def test_two_users_share_one_family(session):
    a = repo.get_or_create_user(session, "111", "A")
    b = repo.get_or_create_user(session, "222", "B")
    # MVP: everyone joins the single default family → shared list.
    assert a.family_id == b.family_id
