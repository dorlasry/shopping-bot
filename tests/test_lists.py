"""Regression tests for the business logic (handle_intent).

These exercise the same path a real (typed or voice) message takes after parsing,
by constructing the ParsedIntent directly — so no Claude call is needed.
"""

from app.db import repository as repo
from app.domain.schemas import ParsedIntent
from app.services.lists import HELP_TEXT, handle_intent


def _user(session):
    return repo.get_or_create_user(session, "972500000001", "Tester")


def _needed(session, user):
    lst = repo.get_active_list(session, user.family_id)
    return {i.text for i in repo.get_needed_items(session, lst.id)}


def test_add(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה"]))
    assert "הוספתי" in res.reply_text
    assert res.show_list is True
    assert _needed(session, user) == {"חלב", "גבינה"}


def test_add_duplicate(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב"]))
    res = handle_intent(session, user, ParsedIntent(action="add", items=["חלב"]))
    assert "לא הוספתי" in res.reply_text


def test_bought_specific(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה"]))
    res = handle_intent(session, user, ParsedIntent(action="bought", items=["חלב"]))
    assert "סימנתי שנקנו" in res.reply_text
    assert _needed(session, user) == {"גבינה"}


def test_bought_multiple(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה", "לחם"]))
    res = handle_intent(
        session, user, ParsedIntent(action="bought", items=["חלב", "לחם"])
    )
    assert "סימנתי שנקנו" in res.reply_text
    assert _needed(session, user) == {"גבינה"}


def test_bought_not_found(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="bought", items=["קקאו"]))
    assert "לא מצאתי" in res.reply_text


def test_bought_all(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה", "לחם"]))
    res = handle_intent(session, user, ParsedIntent(action="bought_all"))
    assert "הכל" in res.reply_text
    assert _needed(session, user) == set()


def test_bought_all_when_empty(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="bought_all"))
    assert "ריקה" in res.reply_text


def test_remove(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה"]))
    res = handle_intent(session, user, ParsedIntent(action="remove", items=["חלב"]))
    assert "הסרתי" in res.reply_text
    assert _needed(session, user) == {"גבינה"}


def test_remove_not_found(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="remove", items=["קקאו"]))
    assert "לא מצאתי" in res.reply_text


def test_view_empty(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="view"))
    assert "ריקה" in res.reply_text


def test_view_with_items(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב"]))
    res = handle_intent(session, user, ParsedIntent(action="view"))
    assert res.show_list is True


def test_clear(session):
    user = _user(session)
    handle_intent(session, user, ParsedIntent(action="add", items=["חלב", "גבינה"]))
    lst = repo.get_active_list(session, user.family_id)
    repo.mark_all_bought(session, lst.id, user.id)
    res = handle_intent(session, user, ParsedIntent(action="clear"))
    assert "ניקיתי" in res.reply_text


def test_help(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="help"))
    assert res.reply_text == HELP_TEXT


def test_greeting(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="greeting"))
    assert "היי" in res.reply_text


def test_unknown(session):
    user = _user(session)
    res = handle_intent(session, user, ParsedIntent(action="unknown"))
    assert "לא הבנתי" in res.reply_text
