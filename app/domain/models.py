"""SQLAlchemy ORM models.

Entities:
  Family        a shared unit (a couple, a household). Has an invite_code so the
                NEXT step (onboarding: create/join a family) drops in cleanly.
  User          a person, identified by WhatsApp phone number, belongs to a Family.
  ShoppingList  one active list per family for the MVP.
  Item          a line on a list: text + status (needed/bought) + audit fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ItemStatus(str, Enum):
    NEEDED = "needed"
    BOUGHT = "bought"


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="המשפחה שלנו")
    # Reserved for onboarding (next step). Unique short code partners use to join.
    invite_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list[User]] = relationship(back_populates="family")
    lists: Mapped[list[ShoppingList]] = relationship(back_populates="family")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    family: Mapped[Family] = relationship(back_populates="members")


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"))
    name: Mapped[str] = mapped_column(String(100), default="הרשימה שלנו")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    family: Mapped[Family] = relationship(back_populates="lists")
    items: Mapped[list[Item]] = relationship(
        back_populates="list", cascade="all, delete-orphan"
    )


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("shopping_lists.id"))
    text: Mapped[str] = mapped_column(String(200))
    status: Mapped[ItemStatus] = mapped_column(
        SAEnum(ItemStatus, name="item_status"), default=ItemStatus.NEEDED
    )

    # Audit: who added it, who bought it. Both point at users; we keep them as
    # plain FKs (no relationship) to avoid ambiguous-join configuration for the MVP.
    added_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    bought_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Reserved for the smart-categorization feature (e.g. "חלב" -> dairy).
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    bought_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    list: Mapped[ShoppingList] = relationship(back_populates="items")
