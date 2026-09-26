"""VIP levels, their expiry and the perks they grant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import User, VipGrant

MAX_LEVEL = 5

#: level -> (label, cash bonus % of a prize, gold back on purchase, daily bonus multiplier)
PERKS: dict[int, tuple[str, float, int, float]] = {
    1: ("VIP 1", 0.02, 0, 1.10),
    2: ("VIP 2", 0.05, 0, 1.25),
    3: ("VIP 3", 0.08, 1, 1.40),
    4: ("VIP 4", 0.12, 2, 1.60),
    5: ("VIP 5", 0.20, 5, 2.00),
}

DURATIONS: list[tuple[str, int]] = [  # (label, days) — 0 means permanent
    ("7 days", 7),
    ("30 days", 30),
    ("90 days", 90),
    ("Permanent", 0),
]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def now() -> datetime:
    return datetime.now(timezone.utc)


def active_level(user: User) -> int:
    """VIP level that is valid *right now* (0 when there is none)."""
    level = int(user.vip_level or 0)
    if level <= 0:
        return 0
    if user.vip_permanent:
        return min(level, MAX_LEVEL)
    expires = _aware(user.vip_expires_at)
    if expires is not None and expires <= now():
        return 0
    return min(level, MAX_LEVEL)


def refresh(user: User) -> int:
    """Expire a lapsed VIP in place so every screen shows the truth."""
    level = int(user.vip_level or 0)
    if level <= 0:
        return 0
    if not user.vip_permanent:
        expires = _aware(user.vip_expires_at)
        if expires is None or expires <= now():
            user.vip_level = 0
            user.vip_started_at = None
            user.vip_expires_at = None
            return 0
    return min(level, MAX_LEVEL)


def grant(
    db: Session,
    user: User,
    level: int,
    days: int,
    admin_id: int | None = None,
    permanent: bool | None = None,
) -> VipGrant:
    """Give (or upgrade) a VIP. ``days == 0`` means permanent."""
    level = max(1, min(MAX_LEVEL, int(level)))
    if permanent is None:
        permanent = int(days) <= 0
    started = user.vip_started_at if active_level(user) >= level else now()
    user.vip_level = level
    user.vip_started_at = started or now()
    user.vip_permanent = bool(permanent)
    user.vip_expires_at = None if permanent else now() + timedelta(days=max(1, int(days or 30)))
    db.flush()
    row = VipGrant(
        user_id=user.id,
        admin_id=int(admin_id or 0),
        level=level,
        days=0 if permanent else int(days or 0),
        permanent=bool(permanent),
        expires_at=user.vip_expires_at,
    )
    db.add(row)
    return row


def remove(user: User) -> None:
    user.vip_level = 0
    user.vip_started_at = None
    user.vip_expires_at = None
    user.vip_permanent = False


def label(user: User) -> str:
    level = refresh(user)
    if level == 0:
        return "No VIP"
    if user.vip_permanent:
        return f"{PERKS[level][0]} · permanent"
    expires = _aware(user.vip_expires_at)
    if expires is None:
        return PERKS[level][0]
    left = max(0, int((expires - now()).total_seconds() // 3600))
    days, hours = divmod(left, 24)
    return f"{PERKS[level][0]} · {days}d {hours}h left"


def prize_multiplier(user: User) -> float:
    level = refresh(user)
    return 1.0 + (PERKS[level][1] if level else 0.0)


def daily_multiplier(user: User) -> float:
    level = refresh(user)
    return PERKS[level][3] if level else 1.0


def gold_back(user: User) -> int:
    level = refresh(user)
    return PERKS[level][2] if level else 0


def vip_user_count(db: Session) -> int:
    """Live count of players whose VIP has not expired."""
    total = 0
    for user in db.scalars(select(User).where(User.vip_level > 0)):
        if refresh(user):
            total += 1
    return total


def vip_user_ids(db: Session) -> list[int]:
    ids = []
    for user in db.scalars(select(User).where(User.vip_level > 0)):
        if refresh(user):
            ids.append(user.id)
    return ids


def expiring(db: Session, within_days: int = 7) -> int:
    limit = now() + timedelta(days=within_days)
    stmt = select(func.count(User.id)).where(
        User.vip_level > 0,
        User.vip_permanent.is_(False),
        User.vip_expires_at.is_not(None),
        User.vip_expires_at <= limit,
    )
    return int(db.scalar(stmt) or 0)
