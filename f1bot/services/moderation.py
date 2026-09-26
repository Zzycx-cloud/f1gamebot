"""Bans with durations, reasons and automatic expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Ban, User
from . import adminlog

#: label -> minutes (0 = permanent)
DURATIONS: list[tuple[str, int]] = [
    ("1 hour", 60),
    ("24 hours", 24 * 60),
    ("7 days", 7 * 24 * 60),
    ("30 days", 30 * 24 * 60),
    ("Permanent", 0),
]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def sync_expired(db: Session) -> int:
    """Flip every expired ban (and the legacy flag) back to allowed."""
    now = datetime.now(timezone.utc)
    touched = 0
    for ban in db.scalars(select(Ban).where(Ban.active.is_(True), Ban.expires_at.is_not(None))):
        expires = _aware(ban.expires_at)
        if expires is not None and expires <= now:
            ban.active = False
            touched += 1
    for user in db.scalars(select(User).where(User.banned.is_(True))):
        live = db.scalar(
            select(func.count(Ban.id)).where(
                Ban.user_id == user.id,
                Ban.active.is_(True),
                or_(Ban.expires_at.is_(None), Ban.expires_at > now),
            )
        )
        if not live:
            user.banned = False
            touched += 1
    db.flush()
    return touched


def ban(
    db: Session,
    user: User,
    admin_id: int,
    minutes: int = 0,
    reason: str = "",
) -> Ban:
    now = datetime.now(timezone.utc)
    for previous in db.scalars(select(Ban).where(Ban.user_id == user.id, Ban.active.is_(True))):
        previous.active = False
    row = Ban(
        user_id=user.id,
        admin_id=int(admin_id),
        reason=(reason or "no reason given")[:160],
        created_at=now,
        expires_at=None if int(minutes) <= 0 else now + timedelta(minutes=int(minutes)),
        active=True,
    )
    db.add(row)
    user.banned = True
    db.flush()
    adminlog.log(db, admin_id, "BAN_USER", user.id, int(minutes), reason)
    return row


def unban(db: Session, user: User, admin_id: int, reason: str = "") -> int:
    cleared = 0
    for row in db.scalars(select(Ban).where(Ban.user_id == user.id, Ban.active.is_(True))):
        row.active = False
        cleared += 1
    user.banned = False
    db.flush()
    adminlog.log(db, admin_id, "UNBAN_USER", user.id, 0, reason)
    return cleared


def active_ban(db: Session, user_id: int) -> Ban | None:
    now = datetime.now(timezone.utc)
    return db.scalar(
        select(Ban)
        .where(Ban.user_id == user_id, Ban.active.is_(True))
        .where(or_(Ban.expires_at.is_(None), Ban.expires_at > now))
        .order_by(Ban.id.desc())
        .limit(1)
    )


def is_banned(db: Session, user_id: int) -> bool:
    return active_ban(db, user_id) is not None


def banned_user_ids_count(db: Session) -> int:
    sync_expired(db)
    return int(
        db.scalar(
            select(func.count(func.distinct(Ban.user_id))).where(Ban.active.is_(True))
        )
        or 0
    )


def history(db: Session, user_id: int, limit: int = 5) -> list[Ban]:
    stmt = select(Ban).where(Ban.user_id == user_id).order_by(Ban.id.desc()).limit(limit)
    return list(db.scalars(stmt))


def describe(ban: Ban | None) -> str:
    if ban is None:
        return "not banned"
    expires = _aware(ban.expires_at)
    if expires is None:
        return f"banned permanently ({ban.reason})"
    left = max(0, int((expires - datetime.now(timezone.utc)).total_seconds() // 60))
    days, rest = divmod(left, 1440)
    hours, minutes = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return f"banned for {' '.join(parts)} ({ban.reason})"
