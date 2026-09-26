"""Runtime settings store: the values an admin can retune without a restart.

Falls back to :data:`f1bot.config.settings` so the game works even with an
empty ``settings`` table.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Setting

#: key -> (label, default provider, kind)
CATALOG: list[tuple[str, str, str, str]] = [
    ("entry_fee", "🎟️ Race entry fee", "money", lambda: settings.entry_fee),
    ("prize_1st", "🥇 Prize for P1", "money", lambda: settings.prize_payouts[0]),
    ("fastest_lap_bonus", "⚡ Fastest lap bonus", "money", lambda: settings.fastest_lap_bonus),
    ("daily_cash", "🎁 Daily bonus cash", "money", lambda: settings.daily_cash),
    ("daily_gold", "🪙 Daily bonus gold", "int", lambda: settings.daily_gold),
    ("daily_xp", "✨ Daily bonus XP", "int", lambda: settings.daily_xp),
    ("upgrade_base_cost", "🔧 Upgrade base cost", "money", lambda: settings.upgrade_base_cost),
    ("driver_upgrade_base_cost", "👨‍✈️ Driver training cost", "money", lambda: settings.driver_upgrade_base_cost),
    ("gold_price", "🪙 Price of 1 gold (cash)", "money", lambda: settings.gold_price_usd),
    ("vip_price_1", "⭐ VIP 1 price (gold)", "int", lambda: 50),
    ("vip_price_2", "⭐ VIP 2 price (gold)", "int", lambda: 120),
    ("vip_price_3", "⭐ VIP 3 price (gold)", "int", lambda: 250),
    ("vip_price_4", "⭐ VIP 4 price (gold)", "int", lambda: 450),
    ("vip_price_5", "⭐ VIP 5 price (gold)", "int", lambda: 800),
    ("max_participants", "👥 Max participants", "int", lambda: settings.max_participants),
    ("min_participants", "🚦 Min participants", "int", lambda: settings.min_participants),
    ("registration_minutes", "⏱️ Registration length (min)", "int", lambda: settings.auto_start_minutes),
    ("sell_ratio_pct", "💸 Resale ratio (%)", "int", lambda: int(settings.sell_ratio * 100)),
]

LABELS = {key: label for key, label, _kind, _default in CATALOG}
KINDS = {key: kind for key, _label, kind, _default in CATALOG}
DEFAULTS = {key: default() for key, _label, _kind, default in CATALOG}


def get_raw(db: Session, key: str) -> str | None:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def set_raw(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=str(value)[:200]))
    else:
        row.value = str(value)[:200]
    db.flush()


def get(db: Session, key: str):
    """Read a setting as int (all tunables are integers)."""
    raw = get_raw(db, key)
    if raw is None or raw == "":
        return int(DEFAULTS.get(key, 0))
    try:
        return int(float(raw))
    except ValueError:
        return int(DEFAULTS.get(key, 0))


def money(db: Session, key: str) -> int:
    return int(get(db, key))


def sell_ratio(db: Session) -> float:
    return max(0.0, min(1.0, get(db, "sell_ratio_pct") / 100.0))


def all_values(db: Session) -> list[tuple[str, str, int, bool]]:
    """(key, label, value, modified) for the admin settings screen."""
    out = []
    for key, label, _kind, _default in CATALOG:
        raw = get_raw(db, key)
        out.append((key, label, get(db, key), raw not in (None, "")))
    return out


def prize_payouts(db: Session) -> tuple[int, ...]:
    """Prize purse with P1 re-scaled from the admin-configurable value."""
    base = list(settings.prize_payouts)
    top = get(db, "prize_1st")
    if base and base[0] > 0:
        factor = top / base[0]
        base = [max(0, int(round(v * factor, -5))) for v in base]
    return tuple(base)


def entry_fee(db: Session) -> int:
    return get(db, "entry_fee")


def max_participants(db: Session) -> int:
    return max(2, get(db, "max_participants"))


def min_participants(db: Session) -> int:
    return max(1, min(get(db, "min_participants"), max_participants(db)))


def reset_key(db: Session, key: str) -> None:
    row = db.get(Setting, key)
    if row is not None:
        db.delete(row)
        db.flush()
