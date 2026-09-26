"""Daily bonus: one claim per configured period, streaks, random extra loot."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyReward, User
from . import store, vip, wallet


@dataclass
class Claim:
    cash: int
    gold: int
    xp: int
    bonus: str
    streak: int
    next_in_minutes: int


def seconds_left(user: User) -> int:
    last = user.last_daily_at
    if last is None:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return int(settings.daily_cooldown_hours * 3600 - elapsed)


def can_claim(user: User) -> bool:
    return seconds_left(user) <= 0


def next_in(user: User) -> str:
    left = max(0, seconds_left(user))
    hours, rest = divmod(left, 3600)
    minutes = int(rest // 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def claim(db: Session, user: User, rng: random.Random | None = None) -> Claim:
    """Pay out the daily bonus. Raises ``ValueError`` when it is too early."""
    rng = rng or random.Random()
    if not can_claim(user):
        raise ValueError(f"Already claimed. Come back in {next_in(user)}.")

    now = datetime.now(timezone.utc)
    last = user.last_daily_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is not None and (now - last) <= timedelta(hours=settings.daily_cooldown_hours * 2 + 6):
        streak = int(user.daily_streak or 0) + 1
    else:
        streak = 1

    cash = int(store.get(db, "daily_cash")) * min(3, 1 + streak // 5)
    gold = int(store.get(db, "daily_gold"))
    xp = int(store.get(db, "daily_xp"))

    multiplier = vip.daily_multiplier(user)
    cash = int(cash * multiplier)

    bonus = ""
    roll = rng.random()
    if roll < 0.15:  # random extra loot
        extra = rng.choice(
            [
                ("🪙 Gold bag", "gold", rng.randint(5, 25)),
                ("💵 Cash stack", "cash", rng.randint(2_000_000, 20_000_000)),
                ("✨ XP boost", "xp", rng.randint(50, 300)),
            ]
        )
        bonus = f"{extra[0]} +{extra[2]}"
        if extra[1] == "gold":
            gold += extra[2]
        elif extra[1] == "cash":
            cash += extra[2]
        else:
            xp += extra[2]

    if cash:
        wallet.add_cash(db, user, cash, "DAILY_BONUS", f"Day {streak} streak")
    if gold:
        wallet.add_gold(db, user, gold, "DAILY_BONUS", f"Day {streak} streak")
    user.xp = int(user.xp) + xp
    user.last_daily_at = now
    user.daily_streak = streak
    db.add(
        DailyReward(
            user_id=user.id, streak=streak, cash=cash, gold=gold, xp=xp, bonus=bonus
        )
    )
    db.flush()
    return Claim(cash=cash, gold=gold, xp=xp, bonus=bonus, streak=streak,
                 next_in_minutes=settings.daily_cooldown_hours * 60)


def history(db: Session, user_id: int, limit: int = 7) -> list[DailyReward]:
    stmt = (
        select(DailyReward)
        .where(DailyReward.user_id == user_id)
        .order_by(DailyReward.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
