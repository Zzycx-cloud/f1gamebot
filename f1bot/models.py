"""Database models (SQLAlchemy 2.0 style).

Every table the game needs lives here. ``db.ensure_schema()`` keeps an
already-existing SQLite/PostgreSQL database in sync with this module by adding
missing tables *and* missing columns, so an old ``f1_bot.db`` keeps working
after the game grows new features.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Reference data: constructors, drivers, circuits
# --------------------------------------------------------------------------- #
class Team(Base):
    """A real-world F1 constructor available on the transfer market."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)
    country: Mapped[str] = mapped_column(String(40), default="")
    engine: Mapped[str] = mapped_column(String(40), default="")
    logo: Mapped[str] = mapped_column(String(16), default="🏎️")
    rating: Mapped[int] = mapped_column(Integer, default=70)  # overall 55..100
    price: Mapped[int] = mapped_column(Integer, default=10_000_000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Detailed chassis statistics (55..100) — all editable from the admin panel.
    aero: Mapped[int] = mapped_column(Integer, default=70)
    reliability: Mapped[int] = mapped_column(Integer, default=70)
    straight_line: Mapped[int] = mapped_column(Integer, default=70)
    cornering: Mapped[int] = mapped_column(Integer, default=70)
    tire_management: Mapped[int] = mapped_column(Integer, default=70)
    pit_crew: Mapped[int] = mapped_column(Integer, default=70)
    potential: Mapped[int] = mapped_column(Integer, default=70)

    owners: Mapped[list["UserTeam"]] = relationship(back_populates="team")

    def stat_lines(self) -> list[tuple[str, str, int]]:
        """(callback suffix, label, value) used by the admin editor."""
        return [
            ("rating", "⭐ Overall", self.rating),
            ("aero", "🌬️ Aerodynamics", self.aero),
            ("straight_line", "🚀 Straight-line speed", self.straight_line),
            ("cornering", "🌀 Cornering", self.cornering),
            ("reliability", "🔧 Reliability", self.reliability),
            ("tire_management", "🛞 Tire management", self.tire_management),
            ("pit_crew", "🛠️ Pit crew", self.pit_crew),
            ("potential", "📈 Development potential", self.potential),
        ]


class Driver(Base):
    """A real-world F1 driver available on the transfer market."""

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(3), unique=True)
    number: Mapped[int] = mapped_column(Integer, default=0)
    country: Mapped[str] = mapped_column(String(40), default="")
    team_name: Mapped[str] = mapped_column(String(80), default="")  # real 2026 seat
    avatar: Mapped[str] = mapped_column(String(16), default="👨‍✈️")
    price: Mapped[int] = mapped_column(Integer, default=1_000_000)
    salary: Mapped[int] = mapped_column(Integer, default=1_000_000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Detailed statistics (55..99) — all editable from the admin panel.
    overall: Mapped[int] = mapped_column(Integer, default=70)
    speed: Mapped[int] = mapped_column(Integer, default=70)
    qualifying: Mapped[int] = mapped_column(Integer, default=70)
    race_pace: Mapped[int] = mapped_column(Integer, default=70)
    overtaking: Mapped[int] = mapped_column(Integer, default=70)
    defending: Mapped[int] = mapped_column(Integer, default=70)
    wet_skill: Mapped[int] = mapped_column(Integer, default=70)
    tire_management: Mapped[int] = mapped_column(Integer, default=70)
    consistency: Mapped[int] = mapped_column(Integer, default=70)
    experience: Mapped[int] = mapped_column(Integer, default=70)
    potential: Mapped[int] = mapped_column(Integer, default=70)

    # Legacy aliases kept for the older race engine helpers.
    pace: Mapped[int] = mapped_column(Integer, default=70)

    def stat_lines(self) -> list[tuple[str, str, int]]:
        return [
            ("overall", "⭐ Overall", self.overall),
            ("speed", "⚡ Speed", self.speed),
            ("qualifying", "⏱️ Qualifying", self.qualifying),
            ("race_pace", "🏁 Race pace", self.race_pace),
            ("overtaking", "⚔️ Overtaking", self.overtaking),
            ("defending", "🛡️ Defending", self.defending),
            ("wet_skill", "🌧️ Wet skill", self.wet_skill),
            ("tire_management", "🛞 Tire management", self.tire_management),
            ("consistency", "🎯 Consistency", self.consistency),
            ("experience", "🧠 Experience", self.experience),
            ("potential", "📈 Potential", self.potential),
        ]


class Track(Base):
    """A championship round. Seeded from the real calendar, admin editable."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1, index=True)
    gp_name: Mapped[str] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(40), default="")
    circuit: Mapped[str] = mapped_column(String(80), default="")
    flag: Mapped[str] = mapped_column(String(8), default="")
    length_km: Mapped[float] = mapped_column(Float, default=5.0)
    laps: Mapped[int] = mapped_column(Integer, default=57)
    lap_record: Mapped[float] = mapped_column(Float, default=90.0)
    overtaking: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1 passability
    downforce: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1 requirement
    tire_degradation: Mapped[float] = mapped_column(Float, default=0.5)
    safety_car_prob: Mapped[float] = mapped_column(Float, default=0.3)
    rain_prob: Mapped[float] = mapped_column(Float, default=0.15)
    reliability_stress: Mapped[float] = mapped_column(Float, default=0.5)
    has_sprint: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def distance_km(self) -> float:
        return round(self.length_km * self.laps, 2)

    def stat_lines(self) -> list[tuple[str, str, float]]:
        return [
            ("laps", "🏁 Laps", self.laps),
            ("length_km", "📏 Length (km)", self.length_km),
            ("lap_record", "⏱️ Lap record (s)", self.lap_record),
            ("overtaking", "⚔️ Overtaking (0-1)", self.overtaking),
            ("downforce", "🌬️ Downforce (0-1)", self.downforce),
            ("tire_degradation", "🛞 Tire deg. (0-1)", self.tire_degradation),
            ("safety_car_prob", "🚨 Safety car (0-1)", self.safety_car_prob),
            ("rain_prob", "🌧️ Rain (0-1)", self.rain_prob),
            ("reliability_stress", "🔧 Stress (0-1)", self.reliability_stress),
        ]


# --------------------------------------------------------------------------- #
# Players
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)  # telegram user id
    username: Mapped[str] = mapped_column(String(64), default="")
    first_name: Mapped[str] = mapped_column(String(64), default="")
    balance: Mapped[int] = mapped_column(Integer, default=0)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)

    # VIP
    vip_level: Mapped[int] = mapped_column(Integer, default=0)
    vip_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vip_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vip_permanent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Roster
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    driver1_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    driver2_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)

    # Career statistics (all derived from real, stored race results)
    points: Mapped[int] = mapped_column(Integer, default=0)
    races_entered: Mapped[int] = mapped_column(Integer, default=0)
    race_entries_spent: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    podiums: Mapped[int] = mapped_column(Integer, default=0)
    dnfs: Mapped[int] = mapped_column(Integer, default=0)
    poles: Mapped[int] = mapped_column(Integer, default=0)
    fastest_laps: Mapped[int] = mapped_column(Integer, default=0)
    titles: Mapped[int] = mapped_column(Integer, default=0)
    race_points: Mapped[int] = mapped_column(Integer, default=0)
    total_earnings: Mapped[int] = mapped_column(Integer, default=0)
    total_spending: Mapped[int] = mapped_column(Integer, default=0)
    races_rained_wins: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Car development levels (0..upgrade_max_level)
    up_chassis: Mapped[int] = mapped_column(Integer, default=0)
    up_engine: Mapped[int] = mapped_column(Integer, default=0)
    up_aero: Mapped[int] = mapped_column(Integer, default=0)
    up_strategy: Mapped[int] = mapped_column(Integer, default=0)
    up_pitcrew: Mapped[int] = mapped_column(Integer, default=0)
    up_tires: Mapped[int] = mapped_column(Integer, default=0)
    up_reliability: Mapped[int] = mapped_column(Integer, default=0)
    up_fuel: Mapped[int] = mapped_column(Integer, default=0)
    up_ers: Mapped[int] = mapped_column(Integer, default=0)
    up_race_pace: Mapped[int] = mapped_column(Integer, default=0)
    up_quali_pace: Mapped[int] = mapped_column(Integer, default=0)

    # Current race weekend state
    quali_times: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quali_done: Mapped[bool] = mapped_column(Boolean, default=False)
    quali_avg: Mapped[float] = mapped_column(Float, default=0.0)

    # Daily bonus
    last_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)

    # Shop cosmetics / tyre compound kits
    tire_kits: Mapped[int] = mapped_column(Integer, default=0)
    badge: Mapped[str] = mapped_column(String(32), default="")

    # Interface language: "ru" / "uz" / "en" ("" = not picked yet)
    language: Mapped[str] = mapped_column(String(8), default="")

    # Moderation / anti-flood
    last_reset_key: Mapped[str] = mapped_column(String(10), default="")
    last_action_ts: Mapped[float] = mapped_column(Float, default=0.0)
    action_tokens: Mapped[int] = mapped_column(Integer, default=0)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or str(self.id)


class UserTeam(Base):
    """Purchase history: which user owns which constructor."""

    __tablename__ = "user_teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    price_paid: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    team: Mapped[Team] = relationship(back_populates="owners")


class UserDriver(Base):
    """Purchase history: which user owns which driver."""

    __tablename__ = "user_drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    price_paid: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    driver: Mapped[Driver] = relationship()


class Car(Base):
    """The player's current car build — the numbers the race engine reads."""

    __tablename__ = "cars"
    __table_args__ = (UniqueConstraint("user_id", name="uq_car_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    engine: Mapped[int] = mapped_column(Integer, default=0)
    aero: Mapped[int] = mapped_column(Integer, default=0)
    tires: Mapped[int] = mapped_column(Integer, default=0)
    reliability: Mapped[int] = mapped_column(Integer, default=0)
    fuel: Mapped[int] = mapped_column(Integer, default=0)
    ers: Mapped[int] = mapped_column(Integer, default=0)
    pit_crew: Mapped[int] = mapped_column(Integer, default=0)
    race_pace: Mapped[int] = mapped_column(Integer, default=0)
    quali_pace: Mapped[int] = mapped_column(Integer, default=0)
    strength: Mapped[float] = mapped_column(Float, default=70.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CarUpgrade(Base):
    """One developed part of a player's car (kept per player, mirrors User)."""

    __tablename__ = "car_upgrades"
    __table_args__ = (UniqueConstraint("user_id", "part", name="uq_car_part"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    part: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer, default=0)


class DriverUpgrade(Base):
    """Training level of one stat of one owned driver."""

    __tablename__ = "driver_upgrades"
    __table_args__ = (UniqueConstraint("user_id", "driver_id", "stat", name="uq_drv_stat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    stat: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- #
# Race weekend
# --------------------------------------------------------------------------- #
class Race(Base):
    __tablename__ = "races"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    gp_name: Mapped[str] = mapped_column(String(80))
    circuit: Mapped[str] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(40), default="")
    flag: Mapped[str] = mapped_column(String(8), default="")
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), nullable=True)
    length_km: Mapped[float] = mapped_column(Float, default=5.0)
    total_laps: Mapped[int] = mapped_column(Integer, default=57)
    lap_record: Mapped[float] = mapped_column(Float, default=90.0)
    overtaking: Mapped[float] = mapped_column(Float, default=0.5)
    downforce: Mapped[float] = mapped_column(Float, default=0.5)
    tire_degradation: Mapped[float] = mapped_column(Float, default=0.5)
    safety_car_prob: Mapped[float] = mapped_column(Float, default=0.3)
    rain_prob: Mapped[float] = mapped_column(Float, default=0.15)
    reliability_stress: Mapped[float] = mapped_column(Float, default=0.5)
    kind: Mapped[str] = mapped_column(String(8), default="gp")  # gp|sprint

    status: Mapped[str] = mapped_column(String(12), default="open")  # open|paused|live|finished|cancelled
    participants: Mapped[int] = mapped_column(Integer, default=0)
    organiser_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    registration_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_start_minutes: Mapped[int] = mapped_column(Integer, default=20)

    weather: Mapped[str] = mapped_column(String(16), default="dry")
    quali_done: Mapped[bool] = mapped_column(Boolean, default=False)
    grid: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{user_id, time, pos}]
    live_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RaceEntry(Base):
    """A team entered into a race weekend."""

    __tablename__ = "race_entries"
    __table_args__ = (UniqueConstraint("race_id", "user_id", name="uq_race_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fee_paid: Mapped[int] = mapped_column(Integer, default=0)
    quali_times: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quali_avg: Mapped[float] = mapped_column(Float, default=0.0)
    grid_pos: Mapped[int] = mapped_column(Integer, default=0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    race_times: Mapped[list | None] = mapped_column(JSON, nullable=True)
    race_avg: Mapped[float] = mapped_column(Float, default=0.0)
    finish_pos: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    money_won: Mapped[int] = mapped_column(Integer, default=0)
    gold_won: Mapped[int] = mapped_column(Integer, default=0)
    dnf: Mapped[bool] = mapped_column(Boolean, default=False)
    fastest_lap: Mapped[bool] = mapped_column(Boolean, default=False)
    pit_stops: Mapped[int] = mapped_column(Integer, default=0)
    strategy: Mapped[str] = mapped_column(String(24), default="")
    tyre: Mapped[str] = mapped_column(String(12), default="medium")
    gap: Mapped[float] = mapped_column(Float, default=0.0)
    total_time: Mapped[float] = mapped_column(Float, default=0.0)


class QualifyingResult(Base):
    """Stored qualifying sheet of one weekend."""

    __tablename__ = "qualifying_results"
    __table_args__ = (UniqueConstraint("race_id", "user_id", name="uq_quali_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    time: Mapped[float] = mapped_column(Float, default=0.0)
    laps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    weather: Mapped[str] = mapped_column(String(16), default="dry")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Result(Base):
    """Immutable result rows, used for leaderboards and history."""

    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    gp_name: Mapped[str] = mapped_column(String(80), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    prize: Mapped[int] = mapped_column(Integer, default=0)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    gap: Mapped[float] = mapped_column(Float, default=0.0)
    total_time: Mapped[float] = mapped_column(Float, default=0.0)
    pit_stops: Mapped[int] = mapped_column(Integer, default=0)
    fastest_lap: Mapped[bool] = mapped_column(Boolean, default=False)
    dnf: Mapped[bool] = mapped_column(Boolean, default=False)
    weather: Mapped[str] = mapped_column(String(16), default="dry")
    team_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RaceEvent(Base):
    """Every notable incident that happened during a simulated race."""

    __tablename__ = "race_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"), index=True)
    lap: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(24), default="")  # overtake|pit|crash|...
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    detail: Mapped[str] = mapped_column(String(200), default="")


class WeatherLog(Base):
    """Weather conditions observed during a race, in order."""

    __tablename__ = "weather"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"), index=True)
    lap: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="dry")


class Championship(Base):
    """One championship table (drivers or constructors) of the current season."""

    __tablename__ = "championships"

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[int] = mapped_column(Integer, default=2026)
    kind: Mapped[str] = mapped_column(String(16), default="drivers")  # drivers|constructors
    leader_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    leader_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)


class ChampionshipPoint(Base):
    """Points of one subject in one championship, updated after every race."""

    __tablename__ = "championship_points"
    __table_args__ = (UniqueConstraint("championship_id", "user_id", "team_id", name="uq_champ_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    championship_id: Mapped[int] = mapped_column(ForeignKey("championships.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    podiums: Mapped[int] = mapped_column(Integer, default=0)
    poles: Mapped[int] = mapped_column(Integer, default=0)
    fastest_laps: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- #
# Economy
# --------------------------------------------------------------------------- #
class Transaction(Base):
    """Every single cash/gold movement of every wallet."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(6), default="cash")  # cash|gold
    amount: Mapped[int] = mapped_column(Integer, default=0)  # signed
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(48), default="")
    note: Mapped[str] = mapped_column(String(160), default="")
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(24), default="")  # team|driver|upgrade|gold|vip|cosmetic|tire
    item_key: Mapped[str] = mapped_column(String(48), default="")
    item_name: Mapped[str] = mapped_column(String(80), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(6), default="cash")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyReward(Base):
    __tablename__ = "daily_rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    streak: Mapped[int] = mapped_column(Integer, default=1)
    cash: Mapped[int] = mapped_column(Integer, default=0)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- #
# Achievements
# --------------------------------------------------------------------------- #
class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(String(160), default="")
    icon: Mapped[str] = mapped_column(String(8), default="🏅")
    target: Mapped[int] = mapped_column(Integer, default=1)
    reward_cash: Mapped[int] = mapped_column(Integer, default=0)
    reward_gold: Mapped[int] = mapped_column(Integer, default=0)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_code", name="uq_user_ach"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    achievement_code: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Moderation, broadcasts, logging, settings
# --------------------------------------------------------------------------- #
class Ban(Base):
    __tablename__ = "bans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    admin_id: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class VipGrant(Base):
    __tablename__ = "vip"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    admin_id: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    days: Mapped[int] = mapped_column(Integer, default=0)  # 0 = permanent
    permanent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BroadcastLog(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, default=0)
    audience: Mapped[str] = mapped_column(String(16), default="all")
    text: Mapped[str] = mapped_column(Text, default="")
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32), default="")
    target_user: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[str] = mapped_column(String(24), default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BotStat(Base):
    """Single row with global bot counters for the admin panel."""

    __tablename__ = "bot_stats"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    races_created: Mapped[int] = mapped_column(Integer, default=0)
    races_finished: Mapped[int] = mapped_column(Integer, default=0)
    entries_total: Mapped[int] = mapped_column(Integer, default=0)
    fees_collected: Mapped[int] = mapped_column(Integer, default=0)
    prizes_paid: Mapped[int] = mapped_column(Integer, default=0)
    players_total: Mapped[int] = mapped_column(Integer, default=0)
    players_active: Mapped[int] = mapped_column(Integer, default=0)
    players_banned: Mapped[int] = mapped_column(Integer, default=0)
    cash_in_circulation: Mapped[int] = mapped_column(Integer, default=0)


class Setting(Base):
    """Key/value store for everything the admin can reconfigure at runtime."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")
