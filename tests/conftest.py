"""Shared pytest setup: one throw-away SQLite database for the whole session."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_DB = Path(tempfile.gettempdir()) / "f1_bot_pytest.db"
if _DB.exists():
    _DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["ADMIN_IDS"] = "1"
os.environ["LIVE_BROADCAST"] = "no"
os.environ["LIVE_DELAY"] = "0"
os.environ["BOT_TOKEN"] = "123:TEST"

import pytest  # noqa: E402

from f1bot.config import settings  # noqa: E402

object.__setattr__(settings, "live_enabled", True)
object.__setattr__(settings, "live_delay", 0.0)


def clear_weekends() -> None:
    from f1bot.db import session
    from f1bot.models import Race, RaceEntry

    with session() as db:
        dead_ids = [
            rid
            for (rid,) in db.query(Race.id).filter(Race.status != "finished").all()
        ]
        if dead_ids:
            db.query(RaceEntry).filter(RaceEntry.race_id.in_(dead_ids)).delete(
                synchronize_session=False
            )
        db.query(Race).filter(Race.status != "finished").delete(synchronize_session=False)


def sign_driver(db, user, code: str, slot: int) -> None:
    """Sign driver ``code`` into ``slot`` for ``user``, freeing him from any other owner."""
    from sqlalchemy import or_

    from f1bot.models import Driver, User
    from f1bot.services import economy

    driver = db.query(Driver).filter(Driver.code == code).one()
    if getattr(user, f"driver{slot}_id") == driver.id:
        return
    holders = db.query(User).filter(
        or_(User.driver1_id == driver.id, User.driver2_id == driver.id)
    ).all()
    for holder in holders:
        if holder.id != user.id:
            economy.sell_driver(db, holder, driver.id)
    if getattr(user, f"driver{slot}_id") == driver.id:
        return
    if getattr(user, "driver1_id") is None and slot == 2:
        slot = 1
    economy.buy_driver(db, user, driver.id, slot)


def buy_team_free(db, user, code: str):
    """Buy constructor ``code`` for ``user``, taking it from any other holder."""
    from f1bot.models import Team, User
    from f1bot.services import economy

    team = db.query(Team).filter(Team.code == code).one()
    if user.team_id == team.id:
        return team
    for holder in db.query(User).filter(User.team_id == team.id).all():
        if holder.id != user.id:
            economy.sell_team(db, holder, team.id)
    if user.team_id == team.id:
        return team
    return economy.buy_team(db, user, team.id)


@pytest.fixture(scope="session", autouse=True)
def database():
    from f1bot.db import init_db, session
    from f1bot.seed import seed_all

    init_db()
    with session() as db:
        seed_all(db)
    yield
