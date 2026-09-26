"""Transfer market, garage upgrades and the player's roster.

Money never moves directly — everything goes through :mod:`f1bot.services.wallet`
so each purchase leaves a transaction and a purchase record behind.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Car, CarUpgrade, Driver, DriverUpgrade, Team, User, UserDriver, UserTeam
from ..seed import driver_price, driver_salary
from . import achievements, moderation, store, wallet
from .wallet import NotEnoughFunds

__all__ = ["NotEnoughFunds"]


# --------------------------------------------------------------------------- #
# Roster
# --------------------------------------------------------------------------- #
def get_team(db: Session, user: User) -> Team | None:
    return db.get(Team, user.team_id) if user.team_id else None


def get_drivers(db: Session, user: User) -> list[Driver]:
    ids = [i for i in (user.driver1_id, user.driver2_id) if i]
    return [d for d in (db.get(Driver, i) for i in ids) if d is not None]


def roster_value(db: Session, user: User) -> int:
    total = 0
    for row in db.scalars(select(UserTeam).where(UserTeam.user_id == user.id)):
        total += row.price_paid
    for row in db.scalars(select(UserDriver).where(UserDriver.user_id == user.id)):
        total += row.price_paid
    return int(total)


def is_banned(db: Session, user_id: int) -> bool:
    return moderation.is_banned(db, user_id)


# --------------------------------------------------------------------------- #
# Market listings
# --------------------------------------------------------------------------- #
def owned_team_ids(db: Session) -> set[int]:
    return {row for row in db.scalars(select(UserTeam.team_id))}


def owned_driver_ids(db: Session) -> set[int]:
    return {row for row in db.scalars(select(UserDriver.driver_id))}


def market_teams(db: Session, page: int = 0, size: int = 8) -> tuple[list[Team], int]:
    rows = list(
        db.scalars(
            select(Team).where(Team.active.is_(True)).order_by(Team.rating.desc(), Team.price.desc())
        )
    )
    owned = owned_team_ids(db)
    free = [t for t in rows if t.id not in owned]
    pages = max(1, -(-len(free) // size))
    page = max(0, min(page, pages - 1))
    return free[page * size : (page + 1) * size], pages


def market_drivers(
    db: Session, page: int = 0, size: int = 8, sort: str = "pace"
) -> tuple[list[Driver], int]:
    order = Driver.overall.desc() if sort == "pace" else Driver.price.asc()
    rows = list(
        db.scalars(select(Driver).where(Driver.active.is_(True)).order_by(order, Driver.id.asc()))
    )
    owned = owned_driver_ids(db)
    free = [d for d in rows if d.id not in owned]
    pages = max(1, -(-len(free) // size))
    page = max(0, min(page, pages - 1))
    return free[page * size : (page + 1) * size], pages


def all_drivers(db: Session, page: int = 0, size: int = 8) -> tuple[list[Driver], int]:
    rows = list(db.scalars(select(Driver).order_by(Driver.overall.desc(), Driver.id.asc())))
    pages = max(1, -(-len(rows) // size))
    page = max(0, min(page, pages - 1))
    return rows[page * size : (page + 1) * size], pages


def all_teams(db: Session, page: int = 0, size: int = 8) -> tuple[list[Team], int]:
    rows = list(db.scalars(select(Team).order_by(Team.rating.desc(), Team.id.asc())))
    pages = max(1, -(-len(rows) // size))
    page = max(0, min(page, pages - 1))
    return rows[page * size : (page + 1) * size], pages


def free_slots(user: User) -> list[int]:
    slots = []
    if user.driver1_id is None:
        slots.append(1)
    if user.driver2_id is None:
        slots.append(2)
    return slots


def assert_not_banned(db: Session, user: User) -> None:
    if moderation.is_banned(db, user.id):
        raise ValueError("🚫 Your account is suspended.")


# --------------------------------------------------------------------------- #
# Buying / selling
# --------------------------------------------------------------------------- #
def buy_team(db: Session, user: User, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if team is None or not team.active:
        raise ValueError("This constructor is not on the market.")
    if team.id in owned_team_ids(db):
        raise ValueError("This team is already owned by somebody.")
    if user.team_id == team.id:
        raise ValueError("You already run this team.")
    assert_not_banned(db, user)
    if int(user.balance) < team.price:
        raise ValueError(f"Not enough money. {team.name} costs {team.price:,}.")

    wallet.spend_cash(db, user, team.price, "BUY_TEAM", team.name)
    user.team_id = team.id
    db.add(UserTeam(user_id=user.id, team_id=team.id, price_paid=team.price))
    wallet.log_purchase(db, user, "team", f"team:{team.id}", team.name, team.price)
    db.flush()
    refresh_car(db, user)
    achievements.check(db, user)
    return team


def buy_driver(db: Session, user: User, driver_id: int, slot: int) -> Driver:
    driver = db.get(Driver, driver_id)
    if driver is None or not driver.active:
        raise ValueError("This driver is not on the market.")
    if driver.id in owned_driver_ids(db):
        raise ValueError("This driver already has a contract.")
    assert_not_banned(db, user)
    if int(user.balance) < driver.price:
        raise ValueError(f"Not enough money. {driver.name} costs {driver.price:,}.")
    if slot not in (1, 2):
        raise ValueError("Choose the race seat: slot 1 or 2.")
    if slot == 2 and user.driver1_id is None:
        raise ValueError("Fill the first race seat before signing a second driver.")

    wallet.spend_cash(db, user, driver.price, "BUY_DRIVER", driver.name)
    if slot == 1:
        user.driver1_id = driver.id
    else:
        user.driver2_id = driver.id
    db.add(UserDriver(user_id=user.id, driver_id=driver.id, price_paid=driver.price))
    wallet.log_purchase(db, user, "driver", f"driver:{driver.id}", driver.name, driver.price)
    db.flush()
    achievements.check(db, user)
    return driver


def sell_driver(db: Session, user: User, driver_id: int) -> int:
    row = db.scalar(
        select(UserDriver).where(UserDriver.user_id == user.id, UserDriver.driver_id == driver_id)
    )
    if row is None:
        raise ValueError("You do not own this driver.")
    payout = int(row.price_paid * store.sell_ratio(db))
    driver = db.get(Driver, driver_id)
    wallet.add_cash(db, user, payout, "SELL_DRIVER", driver.name if driver else "")
    if user.driver1_id == driver_id:
        user.driver1_id = None
    if user.driver2_id == driver_id:
        user.driver2_id = None
    db.delete(row)
    db.flush()
    return payout


def sell_team(db: Session, user: User, team_id: int) -> int:
    row = db.scalar(select(UserTeam).where(UserTeam.user_id == user.id, UserTeam.team_id == team_id))
    if row is None:
        raise ValueError("You do not own this constructor.")
    payout = int(row.price_paid * store.sell_ratio(db))
    team = db.get(Team, team_id)
    wallet.add_cash(db, user, payout, "SELL_TEAM", team.name if team else "")
    db.delete(row)
    if user.team_id == team_id:
        user.team_id = None
    db.flush()
    refresh_car(db, user)
    return payout


# --------------------------------------------------------------------------- #
# Car development
# --------------------------------------------------------------------------- #
UPGRADES: dict[str, tuple[str, str]] = {
    "engine": ("⚡ Engine", "top speed and straight-line pace"),
    "aero": ("🌬️ Aerodynamics", "cornering speed and tyre wear"),
    "tires": ("🛞 Tires", "slower tyre degradation over a stint"),
    "reliability": ("🔧 Reliability", "fewer mechanical retirements"),
    "fuel": ("⛽ Fuel efficiency", "leaner, faster fuel saves"),
    "ers": ("🔋 ERS", "extra electrical boost per lap"),
    "pitcrew": ("🛠️ Pit Crew", "faster pit stops"),
    "race_pace": ("🏁 Race Pace", "raw pace over a race distance"),
    "quali_pace": ("⏱️ Qualifying Pace", "one-lap speed for the grid"),
    "chassis": ("🔩 Chassis", "overall structural performance"),
    "strategy": ("🧠 Strategy", "smarter calls under pressure"),
}

CAR_COLUMN = {
    "engine": "up_engine", "aero": "up_aero", "tires": "up_tires",
    "reliability": "up_reliability", "fuel": "up_fuel", "ers": "up_ers",
    "pitcrew": "up_pitcrew", "race_pace": "up_race_pace", "quali_pace": "up_quali_pace",
    "chassis": "up_chassis", "strategy": "up_strategy",
}


def upgrade_cost(level: int) -> int:
    return settings.upgrade_base_cost + settings.upgrade_cost_step * int(level)


def buy_upgrade(db: Session, user: User, key: str) -> tuple[int, int]:
    if key not in UPGRADES:
        raise ValueError("Unknown upgrade.")
    column = CAR_COLUMN[key]
    level = int(getattr(user, column, 0) or 0)
    if level >= settings.upgrade_max_level:
        raise ValueError("This part is already fully developed.")
    cost = upgrade_cost(level)
    if int(user.balance) < cost:
        raise ValueError(f"Not enough money. Next level costs {cost:,}.")

    wallet.spend_cash(db, user, cost, "UPGRADE", f"{UPGRADES[key][0]} Lv{level + 1}")
    setattr(user, column, level + 1)
    db.flush()

    row = db.scalar(
        select(CarUpgrade).where(CarUpgrade.user_id == user.id, CarUpgrade.part == key)
    )
    if row is None:
        db.add(CarUpgrade(user_id=user.id, part=key, level=level + 1))
    else:
        row.level = level + 1
    wallet.log_purchase(db, user, "upgrade", f"upgrade:{key}", UPGRADES[key][0], cost)
    db.flush()
    refresh_car(db, user)
    return level + 1, cost


def refresh_car(db: Session, user: User) -> Car:
    """Recompute and persist the car build the race engine reads."""
    from .races import car_package

    team = get_team(db, user)
    pkg = car_package(user, team)
    car = db.scalar(select(Car).where(Car.user_id == user.id))
    if car is None:
        car = Car(user_id=user.id)
        db.add(car)
    car.team_id = user.team_id
    car.engine = int(pkg["engine"])
    car.aero = int(pkg["aero"])
    car.tires = int(pkg["tires"])
    car.reliability = int(pkg["reliability"])
    car.fuel = int(pkg["fuel"])
    car.ers = int(user.up_ers)
    car.pit_crew = int(pkg["pit_crew"])
    car.race_pace = int(pkg["race_pace"])
    car.quali_pace = int(pkg["quali_pace"])
    car.strength = float(pkg["rating"])
    db.flush()
    return car


# --------------------------------------------------------------------------- #
# Driver training
# --------------------------------------------------------------------------- #
DRIVER_STATS: dict[str, tuple[str, str]] = {
    "speed": ("⚡ Speed", "raw one-lap pace"),
    "qualifying": ("⏱️ Qualifying", "grid position quality"),
    "race_pace": ("🏁 Race Pace", "consistent race rhythm"),
    "tire_management": ("🛞 Tire Management", "protects the tyres"),
    "wet_skill": ("🌧️ Wet Skill", "pace in the rain"),
    "overtaking": ("⚔️ Overtaking", "passes opponents"),
    "defending": ("🛡️ Defending", "holds position"),
    "consistency": ("🎯 Consistency", "fewer mistakes"),
}


def driver_levels(db: Session, user_id: int, driver_id: int) -> dict[str, int]:
    rows = db.scalars(
        select(DriverUpgrade).where(
            DriverUpgrade.user_id == user_id, DriverUpgrade.driver_id == driver_id
        )
    )
    return {row.stat: int(row.level) for row in rows}


def driver_upgrades(db: Session, user_id: int) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for row in db.scalars(select(DriverUpgrade).where(DriverUpgrade.user_id == user_id)):
        out.setdefault(int(row.driver_id), {})[row.stat] = int(row.level)
    return out


def driver_upgrade_cost(level: int) -> int:
    return settings.driver_upgrade_base_cost + settings.driver_upgrade_cost_step * int(level)


def buy_driver_upgrade(db: Session, user: User, driver_id: int, stat: str) -> tuple[int, int]:
    if stat not in DRIVER_STATS:
        raise ValueError("Unknown driver attribute.")
    if driver_id not in {user.driver1_id, user.driver2_id}:
        raise ValueError("You can only train your own race drivers.")
    levels = driver_levels(db, user.id, driver_id)
    level = int(levels.get(stat, 0))
    if level >= settings.upgrade_max_level:
        raise ValueError("This attribute is fully trained.")
    cost = driver_upgrade_cost(level)
    if int(user.balance) < cost:
        raise ValueError(f"Not enough money. Next level costs {cost:,}.")

    wallet.spend_cash(db, user, cost, "DRIVER_TRAINING", f"{DRIVER_STATS[stat][0]} Lv{level + 1}")
    row = db.scalar(
        select(DriverUpgrade).where(
            DriverUpgrade.user_id == user.id,
            DriverUpgrade.driver_id == driver_id,
            DriverUpgrade.stat == stat,
        )
    )
    if row is None:
        db.add(DriverUpgrade(user_id=user.id, driver_id=driver_id, stat=stat, level=level + 1))
    else:
        row.level = level + 1
    wallet.log_purchase(db, user, "driver_upgrade", f"{driver_id}:{stat}", DRIVER_STATS[stat][0], cost)
    db.flush()
    return level + 1, cost


# --------------------------------------------------------------------------- #
# Admin tools
# --------------------------------------------------------------------------- #
def refresh_driver_prices(db: Session) -> int:
    """Recompute market prices from driver ratings (admin tool)."""
    count = 0
    for driver in db.scalars(select(Driver)):
        driver.price = driver_price(driver.overall)
        driver.salary = driver_salary(driver.overall)
        count += 1
    db.flush()
    return count


def reset_market(db: Session) -> int:
    """Return every team and driver to the transfer market."""
    total = 0
    for row in list(db.scalars(select(UserTeam))):
        db.delete(row)
        total += 1
    for row in list(db.scalars(select(UserDriver))):
        db.delete(row)
        total += 1
    for user in db.scalars(select(User)):
        user.team_id = None
        user.driver1_id = None
        user.driver2_id = None
    db.flush()
    return total


def reset_progress(db: Session, user: User) -> None:
    """Wipe one player's progress but keep the account row."""
    user.team_id = None
    user.driver1_id = None
    user.driver2_id = None
    user.points = 0
    user.race_points = 0
    user.races_entered = 0
    user.race_entries_spent = 0
    user.wins = 0
    user.podiums = 0
    user.dnfs = 0
    user.poles = 0
    user.fastest_laps = 0
    user.titles = 0
    user.xp = 0
    user.daily_streak = 0
    user.last_daily_at = None
    for column in CAR_COLUMN.values():
        setattr(user, column, 0)
    user.balance = settings.starting_cash
    user.gold = settings.starting_gold
    for row in list(db.scalars(select(UserTeam).where(UserTeam.user_id == user.id))):
        db.delete(row)
    for row in list(db.scalars(select(UserDriver).where(UserDriver.user_id == user.id))):
        db.delete(row)
    for row in list(db.scalars(select(DriverUpgrade).where(DriverUpgrade.user_id == user.id))):
        db.delete(row)
    db.flush()
    refresh_car(db, user)
