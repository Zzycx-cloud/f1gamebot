"""Entry point: python main.py"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from f1bot.config import settings
from f1bot.db import session
from f1bot.db import init_db
from f1bot.flow import start_race
from f1bot.handlers import admin, garage, market, races, user
from f1bot.seed import seed_all
from f1bot.services import races as svc
from f1bot.services.runtime import ThrottleMiddleware, set_bot, spawn_auto_start

log = logging.getLogger("f1bot")


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Unhandled error: %s", event.exception)
    if event.update.callback_query is not None and event.update.callback_query.id:
        try:
            await event.update.callback_query.answer("Something broke. Try again.", show_alert=True)
        except Exception:
            pass
    return True


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.is_configured:
        raise SystemExit("Set BOT_TOKEN in .env before starting the bot.")

    init_db()
    with session() as db:
        created = seed_all(db)
        open_race = svc.current_race(db)
    log.info(
        "Database ready (new: %s teams, %s drivers, %s calendar rounds)",
        created["teams"],
        created["drivers"],
        created["rounds"],
    )

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    set_bot(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(ThrottleMiddleware())
    dp.errors.register(on_error)
    for router in (user.router, market.router, garage.router, races.router, admin.router):
        dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    log.info("Logged in as @%s (id %s)", me.username, me.id)

    if open_race is not None and open_race.status == "open":
        log.info("Resuming auto-start timer for weekend R%s", open_race.round_no)
        spawn_auto_start(max(60, settings.auto_start_minutes * 60), start_race, open_race.id)

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        print(exc)
