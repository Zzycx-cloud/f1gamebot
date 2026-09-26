"""Race weekend engine: calendar, entries, weather, tyres, qualifying,
lap-by-lap simulation, live broadcast and payouts.

The simulation is *not* random: a car's average lap time comes from the driver's
race pace, the car package and the track characteristics; weather, tyre choice,
strategy, reliability and controlled randomness then shape the result.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    BotStat,
    Championship,
    ChampionshipPoint,
    Driver,
    QualifyingResult,
    Race,
    RaceEntry,
    RaceEvent,
    Result,
    Team,
    Track,
    User,
    UserDriver,
    UserTeam,
    WeatherLog,
)
from . import store, vip, wallet

# --------------------------------------------------------------------------- #
# Weather and tyres
# --------------------------------------------------------------------------- #
#: kind -> (label, lap-time penalty factor, wetness 0..1)
WEATHER: dict[str, tuple[str, float, float]] = {
    "dry": ("☀️ Dry", 0.0, 0.0),
    "cloudy": ("🌤️ Cloudy", 0.0015, 0.05),
    "light_rain": ("🌦️ Light Rain", 0.020, 0.45),
    "heavy_rain": ("🌧️ Heavy Rain", 0.045, 0.75),
    "storm": ("⛈️ Storm", 0.075, 1.00),
}

#: compound -> (label, speed delta s/lap vs medium, durability laps, wet skill 0..1)
TYRES: dict[str, tuple[str, float, int, float]] = {
    "soft": ("🔴 Soft", -0.35, 18, 0.0),
    "medium": ("🟡 Medium", 0.0, 28, 0.0),
    "hard": ("⚪ Hard", 0.30, 40, 0.0),
    "intermediate": ("🟢 Intermediate", 1.10, 34, 0.65),
    "wet": ("🔵 Wet", 2.20, 40, 1.00),
}

DRY_COMPOUNDS = ("soft", "medium", "hard")
WET_COMPOUNDS = ("intermediate", "wet")

POINTS = settings.points
SPRINT_POINTS = settings.sprint_points


# --------------------------------------------------------------------------- #
# Track helpers
# --------------------------------------------------------------------------- #
def _fallback_tracks() -> list[dict]:
    from ..seed import TRACKS

    return TRACKS


def _from_row(row: Track) -> dict:
    return dict(
        r=row.round_no, flag=row.flag, gp=row.gp_name, circuit=row.circuit, country=row.country,
        length=row.length_km, laps=row.laps, rec=row.lap_record, over=row.overtaking,
        down=row.downforce, deg=row.tire_degradation, sc=row.safety_car_prob,
        rain=row.rain_prob, stress=row.reliability_stress, sprint=bool(row.has_sprint),
        track_id=row.id,
    )


def all_tracks(db: Session) -> list[dict]:
    rows = list(db.scalars(select(Track).where(Track.active.is_(True)).order_by(Track.round_no)))
    if rows:
        return [_from_row(r) for r in rows]
    return [dict(t, track_id=None) for t in _fallback_tracks()]


def round_info(db: Session | None, round_no: int) -> dict:
    if db is not None:
        row = db.scalar(
            select(Track).where(Track.round_no == round_no, Track.active.is_(True)).limit(1)
        )
        if row is not None:
            return _from_row(row)
    tracks = _fallback_tracks()
    return dict(tracks[(round_no - 1) % len(tracks)], track_id=None)


def next_round_number(db: Session) -> int:
    """A random round that has not been raced yet (falls back to any round).

    The admin asked for the track card to drop at random, like a draw.
    """
    used = {
        int(r) for (r,) in db.execute(select(Race.round_no).where(Race.status == "finished"))
    }
    tracks = all_tracks(db)
    remaining = [int(t["r"]) for t in tracks if int(t["r"]) not in used]
    pool = remaining or [int(t["r"]) for t in tracks]
    return random.choice(pool)


def current_race(db: Session) -> Race | None:
    return db.scalar(
        select(Race)
        .where(Race.status.in_(("open", "paused", "live")))
        .order_by(Race.id.desc())
        .limit(1)
    )


def total_laps(info: dict, kind: str = "gp") -> int:
    if settings.race_laps_override:
        return settings.race_laps_override
    laps = int(info["laps"])
    return max(15, int(laps * 0.35)) if kind == "sprint" else laps


# --------------------------------------------------------------------------- #
# Strength models
# --------------------------------------------------------------------------- #
def car_package(user: User, team: Team | None) -> dict[str, float]:
    """Effective car numbers: chassis stats + the player's own development."""
    gain = settings.upgrade_gain
    if team is None:
        base = {
            "rating": 70.0, "aero": 70.0, "straight_line": 70.0, "cornering": 70.0,
            "reliability": 70.0, "tire_management": 70.0, "pit_crew": 70.0,
        }
    else:
        base = {
            "rating": float(team.rating), "aero": float(team.aero),
            "straight_line": float(team.straight_line), "cornering": float(team.cornering),
            "reliability": float(team.reliability), "tire_management": float(team.tire_management),
            "pit_crew": float(team.pit_crew),
        }
    up = {
        "engine": user.up_engine, "aero": user.up_aero, "tires": user.up_tires,
        "reliability": user.up_reliability, "fuel": user.up_fuel, "ers": user.up_ers,
        "pitcrew": user.up_pitcrew, "race_pace": user.up_race_pace,
        "quali_pace": user.up_quali_pace, "chassis": user.up_chassis,
        "strategy": user.up_strategy,
    }
    pkg = dict(base)
    pkg["engine"] = base["straight_line"] + up["engine"] * gain * 10 + up["ers"] * gain * 5
    pkg["aero"] = base["aero"] + up["aero"] * gain * 10 + up["chassis"] * gain * 4
    pkg["cornering"] = base["cornering"] + up["aero"] * gain * 5 + up["chassis"] * gain * 6
    pkg["tires"] = base["tire_management"] + up["tires"] * gain * 10 + float(user.tire_kits or 0)
    pkg["reliability"] = base["reliability"] + up["reliability"] * gain * 10
    pkg["fuel"] = 70.0 + up["fuel"] * gain * 10
    pkg["pit_crew"] = base["pit_crew"] + up["pitcrew"] * gain * 10
    pkg["race_pace"] = up["race_pace"] * gain * 10
    pkg["quali_pace"] = up["quali_pace"] * gain * 10
    pkg["strategy"] = 70.0 + up["strategy"] * gain * 10
    pkg["rating"] = (
        pkg["rating"]
        + up["chassis"] * gain * 6
        + up["engine"] * gain * 4
        + up["aero"] * gain * 4
        + up["race_pace"] * gain * 3
    )
    return pkg


