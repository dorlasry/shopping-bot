"""Shared pytest fixtures.

Tests run against a fresh in-memory SQLite database, so they're fast, isolated,
and need no Postgres/Redis/Claude/WhatsApp. The repository and business-logic
functions all take an explicit `session`, which makes this clean to wire up.
"""

import os
import sys

# Make `app` importable when running `pytest` from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dummy env so importing any module that touches app.config never fails in tests.
os.environ.setdefault("WA_PHONE_ID", "test")
os.environ.setdefault("WA_TOKEN", "test")
os.environ.setdefault("WA_VERIFY_TOKEN", "test")
os.environ.setdefault("WA_APP_SECRET", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
