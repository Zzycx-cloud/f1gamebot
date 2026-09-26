"""Import / wiring self-check without touching the network."""

import os

os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ["DATABASE_URL"] = "sqlite:///f1_wiring_check.db"

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from f1bot.db import init_db, session
from f1bot.handlers import admin, garage, market, races, user
from f1bot.seed import seed_all
from f1bot.services.runtime import ThrottleMiddleware

init_db()
with session() as db:
    print("seed:", seed_all(db))

bot = Bot(os.environ["BOT_TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.callback_query.outer_middleware(ThrottleMiddleware())
for router in (user.router, market.router, garage.router, races.router, admin.router):
    dp.include_router(router)
print("routers ok, handlers:", sum(len(r.message.handlers) + len(r.callback_query.handlers) for r in (user.router, market.router, garage.router, races.router, admin.router)))
print("updates:", sorted(dp.resolve_used_update_types()))
print("WIRING OK")