def car_strength(user: User, team: Team | None) -> float:
    """Overall machinery rating (kept as a single number for older callers)."""
    return round(car_package(user, team)["rating"], 2)


def driver_package(driver: Driver | None, levels: dict[str, int] | None = None) -> dict[str, float]:
    levels = levels or {}
    step = 0.5  # each training level is worth half a rating point
    if driver is None:  # reserve driver signed on the fly
        base = dict(
            overall=62.0, speed=62.0, qualifying=62.0, race_pace=62.0, overtaking=60.0,
            defending=60.0, wet_skill=62.0, tire_management=65.0, consistency=70.0,
            experience=45.0, potential=70.0,
        )
    else:
        base = {
            "overall": float(driver.overall), "speed": float(driver.speed),
            "qualifying": float(driver.qualifying), "race_pace": float(driver.race_pace),
            "overtaking": float(driver.overtaking), "defending": float(driver.defending),
            "wet_skill": float(driver.wet_skill), "tire_management": float(driver.tire_management),
            "consistency": float(driver.consistency), "experience": float(driver.experience),
            "potential": float(driver.potential),
        }
    for stat, level in levels.items():
        if stat in base:
            base[stat] = min(100.0, base[stat] + level * step)
    base["overall"] = round(
        (base["speed"] + base["qualifying"] + base["race_pace"] + base["consistency"]) / 4, 2
    )
    return base


def driver_strength(driver: Driver | None) -> tuple[float, float]:
    """(pace, consistency) kept for the older helpers."""
    pkg = driver_package(driver)
    return pkg["race_pace"], pkg["consistency"]


# --------------------------------------------------------------------------- #
# Weekend management
# --------------------------------------------------------------------------- #
def create_race(db: Session, round_no: int | None = None, kind: str = "gp", organiser_id: int | None = None) -> Race:
    """Open a brand new race weekend (only one can be active at a time)."""
    if current_race(db) is not None:
        raise ValueError("There is already an active race weekend.")
    if round_no is None:
        round_no = next_round_number(db)
    info = round_info(db, round_no)
    minutes = settings.auto_start_minutes
    race = Race(
        round_no=round_no,
        gp_name=info["gp"],
        circuit=info["circuit"],
        country=info["country"],
        flag=info["flag"],
        track_id=info.get("track_id"),
        length_km=info["length"],
        total_laps=total_laps(info, kind),
        lap_record=info["rec"],
        overtaking=info["over"],
        downforce=info["down"],
        tire_degradation=info["deg"],
        safety_car_prob=info["sc"],
        rain_prob=info["rain"],
        reliability_stress=info["stress"],
        kind=kind,
        status="open",
        weather=pick_weather(info, force="dry"),
        auto_start_minutes=minutes,
        registration_ends_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    )
    db.add(race)
    db.flush()
    stats = get_stats(db)
    stats.races_created += 1
    return race


def entry_of(db: Session, race_id: int, user_id: int) -> RaceEntry | None:
    return db.scalar(select(RaceEntry).where(RaceEntry.race_id == race_id, RaceEntry.user_id == user_id))


def registration_open(race: Race) -> bool:
    return race.status == "open"


def is_organiser(db: Session, race: Race, user_id: int) -> bool:
    """The organiser may extend or start a weekend: whoever opened it, or the
    first player who paid the entry fee when an admin did not create it."""
    if race.organiser_id is not None:
        return int(race.organiser_id) == int(user_id)
    first = db.scalar(
        select(RaceEntry.user_id).where(RaceEntry.race_id == race.id).order_by(RaceEntry.id.asc()).limit(1)
    )
    return first is not None and int(first) == int(user_id)


def extend_registration(db: Session, race: Race, minutes: int) -> datetime:
    """Push the registration deadline forward and re-arm the auto-start timer."""
    minutes = int(minutes)
    if minutes <= 0:
        raise ValueError("Extension must be a positive number of minutes.")
    if race.status not in ("open", "paused"):
        raise ValueError("Registration for this weekend is already closed.")
    base = race.registration_ends_at or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    race.registration_ends_at = base + timedelta(minutes=minutes)
    race.auto_start_minutes = int(race.auto_start_minutes or 0) + minutes
    race.status = "open"
    db.flush()
    return race.registration_ends_at


