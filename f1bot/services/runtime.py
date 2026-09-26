"""Runtime helpers: shared bot reference, anti-flood middleware, background jobs."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, MutableMapping

from aiogram import Bot
from aiogram.types import CallbackQuery, TelegramObject

from ..config import settings

_bot: Bot | None = None
_races_started: set[int] = set()


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> Bot | None:
    return _bot


# --------------------------------------------------------------------------- #
# Anti-flood: token bucket per user
# --------------------------------------------------------------------------- #
class ThrottleMiddleware:
    """Simple per-user token bucket to protect the bot from button spam."""

    def __init__(self) -> None:
        self._buckets: dict[int, list[float]] = {}

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        window = [t for t in self._buckets.get(user_id, []) if now - t < 60.0]
        if len(window) >= max(3, settings.max_actions_per_minute):
            self._buckets[user_id] = window
            return False
        window.append(now)
        self._buckets[user_id] = window
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        user = event.from_user
        if user is None or settings.is_admin(user.id):
            return await handler(event, data)
        if self._is_banned(user.id):
            await event.answer("🚫 Your account is suspended. Contact the admin.", show_alert=True)
            return None
        if not self.allow(user.id):
            await event.answer("⏳ Too many clicks, slow down a little.", show_alert=True)
            return None
        return await handler(event, data)

    @staticmethod
    def _is_banned(user_id: int) -> bool:
        from ..db import session
        from ..models import User

        try:
            with session() as db:
                player = db.get(User, user_id)
                return bool(player and player.banned)
        except Exception:
            return False


# --------------------------------------------------------------------------- #
# Background race jobs
# --------------------------------------------------------------------------- #
def race_already_handled(race_id: int) -> bool:
    return race_id in _races_started


def mark_race_handled(race_id: int) -> None:
    _races_started.add(race_id)
    if len(_races_started) > 500:
        _races_started.clear()
        _races_started.add(race_id)


def clear_race_handled(race_id: int) -> None:
    """Allow a restarted weekend to be started again."""
    _races_started.discard(race_id)


async def schedule_auto_start(delay_seconds: int, start_callable: Callable[[int], Awaitable[Any]], race_id: int) -> None:
    """Auto-start an untouched weekend so the lobby never stalls forever."""
    if delay_seconds <= 0:
        return
    try:
        await asyncio.sleep(delay_seconds)
        if race_already_handled(race_id):
            return
        await start_callable(race_id)
    except asyncio.CancelledError:  # pragma: no cover
        raise
    except Exception:
        pass


def spawn_auto_start(delay_seconds: int, start_callable: Callable[[int], Awaitable[Any]], race_id: int):
    if delay_seconds <= 0:
        return None
    return asyncio.create_task(schedule_auto_start(delay_seconds, start_callable, race_id))
