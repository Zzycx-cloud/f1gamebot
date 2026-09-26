"""Shop categories that are not the transfer market: tyres, cosmetics, gold, VIP.

Every item here has a real, measurable effect:
* tyre kits lower the car's tyre degradation in the simulation,
* cosmetics change what other players see next to your name,
* gold packs move cash into the gold wallet,
* VIP packs set the VIP level/expiry that the bonuses read.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Driver, Team, User
from . import achievements, store, vip, wallet
from .wallet import NotEnoughFunds  # re-exported for the handlers

#: key -> (label, description, price in cash, tyre-management gain)
TIRE_KITS: dict[str, tuple[str, str, int, float]] = {
    "warmers": (
        "🔥 Tyre warmers",
        "Bringing the tyres into their window earlier: slower degradation.",
        15_000_000,
        2.0,
    ),
    "blankets": (
        "🧣 Heated blankets",
        "Keep the compound stable through a long stint.",
        25_000_000,
        3.0,
    ),
    "sensor": (
        "📟 Tyre sensors",
        "Live telemetry lets you push without cooking the rubber.",
        40_000_000,
        4.0,
    ),
    "construction": (
        "🧪 Construction research",
        "Partner with the supplier on a tougher carcass.",
        65_000_000,
        6.0,
    ),
}

#: key -> (label, description, price in cash)
COSMETICS: dict[str, tuple[str, str, int]] = {
    "badge_rookie": ("🎖️ Rookie badge", "Shown next to your name in every standings list.", 5_000_000),
    "badge_veteran": ("🎗️ Veteran badge", "For managers who never quit.", 15_000_000),
    "badge_champion": ("👑 Champion badge", "The loudest flex in the paddock.", 60_000_000),
    "livery_gold": ("✨ Gold livery", "Your car name is decorated in results.", 30_000_000),
    "livery_neon": ("💠 Neon livery", "Chrome-flake paint job.", 30_000_000),
    "cap_classic": ("🧢 Classic cap", "Old-school wool cap.", 8_000_000),
}

#: key -> (amount of gold, price in cash)
GOLD_PACKS: dict[str, tuple[int, int]] = {
    "g10": (10, 1_000_000),
    "g60": (60, 5_000_000),
    "g150": (150, 11_000_000),
    "g400": (400, 26_000_000),
    "g1000": (1000, 58_000_000),
}


def kit_gain(db: Session, user: User) -> float:
    """Total tyre-management bonus the player bought in the shop."""
    return float(user.tire_kits or 0)


def buy_tire_kit(db: Session, user: User, key: str) -> tuple[str, int]:
    item = TIRE_KITS.get(key)
    if item is None:
        raise ValueError("Unknown tyre kit.")
    owned = db.scalar(
        select(wallet.Purchase).where(
            wallet.Purchase.user_id == user.id,
            wallet.Purchase.category == "tire",
            wallet.Purchase.item_key == key,
        )
    )
    if owned is not None:
        raise ValueError("You already own this tyre package.")
    label, _desc, price, gain = item
    if int(user.balance) < price:
        raise ValueError(f"Not enough money. {label} costs {price:,}.")
    wallet.spend_cash(db, user, price, "BUY_TYRES", label)
    user.tire_kits = int(user.tire_kits or 0) + int(gain)
    wallet.log_purchase(db, user, "tire", key, label, price)
    db.flush()
    achievements.check(db, user)
    return label, price


def buy_cosmetic(db: Session, user: User, key: str) -> tuple[str, int]:
    item = COSMETICS.get(key)
    if item is None:
        raise ValueError("Unknown cosmetic.")
    owned = db.scalar(
        select(wallet.Purchase).where(
            wallet.Purchase.user_id == user.id,
            wallet.Purchase.category == "cosmetic",
            wallet.Purchase.item_key == key,
        )
    )
    if owned is not None:
        raise ValueError("You already own this.")
    label, _desc, price = item
    if int(user.balance) < price:
        raise ValueError(f"Not enough money. {label} costs {price:,}.")
    wallet.spend_cash(db, user, price, "BUY_COSMETIC", label)
    wallet.log_purchase(db, user, "cosmetic", key, label, price)
    if key.startswith("badge_"):
        user.badge = label
    db.flush()
    return label, price


def owned_keys(db: Session, user_id: int, category: str) -> set[str]:
    rows = db.scalars(
        select(wallet.Purchase.item_key).where(
            wallet.Purchase.user_id == user_id, wallet.Purchase.category == category
        )
    )
    return set(rows)


def buy_gold(db: Session, user: User, key: str) -> tuple[int, int]:
    pack = GOLD_PACKS.get(key)
    if pack is None:
        raise ValueError("Unknown gold pack.")
    amount, price = pack
    if int(user.balance) < price:
        raise ValueError(f"Not enough money. This pack costs {price:,}.")
    wallet.spend_cash(db, user, price, "BUY_GOLD", f"{amount} gold")
    wallet.add_gold(db, user, amount, "BUY_GOLD", f"pack {key}")
    wallet.log_purchase(db, user, "gold", key, f"{amount} gold", price)
    db.flush()
    achievements.check(db, user)
    return amount, price


def buy_vip(db: Session, user: User, level: int, days: int = 30) -> tuple[int, int]:
    """Pay gold for a VIP level. Returns (gold spent, days granted)."""
    if not 1 <= level <= vip.MAX_LEVEL:
        raise ValueError("VIP levels run from 1 to 5.")
    if int(user.vip_level or 0) > level:
        raise ValueError("You already hold a higher VIP level.")
    price = store.get(db, f"vip_price_{level}")
    if int(user.gold) < price:
        raise ValueError(f"Not enough gold. VIP {level} costs {price} 🪙.")
    wallet.spend_gold(db, user, price, "BUY_VIP", f"VIP {level} for {days} days")
    vip.grant(db, user, level, days)
    wallet.log_purchase(db, user, "vip", f"vip{level}", f"VIP {level}", price, currency=wallet.GOLD)
    db.flush()
    achievements.check(db, user)
    return price, days