def join_race(db: Session, race: Race, user: User, drivers: list[Driver] | None = None) -> int:
    """Pay the entry fee plus the weekend salaries and register the player."""
    from . import moderation  # local import avoids a cycle at import time

    if race.status != "open":
        raise ValueError("Registration for this weekend is already closed.")
    maximum = store.max_participants(db)
    if race.participants >= maximum:
        raise ValueError("The entry list is full.")
    if entry_of(db, race.id, user.id) is not None:
        raise ValueError("You are already on the entry list.")
    if moderation.is_banned(db, user.id):
        raise ValueError("Your account is suspended.")
    if user.team_id is None:
        raise ValueError("Buy a constructor on the transfer market first.")
    if user.driver1_id is None:
        raise ValueError("Sign at least one driver first.")

    fee = store.entry_fee(db)
    salaries = sum(d.salary for d in (drivers or []))
    total = fee + salaries
    if user.balance < total:
        raise ValueError(f"You need {total:,} to enter (fee + salaries).")

    wallet.spend_cash(db, user, total, "ENTRY_FEE", f"{race.flag} {race.gp_name}")
    user.races_entered += 1
    user.race_entries_spent += total
    db.add(RaceEntry(race_id=race.id, user_id=user.id, fee_paid=total, quali_times=[]))
    race.participants += 1
    db.flush()
    stats = get_stats(db)
    stats.entries_total += 1
    stats.fees_collected += total
    return total


def leave_race(db: Session, race: Race, user: User) -> int:
    entry = entry_of(db, race.id, user.id)
    if entry is None:
        raise ValueError("You are not entered for this weekend.")
    if race.status != "open":
        raise ValueError("The weekend already started, you cannot withdraw.")
    refund = int(entry.fee_paid)
    wallet.add_cash(db, user, refund, "ENTRY_REFUND", f"{race.flag} {race.gp_name}")
    user.races_entered = max(0, int(user.races_entered) - 1)
    user.race_entries_spent = max(0, int(user.race_entries_spent) - refund)
    entry.fee_paid = 0
    db.delete(entry)
    db.flush()
    race.participants = max(0, int(race.participants) - 1)
    stats = get_stats(db)
    stats.entries_total = max(0, stats.entries_total - 1)
    stats.fees_collected = max(0, stats.fees_collected - refund)
    return refund


def cancel_race(db: Session, race: Race, reason: str = "not enough entries") -> list[int]:
    """Cancel a weekend and refund everybody who paid."""
    refunded: list[int] = []
    for entry in list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id))):
        user = db.get(User, entry.user_id)
        if user is not None and entry.fee_paid:
            wallet.add_cash(db, user, int(entry.fee_paid), "ENTRY_REFUND", f"Cancelled: {reason}"[:160])
        refunded.append(entry.user_id)
        db.delete(entry)
    race.status = "cancelled"
    race.finished_at = datetime.now(timezone.utc)
    race.participants = 0
    db.flush()
    return refunded


# --------------------------------------------------------------------------- #
# AI entrants (the /arace group mode: bots fill the grid and race)
# --------------------------------------------------------------------------- #
BOT_ID_BASE = -910_000


def fill_with_bots(db: Session, race: Race, target: int | None = None) -> list[User]:
    """Fill the entry list with AI drivers so a race can run without humans.

    Bot ids are negative, so they never collide with real Telegram accounts.
    """
    if target is None:
        target = random.randint(max(store.min_participants(db), 6), 10)
    target = min(max(1, target), store.max_participants(db))
    need = max(0, target - int(race.participants))
    teams = list(db.scalars(select(Team).order_by(func.random())))
    drivers = list(db.scalars(select(Driver).order_by(func.random())))
    bots: list[User] = []
    for i in range(need):
        team = teams[i % len(teams)] if teams else None
        driver = drivers[i % len(drivers)] if drivers else None
        bot = db.get(User, BOT_ID_BASE - i)
        if bot is None:
            bot = User(
                id=BOT_ID_BASE - i,
                username=f"ai_pilot_{i + 1}",
                first_name=f"🤖 {driver.name if driver else f'AI-{i + 1}'}",
                balance=0,
                gold=0,
            )
            db.add(bot)
            db.flush()
        # reset the previous simulation's contracts, then re-own consistently
        for row in list(db.scalars(select(UserTeam).where(UserTeam.user_id == bot.id))):
            db.delete(row)
        for row in list(db.scalars(select(UserDriver).where(UserDriver.user_id == bot.id))):
            db.delete(row)
        bot.team_id = team.id if team else None
        bot.driver1_id = driver.id if driver else None
        if team is not None:
            db.add(UserTeam(user_id=bot.id, team_id=team.id, price_paid=0))
        if driver is not None:
            db.add(UserDriver(user_id=bot.id, driver_id=driver.id, price_paid=0))
        db.add(
            RaceEntry(
                race_id=race.id,
                user_id=bot.id,
                fee_paid=0,
                quali_times=[],
                quali_avg=round(race.lap_record * random.uniform(1.005, 1.06), 3),
            )
        )
        race.participants += 1
        bots.append(bot)
    db.flush()
    return bots


def mention(user_id: int, name: str) -> str:
    """A clickable Telegram mention for real users; plain text for the bots."""
    from ..format import esc

    if user_id > 0:
        return f"<a href='tg://user?id={user_id}'>{esc(name)}</a>"
    return esc(name)


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #
def pick_weather(info: dict, rng: random.Random | None = None, force: str | None = None) -> str:
    rng = rng or random.Random()
    if force:
        return force
    rain = float(info.get("rain", 0.15))
    roll = rng.random()
    if roll < rain * 0.25:
        return "storm"
    if roll < rain * 0.60:
        return "heavy_rain"
    if roll < rain:
        return "light_rain"
    return "cloudy" if rng.random() < 0.40 else "dry"


def weather_label(kind: str) -> str:
    return WEATHER.get(kind, WEATHER["dry"])[0]


def tyre_label(compound: str) -> str:
    return TYRES.get(compound, TYRES["medium"])[0]


def best_compound(weather: str, rng: random.Random | None = None) -> str:
    wet = WEATHER.get(weather, WEATHER["dry"])[2]
    rng = rng or random.Random()
    if wet >= 0.75:
        return "wet"
    if wet >= 0.40:
        return "intermediate"
    return rng.choice(("soft", "medium", "medium", "hard"))


