"""Real statistics — every number here is aggregated from the database."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Ban,
    Championship,
    Driver,
    Purchase,
    Race,
    RaceEntry,
    Result,
    Team,
    Transaction,
    User,
    UserAchievement,
)
from . import vip


def player_stats(db: Session, user: User) -> dict:
    """Everything the profile / statistics screens show, read live from the DB."""
    races = int(user.races_entered or 0)
    wins = int(user.wins or 0)
    wins_in_races = int(
        db.scalar(
            select(func.count(Result.id)).where(
                Result.user_id == user.id, Result.position == 1, Result.dnf.is_(False)
            )
        )
        or 0
    )
    dnfs = int(user.dnfs or 0)
    finished = int(
        db.scalar(
            select(func.count(Result.id)).where(
                Result.user_id == user.id, Result.dnf.is_(False)
            )
        )
        or 0
    )
    starts = int(db.scalar(select(func.count(Result.id)).where(Result.user_id == user.id)) or 0)
    earned = int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user.id,
                Transaction.currency == "cash",
                Transaction.amount > 0,
            )
        )
        or 0
    )
    spent = int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user.id,
                Transaction.currency == "cash",
                Transaction.amount < 0,
            )
        )
        or 0
    )
    best = int(
        db.scalar(
            select(func.min(Result.position)).where(Result.user_id == user.id, Result.dnf.is_(False))
        )
        or 0
    )
    win_rate = round(100.0 * wins_in_races / starts, 1) if starts else 0.0
    finish_rate = round(100.0 * finished / starts, 1) if starts else 0.0
    achievements = int(
        db.scalar(
            select(func.count(UserAchievement.id)).where(UserAchievement.user_id == user.id)
        )
        or 0
    )
    return {
        "races": starts or races,
        "entered": races,
        "wins": wins_in_races or wins,
        "podiums": int(user.podiums or 0),
        "dnfs": dnfs,
        "poles": int(user.poles or 0),
        "fastest_laps": int(user.fastest_laps or 0),
        "points": int(user.race_points or 0),
        "titles": int(user.titles or 0),
        "gold": int(user.gold or 0),
        "achievements": achievements,
        "earnings": earned,
        "spending": abs(spent),
        "win_rate": win_rate,
        "finish_rate": finish_rate,
        "best_finish": best,
        "rating": rating(user),
        "xp": int(user.xp or 0),
        "level": 1 + int(user.xp or 0) // 500,
    }


def rating(user: User) -> int:
    """0-100 player rating derived from results actually achieved."""
    starts = max(1, int(user.races_entered or 0))
    score = 40.0
    score += min(25.0, (user.wins or 0) * 2.5)
    score += min(15.0, (user.podiums or 0) * 1.0)
    score += min(10.0, (user.race_points or 0) / 40.0)
    score += min(5.0, (user.fastest_laps or 0) * 0.5)
    score += min(5.0, (user.poles or 0) * 0.5)
    return int(max(1, min(100, round(score))))


def global_stats(db: Session) -> dict:
    now = vip.now()
    active_users = int(
        db.scalar(
            select(func.count(User.id)).where(User.races_entered > 0, User.banned.is_(False))
        )
        or 0
    )
    banned = int(
        db.scalar(
            select(func.count(func.distinct(Ban.user_id))).where(
                Ban.active.is_(True),
                (Ban.expires_at.is_(None)) | (Ban.expires_at > now),
            )
        )
        or 0
    )
    championships = Championship  # referenced so the table is exercised by callers
    total_cash = int(db.scalar(select(func.coalesce(func.sum(User.balance), 0))) or 0)
    return {
        "users": int(db.scalar(select(func.count(User.id))) or 0),
        "active": active_users,
        "active_users": active_users,
        "banned": banned,
        "banned_users": banned,
        "races": int(db.scalar(select(func.count(Race.id))) or 0),
        "races_total": int(db.scalar(select(func.count(Race.id))) or 0),
        "finished": int(db.scalar(select(func.count(Race.id)).where(Race.status == "finished")) or 0),
        "races_completed": int(
            db.scalar(select(func.count(Race.id)).where(Race.status == "finished")) or 0
        ),
        "races_active": int(
            db.scalar(select(func.count(Race.id)).where(Race.status.in_(("open", "paused", "live"))))
            or 0
        ),
        "entries": int(db.scalar(select(func.count(RaceEntry.id))) or 0),
        "results": int(db.scalar(select(func.count(Result.id))) or 0),
        "teams": int(db.scalar(select(func.count(Team.id))) or 0),
        "drivers": int(db.scalar(select(func.count(Driver.id))) or 0),
        "total_cash": total_cash,
        "cash_in_circulation": total_cash,
        "total_gold": int(db.scalar(select(func.coalesce(func.sum(User.gold), 0))) or 0),
        "prizes": int(
            db.scalar(
                select(func.coalesce(func.sum(Result.prize), 0))
            )
            or 0
        ),
        "vip": int(
            db.scalar(
                select(func.count(User.id)).where(
                    User.vip_level > 0,
                    (User.vip_permanent.is_(True))
                    | (User.vip_expires_at.is_(None))
                    | (User.vip_expires_at > now),
                )
            )
            or 0
        ),
        "vip_users": int(
            db.scalar(
                select(func.count(User.id)).where(
                    User.vip_level > 0,
                    (User.vip_permanent.is_(True))
                    | (User.vip_expires_at.is_(None))
                    | (User.vip_expires_at > now),
                )
            )
            or 0
        ),
        "championships": int(db.scalar(select(func.count(championships.id))) or 0),
        "transactions": int(db.scalar(select(func.count(Transaction.id))) or 0),
        "purchases": int(db.scalar(select(func.count(Purchase.id))) or 0),
    }
