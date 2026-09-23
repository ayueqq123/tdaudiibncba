"""Engine/session factory. Postgres in production (asyncpg), sqlite in tests."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


def make_engine(dsn: str, **kwargs) -> AsyncEngine:
    return create_async_engine(dsn, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# create_all only creates missing tables; these additive columns must be
# applied to databases created before the column existed.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("event_inbox", "source_sender_id", "BIGINT"),
    ("event_inbox", "source_media_kind", "VARCHAR(32)"),
)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            for table, column, ddl in _ADDITIVE_COLUMNS:
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"
                ))
