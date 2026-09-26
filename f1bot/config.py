"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# The only account allowed to use the Super Admin Panel.
SUPER_ADMIN_ID = 7203210832


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = _str(name, "yes" if default else "no").lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _tuple_int(name: str, default: str) -> tuple[int, ...]:
    raw = _str(name, default)
    result = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            try:
                result.append(int(chunk))
            except ValueError:
                continue
    return tuple(result)


@dataclass(frozen=True)
class Settings:
    """All tunables of the game in one immutable object."""

    bot_token: str
    admin_ids: tuple[int, ...]
    database_url: str

    # Economy
    starting_cash: int
    starting_gold: int
    entry_fee: int
    prize_payouts: tuple[int, ...]
    sprint_payouts: tuple[int, ...]
    fastest_lap_bonus: int
    sprint_points: tuple[int, ...]
    points: tuple[int, ...]
    sell_ratio: float

    # Upgrades
    upgrade_base_cost: int
    upgrade_cost_step: int
    upgrade_max_level: int
    upgrade_gain: float
    driver_upgrade_base_cost: int
    driver_upgrade_cost_step: int

    # Gold shop reference price for one gold piece.
    gold_price_usd: int

    # Race simulation
    quali_laps: int
    race_laps_override: int  # 0 = use the real distance of the round
    ai_base_error: float
    max_participants: int
    min_participants: int
    registration_minutes: int

    # Live broadcast
    live_enabled: bool
    live_chunk: int
    live_delay: float
    auto_start_minutes: int
    lobby_notify: bool

    # Daily bonus
    daily_cooldown_hours: int
    daily_cash: int
    daily_gold: int
    daily_xp: int

    # Anti-flood
    max_actions_per_minute: int

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token)

    @property
    def super_admin_id(self) -> int:
        return SUPER_ADMIN_ID

    def is_super_admin(self, user_id: int | None) -> bool:
        return user_id is not None and int(user_id) == SUPER_ADMIN_ID

    def is_admin(self, user_id: int | None) -> bool:
        """Super admin plus the optional ADMIN_IDS operators."""
        if user_id is None:
            return False
        uid = int(user_id)
        return uid == SUPER_ADMIN_ID or uid in self.admin_ids


settings = Settings(
    bot_token=_str("BOT_TOKEN"),
    admin_ids=_tuple_int("ADMIN_IDS", ""),
    database_url=_str("DATABASE_URL", f"sqlite:///{BASE_DIR / 'f1_bot.db'}"),
    starting_cash=_int("STARTING_CASH", 200_000_000),
    starting_gold=_int("STARTING_GOLD", 0),
    entry_fee=_int("ENTRY_FEE", 1_000_000),
    prize_payouts=_tuple_int(
        "PRIZE_PAYOUTS",
        "100000000,75000000,60000000,50000000,40000000,30000000,25000000,20000000,15000000,10000000",
    ),
    sprint_payouts=_tuple_int(
        "SPRINT_PAYOUTS", "20000000,14000000,10000000,7000000,5000000,3000000,2000000,1000000"
    ),
    fastest_lap_bonus=_int("FASTEST_LAP_BONUS", 5_000_000),
    sprint_points=_tuple_int("SPRINT_POINTS", "8,7,6,5,4,3,2,1"),
    points=_tuple_int("POINTS", "25,18,15,12,10,8,6,4,2,1"),
    sell_ratio=_float("SELL_RATIO", 0.8),
    upgrade_base_cost=_int("UPGRADE_BASE_COST", 5_000_000),
    upgrade_cost_step=_int("UPGRADE_COST_STEP", 2_500_000),
    upgrade_max_level=_int("UPGRADE_MAX_LEVEL", 10),
    upgrade_gain=_float("UPGRADE_GAIN", 0.12),
    driver_upgrade_base_cost=_int("DRIVER_UPGRADE_BASE_COST", 4_000_000),
    driver_upgrade_cost_step=_int("DRIVER_UPGRADE_COST_STEP", 2_000_000),
    gold_price_usd=_int("GOLD_PRICE_USD", 100_000),
    quali_laps=_int("QUALI_LAPS", 3),
    race_laps_override=_int("RACE_LAPS_OVERRIDE", 0),
    ai_base_error=_float("AI_BASE_ERROR", 0.0035),
    max_participants=_int("MAX_PARTICIPANTS", 20),
    min_participants=_int("MIN_PARTICIPANTS", 4),
    registration_minutes=_int("REGISTRATION_MINUTES", 120),
    live_enabled=_bool("LIVE_BROADCAST", "yes"),
    live_chunk=_int("LIVE_CHUNK", 3),
    live_delay=_float("LIVE_DELAY", 0.8),
    auto_start_minutes=_int("AUTO_START_MINUTES", 20),
    lobby_notify=_bool("LOBBY_NOTIFY", "yes"),
    daily_cooldown_hours=_int("DAILY_COOLDOWN_HOURS", 24),
    daily_cash=_int("DAILY_CASH", 5_000_000),
    daily_gold=_int("DAILY_GOLD", 5),
    daily_xp=_int("DAILY_XP", 50),
    max_actions_per_minute=_int("MAX_ACTIONS_PER_MINUTE", 40),
)
