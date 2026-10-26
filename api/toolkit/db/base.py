"""Declarative base and column helpers."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


def one_of(column: str, values: Iterable[str], name: str | None = None, nullable: bool = False) -> CheckConstraint:
    """CHECK constraint used instead of native PG enums so new values need no type migration."""
    quoted = ", ".join(f"'{v}'" for v in values)
    expr = f'"{column}" IN ({quoted})'
    if nullable:
        expr = f'"{column}" IS NULL OR {expr}'
    return CheckConstraint(expr, name=name or f"{column}_enum")