# --------------------------------------------------------------------------- #
# Qualifying
# --------------------------------------------------------------------------- #
def quali_pace(
    db: Session,
    race: Race,
    user: User,
    team: Team | None,
    driver: Driver | None,
    levels: dict[str, int] | None = None,
    weather: str | None = None,
) -> float:
    """One representative qualifying lap time in seconds."""
    pkg = car_package(user, team)
    drv = driver_package(driver, levels)
    weather = weather or race.weather
    info = {
        "down": race.downforce, "deg": race.tire_degradation, "over": race.overtaking,
        "rain": race.rain_prob, "stress": race.reliability_stress,
    }
    car = (
        pkg["rating"] * 0.45
        + pkg["aero"] * info["down"] * 0.20
        + pkg["engine"] * (1 - info["down"]) * 0.20
        + pkg["quali_pace"] * 0.15
    )
    pilot = drv["qualifying"] * 0.55 + drv["speed"] * 0.30 + drv["consistency"] * 0.15
    base = race.lap_record * (1.0 - (car * 0.55 + pilot * 0.45 - 70.0) / 2600.0)
    base *= 1.0 + WEATHER.get(weather, WEATHER["dry"])[1] * 1.6
    return base


def run_qualifying(
    db: Session,
    race: Race,
    user: User,
    team: Team | None,
    driver: Driver | None = None,
    levels: dict[str, int] | None = None,
) -> float:
    """Best-of-N flying laps; the average counts. Returns the average lap time."""
    if race.status not in ("open", "paused"):
        raise ValueError("Qualifying is closed.")
    entry = entry_of(db, race.id, user.id)
    if entry is None:
        raise ValueError("You are not entered for this weekend.")
    if entry.quali_avg > 0:
        return entry.quali_avg

    driver = driver or (db.get(Driver, user.driver1_id) if user.driver1_id else None)
    base = quali_pace(db, race, user, team, driver, levels)
    times = []
    for _ in range(max(1, settings.quali_laps)):
        noise = random.gauss(0.0, race.lap_record * 0.0022)
        times.append(max(race.lap_record * 0.85, base + noise - 0.05))
    avg = sum(times) / len(times)
    entry.quali_times = [round(t, 3) for t in times]
    entry.quali_avg = round(avg, 3)
    db.flush()
    return entry.quali_avg


def quali_table(db: Session, race: Race) -> list[RaceEntry]:
    rows = list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)))
    return sorted(rows, key=lambda e: e.quali_avg if e.quali_avg > 0 else 1e9)


def build_grid(db: Session, race: Race, weather: str | None = None) -> list[RaceEntry]:
    """Freeze the grid: everyone who did not set a time gets a simulated one."""
    weather = weather or race.weather
    # A weekend can be re-frozen (admin restart): drop the old sheet first.
    for old in list(db.scalars(select(QualifyingResult).where(QualifyingResult.race_id == race.id))):
        db.delete(old)
    entries = list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)))
    for entry in entries:
        if entry.quali_avg <= 0:
            user = db.get(User, entry.user_id)
            if user is None:
                continue
            team = db.get(Team, user.team_id) if user.team_id else None
            driver = db.get(Driver, user.driver1_id) if user.driver1_id else None
            base = quali_pace(db, race, user, team, driver, None, weather)
            entry.quali_avg = round(base + random.gauss(0.0, race.lap_record * 0.003), 3)
            entry.quali_times = [entry.quali_avg]
    entries.sort(key=lambda e: e.quali_avg)
    for pos, entry in enumerate(entries, start=1):
        entry.grid_pos = pos
        db.add(
            QualifyingResult(
                race_id=race.id, user_id=entry.user_id, position=pos, time=entry.quali_avg,
                laps=entry.quali_times, weather=weather,
            )
        )
    race.grid = [{"user_id": e.user_id, "time": e.quali_avg, "pos": e.grid_pos} for e in entries]
    race.quali_done = True
    race.weather = weather
    db.flush()
    return entries


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #
@dataclass
class SimEntrant:
    user_id: int
    name: str
    car: float = 70.0
    drivers: list[dict] = field(default_factory=list)
    quali_avg: float = 0.0
    grid_pos: int = 0
    package: dict = field(default_factory=dict)
    tyre: str = "medium"
    strategy: str = "medium"
    pit_stops: int = 0
    avg: float = 0.0
    retire_lap: int | None = None
    retire_reason: str = ""
    position: int = 0
    points: int = 0
    prize: int = 0
    gold: int = 0
    fastest_lap: bool = False
    best_lap: float = 0.0
    total_time: float = 0.0
    gap: float = 0.0


@dataclass
class SimResult:
    rows: list[SimEntrant]
    total_laps: int
    fastest_lap_user: int | None
    weather: str = "dry"
    weather_history: list[tuple[int, str]] = field(default_factory=list)
    events: list[tuple[int, int | None, str, str]] = field(default_factory=list)
    grid_spread: float = 0.35


def _pace_factor(pkg: dict, info: dict) -> float:
    """How much of the lap is decided by the car at this particular circuit."""
    down = float(info.get("down", 0.5))
    return 0.45 + 0.15 * down


