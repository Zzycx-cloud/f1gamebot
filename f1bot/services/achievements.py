"""Achievements: defined declaratively, unlocked from real database stats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Achievement, User, UserAchievement

#: code -> (icon, name, description, target, reward_cash, reward_gold, reader)
DEFS: list[tuple[str, str, str, str, int, int, int, Callable[[User], int]]] = [
    ("first_race", "🏁", "First Race", "Finish your first race weekend", 1, 0, 1_000_000, lambda u: u.races_entered),
    ("first_win", "🥇", "First Win", "Win a race", 1, 0, 5_000_000, lambda u: u.wins),
    ("wins_10", "🏆", "10 Wins", "Win 10 races", 10, 0, 50_000_000, lambda u: u.wins),
    ("podiums_5", "🔥", "5 Podiums", "Stand on the podium 5 times", 5, 0, 20_000_000, lambda u: u.podiums),
    ("earn_100m", "💰", "Earn $100M", "Earn $100M in total", 100_000_000, 0, 0, lambda u: u.total_earnings),
    ("earn_1b", "💎", "Earn $1B", "Earn $1B in total", 1_000_000_000, 0, 0, lambda u: u.total_earnings),
    ("rain_win", "🌧️", "Rainmaster", "Win a race in the rain", 1, 0, 10, lambda u: u.races_rained_wins),
    ("fastest_lap", "⚡", "Fastest Lap", "Set a fastest lap", 1, 0, 2_000_000, lambda u: u.fastest_laps),
    ("races_100", "🏎️", "100 Races", "Enter 100 race weekends", 100, 0, 100_000_000, lambda u: u.races_entered),
    ("champion", "👑", "Champion", "Win a championship", 1, 0, 250_000_000, lambda u: u.titles),
    ("pole_position", "⏱️", "Pole Position", "Start a race from pole", 1, 0, 3_000_000, lambda u: u.poles),
    ("first_gold", "🪙", "Gold Rush", "Hold 100 gold", 100, 0, 0, lambda u: u.gold),
    ("vip_club", "⭐", "VIP Club", "Reach VIP 1", 1, 0, 0, lambda u: u.vip_level),
    ("points_100", "📊", "Century", "Score 100 championship points", 100, 0, 10_000_000, lambda u: u.race_points),
]

BY_CODE = {row[0]: row for row in DEFS}


def sync_catalog(db: Session) -> int:
    """Make sure every achievement definition exists in the database."""
    created = 0
    for code, icon, name, description, target, cash, gold, _reader in DEFS:
        if db.scalar(select(Achievement).where(Achievement.code == code)) is None:
            db.add(
                Achievement(
                    code=code,
                    icon=icon,
                    name=name,
                    description=description,
                    target=int(target),
                    reward_cash=int(cash),
                    reward_gold=int(gold),
                )
            )
            created += 1
    db.flush()
    return created


def owned_codes(db: Session, user_id: int) -> set[str]:
    return set(db.scalars(select(UserAchievement.achievement_code).where(UserAchievement.user_id == user_id)))


def check(db: Session, user: User) -> list[str]:
    """Unlock everything the player's stored stats already qualify for.

    Returns the newly unlocked achievement names (rewards are paid out).
    """
    from . import wallet as wallet_svc

    have = owned_codes(db, user.id)
    rows = list(db.scalars(select(Achievement)))
    unlocked: list[str] = []
    for row in rows:
        if row.code in have:
            continue
        definition = BY_CODE.get(row.code)
        if definition is None:
            continue
        reader = definition[7]
        try:
            value = int(reader(user))
        except Exception:
            continue
        if value < int(row.target):
            continue
        db.add(UserAchievement(user_id=user.id, achievement_code=row.code))
        have.add(row.code)
        if row.reward_cash:
            wallet_svc.add_cash(db, user, row.reward_cash, "ACHIEVEMENT", f"{row.name} reward")
        if row.reward_gold:
            wallet_svc.add_gold(db, user, row.reward_gold, "ACHIEVEMENT", f"{row.name} reward")
        unlocked.append(f"{row.icon} {row.name}")
    db.flush()
    return unlocked


def check_all(db: Session) -> list[tuple[int, list[str]]]:
    """Run :func:`check` for every player; returns (user_id, unlocked titles)."""
    out: list[tuple[int, list[str]]] = []
    for user in db.scalars(select(User)):
        unlocked = check(db, user)
        if unlocked:
            out.append((user.id, unlocked))
    return out


def title(code: str) -> str:
    definition = BY_CODE.get(code)
    return f"{definition[1]} {definition[2]}" if definition else code


def progress_rows(db: Session, user: User) -> list[tuple[str, str, str, int, int, bool]]:
    """(icon, name, description, value, target, unlocked) for the achievements screen."""
    have = owned_codes(db, user.id)
    out = []
    for row in db.scalars(select(Achievement).order_by(Achievement.id)):
        definition = BY_CODE.get(row.code)
        value = 0
        if definition is not None:
            try:
                value = int(definition[7](user))
            except Exception:
                value = 0
        out.append(
            (row.icon, row.name, row.description, value, int(row.target), row.code in have)
        )
    return out
