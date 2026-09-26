"""Database engine, session factory and small helpers.

``init_db()`` creates missing tables *and* adds missing columns to tables that
already exist, so the game can grow new fields without a migration framework.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from .config import BASE_DIR, settings
from .models import Base, User

_url = settings.database_url
_kwargs: dict = {"future": True, "pool_pre_ping": True}
if _url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
    _kwargs.pop("pool_pre_ping", None)

engine = create_engine(_url, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _sql_type(column) -> str:
    """Compile a SQLAlchemy column type into raw SQL for the active dialect."""
    return column.type.compile(engine.dialect)


def _add_missing_columns(conn) -> list[str]:
    """ALTER TABLE ... ADD COLUMN for every mapped column that is not there yet."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all() is about to build the whole table
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            spec = [f'"{column.name}"', _sql_type(column)]
            default = column.default
            if column.server_default is not None:
                spec.append(f"DEFAULT {column.server_default.arg}")
            elif default is not None and default.is_scalar:
                value = default.arg
                if isinstance(value, bool):
                    spec.append(f"DEFAULT {1 if value else 0}")
                elif isinstance(value, (int, float)):
                    spec.append(f"DEFAULT {value}")
                elif isinstance(value, str):
                    spec.append("DEFAULT '" + value.replace("'", "''") + "'")
            elif not column.nullable:
                spec.append("DEFAULT ''")  # keep strict databases happy on ALTER
            conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {" ".join(spec)}'))
            added.append(f"{table.name}.{column.name}")
    return added


def init_db() -> list[str]:
    """Create all tables / columns. Safe to call on every start."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        return _add_missing_columns(conn)


@contextmanager
def session() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_user(db: Session, user_id: int, username: str = "", first_name: str = "") -> User:
    """Load a player, creating him with the starting budget on first contact."""
    user = db.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=username or "",
            first_name=first_name or "",
            balance=settings.starting_cash,
            gold=settings.starting_gold,
        )
        db.add(user)
        db.flush()
    else:
        if username and user.username != username:
            user.username = username
        if first_name and user.first_name != first_name:
            user.first_name = first_name
    return user


def active_race_id(db: Session) -> int | None:
    """Id of the race weekend that is currently open, paused or live."""
    from .models import Race

    return db.scalar(
        select(Race.id)
        .where(Race.status.in_(("open", "paused", "live")))
        .order_by(Race.id.desc())
        .limit(1)
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