def _lap_time(
    entrant: SimEntrant,
    race: Race,
    info: dict,
    weather: str,
    tyre: str,
    wear: float,
    rng: random.Random,
) -> float:
    pkg = entrant.package
    drv = entrant.drivers[0] if entrant.drivers else {"race_pace": 62, "consistency": 70,
                                                     "tire_management": 65, "wet_skill": 62}
    car = (
        pkg.get("rating", entrant.car) * 0.40
        + pkg.get("engine", 70) * (1 - info["down"]) * 0.16
        + pkg.get("aero", 70) * info["down"] * 0.16
        + pkg.get("cornering", 70) * info["down"] * 0.10
        + pkg.get("race_pace", 0) * 0.08
    )
    pilot = (
        drv.get("race_pace", 70) * 0.45
        + drv.get("consistency", 70) * 0.20
        + drv.get("tire_management", 70) * 0.20
        + drv.get("speed", 70) * 0.15
    )
    strength = car * _pace_factor(pkg, info) + pilot * 0.40
    base = race.lap_record * (1.0 - (strength - 70.0) / 2400.0)

    # Weather + the driver's wet skill and the tyre's wet performance.
    w_name, w_penalty, wetness = WEATHER.get(weather, WEATHER["dry"])
    t_name, t_delta, t_life, t_wet = TYRES.get(tyre, TYRES["medium"])
    base *= 1.0 + w_penalty
    mismatch = max(0.0, wetness - t_wet)
    base += mismatch * race.lap_record * 0.030
    base -= drv.get("wet_skill", 70) / 100.0 * wetness * race.lap_record * 0.012
    base += t_delta * (1.0 - wetness * 0.6)

    # Tyre wear: soft falls away fast, hard lasts, hot tracks punish everyone.
    deg = (1.0 + info["deg"]) * (30.0 / max(8, t_life))
    base += wear * deg * race.lap_record * 0.0016

    # Driving errors, kept small for consistent drivers.
    noise_sigma = race.lap_record * settings.ai_base_error * (1.0 - (drv.get("consistency", 70) - 55) / 220.0)
    base += rng.gauss(0.0, max(0.02, noise_sigma))
    return max(race.lap_record * 0.80, base)


