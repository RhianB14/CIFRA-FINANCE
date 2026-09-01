import uuid
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.core.settings import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

SCOPE_KEY = "cifra_auth_scope"
USER_KEY = "cifra_user_id"

_BIND_SQL = text(
    "SELECT set_config('app.current_user_id', :value, true), set_config('app.auth_scope', '', true)"
)
_SCOPE_SQL = text("SELECT set_config('app.auth_scope', :value, true)")


def _apply_session_scope(session: Session, connection: object) -> None:
    user_id = session.info.get(USER_KEY)
    scope = session.info.get(SCOPE_KEY, "")
    if user_id:
        _driver_sql(
            connection,
            "SELECT set_config('app.current_user_id', '"
            + str(user_id)
            + "', true), set_config('app.auth_scope', '', true)",
        )
    else:
        _driver_sql(
            connection,
            "SELECT set_config('app.auth_scope', '" + str(scope) + "', true)",
        )


def _on_after_begin(session: Session, transaction: object, connection: object) -> None:
    _apply_session_scope(session, connection)


def _driver_sql(connection: object, statement: str) -> None:
    apply = getattr(connection, "exec_driver_sql", None)
    if apply is not None:
        apply(statement)


event.listen(Session, "after_begin", _on_after_begin)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            connect_args={"server_settings": {"role": "cifra_app"}},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def bind_current_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.info[USER_KEY] = str(user_id)
    session.info[SCOPE_KEY] = ""
    if session.in_transaction():
        await session.execute(_BIND_SQL, {"value": str(user_id)})


async def set_bypass_scope(session: AsyncSession) -> None:
    session.info[SCOPE_KEY] = "bypass"
    if session.in_transaction():
        await session.execute(_SCOPE_SQL, {"value": "bypass"})


async def clear_bypass_scope(session: AsyncSession) -> None:
    session.info[SCOPE_KEY] = ""
    if session.in_transaction():
        await session.execute(_SCOPE_SQL, {"value": ""})


async def dispose_engine() -> None:
    global _engine
    global _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
