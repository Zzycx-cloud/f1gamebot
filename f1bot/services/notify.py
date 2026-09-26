"""Mass messaging: weekend announcements and admin broadcasts."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import BroadcastLog, RaceEntry, User

#: key -> (label, description)
AUDIENCES: dict[str, tuple[str, str]] = {
    "all": ("👥 All Users", "every account that ever started the bot"),
    "vip": ("⭐ VIP Users", "everyone with an active VIP level"),
    "active": ("🏁 Active Users", "players that entered at least one race"),
    "one": ("🎯 Specific User", "a single player you pick"),
    "race": ("🏎️ Race entrants", "players entered in the current weekend"),
}


async def send_to_users(
    bot,
    users: list[int],
    text: str,
    markup=None,
    per_second_delay: float = 0.06,
    photo: str | None = None,
    video: str | None = None,
) -> tuple[int, int, int]:
    """Send to many chats, never raising. Returns (sent, failed, blocked)."""
    sent = failed = blocked = 0
    for chat_id in users:
        try:
            if photo:
                await bot.send_photo(chat_id, photo, caption=text, reply_markup=markup, parse_mode="HTML")
            elif video:
                await bot.send_video(chat_id, video, caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await bot.send_message(
                    chat_id,
                    text,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            sent += 1
        except Exception as exc:  # blocked / deleted / flood limited
            message = str(exc).lower()
            if "blocked" in message or "deactivated" in message or "not found" in message:
                blocked += 1
            else:
                failed += 1
        if per_second_delay:
            await asyncio.sleep(per_second_delay)
    return sent, failed, blocked


def audience(db: Session, key: str = "all", target_user: int | None = None) -> list[int]:
    """Resolve an audience key into the list of telegram ids to message."""
    if key == "race":
        race_id = target_user  # the race id is passed through target_user
        return race_participants(db, int(race_id)) if race_id else []
    stmt = select(User.id)
    if key == "vip":
        stmt = stmt.where(User.vip_level > 0)
    elif key == "active":
        stmt = stmt.where(User.races_entered > 0)
    elif key == "one":
        if target_user is None:
            return []
        stmt = stmt.where(User.id == int(target_user))
    return list(db.scalars(stmt))


def audience_count(db: Session, key: str = "all") -> int:
    stmt = select(func.count(User.id))
    if key == "vip":
        stmt = stmt.where(User.vip_level > 0)
    elif key == "active":
        stmt = stmt.where(User.races_entered > 0)
    elif key == "one":
        return 1
    return int(db.scalar(stmt) or 0)


def race_participants(db: Session, race_id: int) -> list[int]:
    return list(db.scalars(select(RaceEntry.user_id).where(RaceEntry.race_id == race_id)))


#: Backwards friendly aliases used by the race flow.
participant_chat_ids = race_participants


def owner_chat_id(db: Session, fallback: int = 0) -> int:
    """The chat to fall back on for announcements (the first admin that spoke)."""
    if fallback:
        return int(fallback)
    return int(db.scalar(select(User.id).order_by(User.id.asc()).limit(1)) or 0)


def log_broadcast(
    db: Session,
    admin_id: int,
    audience_key: str,
    text: str,
    sent: int,
    failed: int,
    blocked: int = 0,
) -> BroadcastLog:
    row = BroadcastLog(
        admin_id=int(admin_id),
        audience=audience_key[:16],
        text=(text or "")[:900],
        sent=int(sent),
        failed=int(failed),
        blocked=int(blocked),
    )
    db.add(row)
    db.flush()
    return row


def history(db: Session, limit: int = 10) -> list[BroadcastLog]:
    return list(db.scalars(select(BroadcastLog).order_by(BroadcastLog.id.desc()).limit(limit)))