def simulate_race(
    entries: list[SimEntrant],
    race: Race,
    rng: random.Random | None = None,
    weather: str | None = None,
) -> SimResult:
    """Lap-by-lap simulation with weather changes, tyre wear, pit stops,
    safety cars, overtakes, crashes and mechanical failures."""
    rng = rng or random.Random()
    laps = max(5, int(race.total_laps))
    info = {
        "down": race.downforce, "deg": race.tire_degradation, "over": race.overtaking,
        "rain": race.rain_prob, "stress": race.reliability_stress, "sc": race.safety_car_prob,
    }
    weather = weather or race.weather or "dry"
    result = SimResult(rows=entries, total_laps=laps, fastest_lap_user=None, weather=weather)
    result.weather_history.append((0, weather))
    if not entries:
        return result

    for e in entries:
        e.tyre = best_compound(weather, rng)
        e.strategy = e.strategy or e.tyre
        e.retire_lap = None
        e.pit_stops = 0
        e.total_time = 0.0
        e.best_lap = 0.0
        e.fastest_lap = False
        e.avg = 0.0
        e.gap = 0.0

    order = sorted(entries, key=lambda e: e.grid_pos or 999)
    positions = {e.user_id: (e.grid_pos or i) for i, e in enumerate(order, start=1)}
    gaps = {e.user_id: 0.0 for e in entries}
    wear = {e.user_id: rng.uniform(0.0, 3.0) for e in entries}
    best_overall = float("inf")
    fastest_user: int | None = None
    sc_laps_left = 0

    for lap in range(1, laps + 1):
        # ---- weather may change during the race -------------------------- #
        if lap > 2 and lap % 7 == 0 and weather in ("dry", "cloudy") and rng.random() < info["rain"] * 0.35:
            weather = rng.choice(("light_rain", "heavy_rain"))
            result.weather_history.append((lap, weather))
            result.events.append((lap, None, "rain", weather_label(weather)))
        elif lap > 2 and lap % 9 == 0 and WEATHER.get(weather, WEATHER["dry"])[2] > 0.4 and rng.random() < 0.45:
            weather = "dry"
            result.weather_history.append((lap, weather))
            result.events.append((lap, None, "rain", "Track drying"))

        wet = WEATHER.get(weather, WEATHER["dry"])[2]
        running = [e for e in entries if e.retire_lap is None]

        # ---- safety car -------------------------------------------------- #
        if sc_laps_left > 0:
            sc_laps_left -= 1
        elif rng.random() < info["sc"] / max(20.0, laps) * 3.0:
            sc_laps_left = rng.randint(2, 4)
            result.events.append((lap, None, "safety_car", "🚨 Safety Car"))
            for e in running:
                gaps[e.user_id] *= 0.15

        for e in running:
            w = wear[e.user_id]
            lap_time = _lap_time(e, race, info, weather, e.tyre, w, rng)
            e.total_time += lap_time
            wear[e.user_id] = w + 1.0
            if lap_time < best_overall:
                best_overall = lap_time
                e.best_lap = lap_time
                fastest_user = e.user_id

            # ---- pit stop ------------------------------------------------ #
            _n, _delta, life, _wet = TYRES.get(e.tyre, TYRES["medium"])
            wear_limit = life * (1.0 + info["deg"] * 0.4)
            needs_wet_tyre = wet >= 0.55 and TYRES.get(e.tyre, TYRES["medium"])[3] < 0.5
            needs_dry_tyre = wet <= 0.15 and TYRES.get(e.tyre, TYRES["medium"])[3] > 0.5
            if (wear[e.user_id] >= wear_limit or needs_wet_tyre or needs_dry_tyre) and e.pit_stops < 3:
                e.pit_stops += 1
                pit_loss = 21.0 - e.package.get("pit_crew", 70) / 12.0
                e.total_time += max(12.0, pit_loss)
                wear[e.user_id] = 0.0
                e.tyre = best_compound(weather, rng)
                result.events.append((lap, e.user_id, "pit", tyre_label(e.tyre)))

            # ---- reliability / crash ------------------------------------- #
            reliability = e.package.get("reliability", 70)
            consistency = e.drivers[0].get("consistency", 70) if e.drivers else 70
            fail = (0.00035 + info["stress"] * 0.00090) * (1.0 + (95 - reliability) / 60.0)
            if rng.random() < fail:
                e.retire_lap = lap
                e.retire_reason = "🔧 Mechanical Failure"
                result.events.append((lap, e.user_id, "mechanical", e.retire_reason))
                continue
            crash = 0.00018 + wet * 0.00090 + (1.0 - info["over"]) * 0.00020
            crash *= 1.0 + (95 - consistency) / 90.0
            if rng.random() < crash:
                e.retire_lap = lap
                e.retire_reason = "💥 Crash"
                result.events.append((lap, e.user_id, "crash", e.retire_reason))

        # ---- running order for this lap ---------------------------------- #
        running = [e for e in entries if e.retire_lap is None]
        if not running:
            break
        if sc_laps_left > 0:
            for e in running:
                gaps[e.user_id] *= 0.55
        running.sort(key=lambda e: e.total_time)
        for idx, e in enumerate(running):
            positions[e.user_id] = idx + 1

        if sc_laps_left == 0 and len(running) > 1:
            for idx in range(len(running) - 1, 0, -1):
                ahead, me = running[idx - 1], running[idx]
                delta = me.total_time - ahead.total_time
                if delta > 0.9:
                    continue
                attack = (
                    me.drivers[0].get("overtaking", 70) if me.drivers else 70
                ) + me.package.get("engine", 70) * 0.35
                guard = (
                    ahead.drivers[0].get("defending", 70) if ahead.drivers else 70
                ) + ahead.package.get("cornering", 70) * 0.35
                chance = 0.06 * info["over"] * (1.0 + (attack - guard) / 60.0)
                if rng.random() < max(0.0, chance):
                    me.total_time = ahead.total_time - 0.05
                    result.events.append(
                        (lap, me.user_id, "overtake", f"P{positions[me.user_id]} → P{positions[ahead.user_id]}")
                    )
                    running.sort(key=lambda e: e.total_time)

    # ---- post-race penalties (must land before the classification sort) --- #
    for e in entries:
        if rng.random() < 0.04:
            e.total_time += 5.0
            result.events.append((max(1, laps // 2), e.user_id, "penalty", "⚠️ +5s track limits"))

    # ---- classification --------------------------------------------------- #
    finishers = sorted([e for e in entries if e.retire_lap is None], key=lambda e: e.total_time)
    retired = sorted([e for e in entries if e.retire_lap is not None], key=lambda e: -(e.retire_lap or 0))
    rows = finishers + retired
    leader_time = finishers[0].total_time if finishers else 0.0
    for pos, row in enumerate(rows, start=1):
        row.position = pos
        row.avg = row.total_time / max(1, laps)
        row.gap = 0.0 if pos == 1 or row.retire_lap else round(row.total_time - leader_time, 3)

    if finishers and fastest_user is not None:
        for row in finishers:
            if row.user_id == fastest_user and row.best_lap > 0:
                row.fastest_lap = True
                result.fastest_lap_user = row.user_id
                result.events.append((laps, row.user_id, "fastest_lap", f"{row.best_lap:.3f}s"))
                break

    for e in entries:
        if rng.random() < 0.03:
            result.events.append((max(1, laps // 3), e.user_id, "track_limits", "🏎️ Track limits warning"))
    if rng.random() < info["sc"] * 0.12:
        result.events.append((max(1, laps // 2), None, "red_flag", "🔴 Red Flag"))
    if rng.random() < info["sc"] * 0.20:
        result.events.append((max(1, laps // 4), None, "vsc", "🟡 VSC"))

    result.rows = rows
    return result


def live_row_at(row: SimEntrant, lap: int, leader_value: float, grid_spread: float) -> tuple[float, bool]:
    if row.retire_lap is not None and row.retire_lap <= lap:
        return 0.0, True
    value = row.avg * lap + (row.grid_pos - row.position) * grid_spread
    return (value - leader_value) / max(1, lap), False


def live_gap(row: SimEntrant, leader: SimEntrant, lap: int, grid_spread: float) -> float:
    mine = row.avg * lap + (row.grid_pos - row.position) * grid_spread
    theirs = leader.avg * lap + (leader.grid_pos - leader.position) * grid_spread
    return (mine - theirs) / max(1, lap)


def live_order(rows: list[SimEntrant], lap: int, grid_spread: float = 0.35) -> list[SimEntrant]:
    running = [r for r in rows if r.retire_lap is None or r.retire_lap > lap]
    running.sort(key=lambda r: r.avg * lap + (r.grid_pos - r.position) * grid_spread)
    return running


def prize_for(position: int, kind: str = "gp") -> int:
    table = settings.sprint_payouts if kind == "sprint" else settings.prize_payouts
    if 1 <= position <= len(table):
        return table[position - 1]
    return 0


def gold_for(position: int, kind: str = "gp") -> int:
    """Gold is the scarce currency: only the podium earns it on a Sunday."""
    base = {1: 10, 2: 6, 3: 4, 4: 2}.get(position, 0)
    return base * (1 if kind == "sprint" else 2)


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def apply_results(
    db: Session,
    race: Race,
    sim: SimResult,
    payouts: tuple[int, ...] | None = None,
) -> list[RaceEntry]:
    """Write the finished race into the database and pay the prize money.

    Idempotent: a weekend that is already finished is never paid out twice.
    """
    if race.status == "finished":
        return list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)))
    entries = {e.user_id: e for e in db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id))}
    points_table = SPRINT_POINTS if race.kind == "sprint" else POINTS
    if payouts is None and race.kind != "sprint":
        payouts = store.prize_payouts(db)  # honour the admin-configurable purse
    total_prize = 0
    wet = WEATHER.get(sim.weather, WEATHER["dry"])[2] > 0.4

    for row in sim.rows:
        entry = entries.get(row.user_id)
        user = db.get(User, row.user_id)
        team = db.get(Team, user.team_id) if user and user.team_id else None
        points = points_table[row.position - 1] if row.position <= len(points_table) else 0
        prize = payouts[row.position - 1] if payouts and row.position <= len(payouts) else prize_for(
            row.position, race.kind
        )
        gold = gold_for(row.position, race.kind)
        if row.fastest_lap and row.position <= 10 and race.kind != "sprint":
            prize += settings.fastest_lap_bonus
        row.points, row.prize, row.gold = points, prize, gold
        total_prize += prize

        if entry is not None:
            entry.finished = True
            entry.race_avg = round(row.avg, 3)
            entry.race_times = [round(row.avg, 3)]
            entry.finish_pos = row.position
            entry.dnf = row.retire_lap is not None
            entry.fastest_lap = row.fastest_lap
            entry.points = points
            entry.money_won = prize
            entry.gold_won = gold
            entry.pit_stops = row.pit_stops
            entry.tyre = row.tyre
            entry.strategy = row.strategy
            entry.gap = round(row.gap, 3)
            entry.total_time = round(row.total_time, 3)
        if user is None:
            continue

        if prize:
            bonus = int(prize * (vip.prize_multiplier(user) - 1.0))
            wallet.add_cash(db, user, prize + bonus, "PRIZE", f"{race.flag} {race.gp_name} P{row.position}")
        if gold:
            wallet.add_gold(db, user, gold, "PRIZE_GOLD", f"{race.flag} {race.gp_name} P{row.position}")
        user.xp = int(user.xp) + 20 + max(0, 25 - row.position) * 3

        user.points += points
        user.race_points += points
        if row.retire_lap is None:
            if row.position == 1:
                user.wins += 1
                if wet:
                    user.races_rained_wins += 1
            if row.position <= 3:
                user.podiums += 1
        else:
            user.dnfs += 1
        if row.grid_pos == 1 and row.retire_lap is None:
            user.poles += 1
        if row.fastest_lap:
            user.fastest_laps += 1

        db.add(
            Result(
                race_id=race.id, user_id=row.user_id, round_no=race.round_no, gp_name=race.gp_name,
                position=row.position, points=points, prize=prize, gold=gold, gap=round(row.gap, 3),
                total_time=round(row.total_time, 3), pit_stops=row.pit_stops,
                fastest_lap=row.fastest_lap, dnf=row.retire_lap is not None, weather=sim.weather,
                team_name=team.name if team else "",
            )
        )

    for lap, user_id, kind, detail in sim.events:
        db.add(RaceEvent(race_id=race.id, lap=lap, user_id=user_id, kind=kind, detail=detail[:200]))
    for lap, kind in sim.weather_history:
        db.add(WeatherLog(race_id=race.id, lap=lap, kind=kind))

    race.status = "finished"
    race.finished_at = datetime.now(timezone.utc)
    db.flush()
    update_championship(db)
    stats = get_stats(db)
    stats.races_finished += 1
    stats.prizes_paid += total_prize
    return list(entries.values())


def update_championship(db: Session, season: int = 2026) -> tuple[Championship, Championship]:
    """Rebuild both championship tables from the stored race results."""
    drivers = db.scalar(select(Championship).where(Championship.season == season, Championship.kind == "drivers"))
    if drivers is None:
        drivers = Championship(season=season, kind="drivers")
        db.add(drivers)
    constructors = db.scalar(
        select(Championship).where(Championship.season == season, Championship.kind == "constructors")
    )
    if constructors is None:
        constructors = Championship(season=season, kind="constructors")
        db.add(constructors)
    db.flush()

    for champ in (drivers, constructors):
        for row in list(db.scalars(select(ChampionshipPoint).where(ChampionshipPoint.championship_id == champ.id))):
            db.delete(row)
    db.flush()

    for user in db.scalars(select(User)):
        agg = db.execute(
            select(
                func.coalesce(func.sum(Result.points), 0),
                func.coalesce(func.sum(case_win()), 0),
            ).where(Result.user_id == user.id)
        ).one()
        db.add(
            ChampionshipPoint(
                championship_id=drivers.id, user_id=user.id, points=int(agg[0] or 0),
                wins=int(user.wins or 0), podiums=int(user.podiums or 0),
                poles=int(user.poles or 0), fastest_laps=int(user.fastest_laps or 0),
            )
        )
    db.flush()
    leader = db.scalar(
        select(ChampionshipPoint)
        .where(ChampionshipPoint.championship_id == drivers.id)
        .order_by(ChampionshipPoint.points.desc())
        .limit(1)
    )
    drivers.leader_user_id = leader.user_id if leader else None

    for team in db.scalars(select(Team)):
        points = int(
            db.scalar(
                select(func.coalesce(func.sum(Result.points), 0))
                .join(User, User.id == Result.user_id)
                .where(User.team_id == team.id)
            )
            or 0
        )
        if points:
            db.add(ChampionshipPoint(championship_id=constructors.id, team_id=team.id, points=points))
    db.flush()
    top = db.scalar(
        select(ChampionshipPoint)
        .where(ChampionshipPoint.championship_id == constructors.id)
        .order_by(ChampionshipPoint.points.desc())
        .limit(1)
    )
    constructors.leader_team_id = top.team_id if top else None
    db.flush()
    return drivers, constructors


def case_win():
    from sqlalchemy import case

    return case((Result.position == 1, 1), else_=0)


# --------------------------------------------------------------------------- #
# Standings & history
# --------------------------------------------------------------------------- #
def season_standings(db: Session, limit: int = 25) -> list[tuple[User, int, int, int]]:
    users = list(
        db.scalars(
            select(User)
            .where(User.banned.is_(False))
            .order_by(User.race_points.desc(), User.wins.desc(), User.id.asc())
            .limit(limit)
        )
    )
    return [(u, u.race_points, u.wins, u.podiums) for u in users]


def constructored_standings(db: Session, limit: int = 15) -> list[tuple[Team, int, int]]:
    rows = list(
        db.execute(
            select(Team, func.sum(User.race_points), func.count(User.id))
            .join(User, User.team_id == Team.id)
            .where(User.banned.is_(False))
            .group_by(Team.id)
            .order_by(func.sum(User.race_points).desc())
            .limit(limit)
        )
    )
    return [(team, int(points or 0), int(riders)) for team, points, riders in rows]


def race_history(db: Session, limit: int = 10) -> list[Race]:
    return list(
        db.scalars(
            select(Race)
            .where(Race.status.in_(("finished", "cancelled")))
            .order_by(Race.id.desc())
            .limit(limit)
        )
    )


def upcoming_races(db: Session, limit: int = 24) -> list[dict]:
    """The calendar of the season that can be opened next."""
    tracks = all_tracks(db)
    last_finished = db.scalar(
        select(func.max(Race.round_no)).select_from(Race).where(Race.status == "finished")
    )
    start = int(last_finished or 0)
    ordered = [t for t in tracks if t["r"] > start] + [t for t in tracks if t["r"] <= start]
    return ordered[:limit]


def race_classification(db: Session, race_id: int) -> list[RaceEntry]:
    return list(
        db.scalars(
            select(RaceEntry).where(RaceEntry.race_id == race_id).order_by(RaceEntry.finish_pos.asc())
        )
    )


def race_events(db: Session, race_id: int, limit: int = 40) -> list[RaceEvent]:
    return list(
        db.scalars(
            select(RaceEvent).where(RaceEvent.race_id == race_id).order_by(RaceEvent.lap.asc()).limit(limit)
        )
    )


# --------------------------------------------------------------------------- #
# Global stats row
# --------------------------------------------------------------------------- #
def get_stats(db: Session) -> BotStat:
    stats = db.get(BotStat, 1)
    if stats is None:
        stats = BotStat(id=1)
        db.add(stats)
        db.flush()
    return stats


def refresh_stats(db: Session) -> BotStat:
    from . import moderation

    stats = get_stats(db)
    stats.players_total = int(db.scalar(select(func.count(User.id))) or 0)
    stats.players_banned = moderation.banned_user_ids_count(db)
    stats.players_active = int(
        db.scalar(select(func.count(User.id)).where(User.races_entered > 0, User.banned.is_(False))) or 0
    )
    stats.cash_in_circulation = int(db.scalar(select(func.sum(User.balance))) or 0)
    return stats


# --------------------------------------------------------------------------- #
# Live broadcast
# --------------------------------------------------------------------------- #
async def broadcast_race(
    bot,
    chat_id: int,
    race: Race,
    sim: SimResult,
    names: dict[int, str],
    progress_message_id: int | None = None,
) -> None:
    """Edit one message with the running order every ``live_chunk`` laps."""
    if not settings.live_enabled or chat_id <= 0:
        return
    laps = sim.total_laps
    step = max(1, settings.live_chunk)
    message_id = progress_message_id
    header = f"🏁 <b>{race.flag} {esc(race.gp_name)} — LIVE</b>\n"
    by_lap: dict[int, list[str]] = {}
    for lap, _user_id, kind, detail in sim.events:
        emoji = {
            "overtake": "⚡", "pit": "🛞", "crash": "💥", "mechanical": "🔧", "rain": "🌧️",
            "safety_car": "🚨", "vsc": "🟡", "red_flag": "🔴", "fastest_lap": "⚡",
            "penalty": "⚠️", "track_limits": "🏎️",
        }.get(kind, "•")
        who = names.get(_user_id or 0, "")
        by_lap.setdefault(lap, []).append(f"{emoji} {who} {detail}".strip())

    for lap in range(step, laps + 1, step):
        order = live_order(sim.rows, lap)
        if not order:
            break
        leader = order[0]
        lines = [header, f"Lap <b>{min(lap, laps)}/{laps}</b>  {progress_bar(lap, laps)}  {weather_label(sim.weather)}\n"]
        for idx, row in enumerate(order[:10], start=1):
            delta = live_gap(row, leader, lap, 0.35)
            suffix = "" if idx == 1 else f"  <i>+{delta:.1f}s</i>"
            pit = f" 🛞{row.pit_stops}" if row.pit_stops else ""
            lines.append(f"{idx}. {esc(names.get(row.user_id, str(row.user_id)))}{pit}{suffix}\n")
        retired = [r for r in sim.rows if r.retire_lap is not None and lap >= r.retire_lap > lap - step]
        for row in retired:
            lines.append(f"\n🔧 <i>RETIREMENT: {esc(names.get(row.user_id, ''))}</i>")
        for note in by_lap.get(lap, [])[:3]:
            lines.append(f"\n<i>{esc(note)}</i>")
        text = "".join(lines)
        try:
            if message_id is None:
                sent = await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
                message_id = sent.message_id
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except Exception:
            break
        await asyncio.sleep(settings.live_delay)


def progress_bar(done: int, total: int, length: int = 10) -> str:
    total = max(1, total)
    filled = min(length, round(length * done / total))
    return "█" * filled + "░" * (length - filled)


def esc(text: object) -> str:
    from html import escape

    return escape(str(text), quote=False)
