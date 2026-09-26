"""Garage: car development and driver training."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import get_user, session
from ..format import esc, money
from ..keyboards import back_home, btn, driver_training_list, garage_menu, kb, upgrade_list
from ..models import Driver
from ..render import show
from ..services import economy
from ..services import races as race_svc

router = Router(name="garage")


# --------------------------------------------------------------------------- #
# Garage home
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:garage")
@router.message(Command("garage"))
async def cb_garage(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = get_user(db, event.from_user.id, event.from_user.username or "", event.from_user.first_name or "")
        team = economy.get_team(db, user)
        pkg = race_svc.car_package(user, team)
        lines = ["🚗 <b>GARAGE</b>\n\n", f"💰 Balance: <b>{money(user.balance)}</b>\n\n"]
        if team:
            lines.append(
                f"🏎️ <b>Current Team:</b> {team.logo} {esc(team.name)}\n"
                f"    chassis OVR {team.rating} · effective car <b>{pkg['rating']:.1f}</b>\n"
            )
        else:
            lines.append("🏎️ <b>Current Team:</b> <i>none — buy a constructor in the Shop</i>\n")
        lines.append("\n")
        for slot in (1, 2):
            driver = _slot_driver(db, user, slot)
            if driver is None:
                lines.append(f"👨‍✈️ <b>Driver {slot}:</b> <i>empty seat</i>\n")
                continue
            levels = economy.driver_levels(db, user.id, driver.id)
            eff = race_svc.driver_package(driver, levels)
            lines.append(
                f"👨‍✈️ <b>Driver {slot}:</b> {driver.country} {esc(driver.name)} — "
                f"effective OVR <b>{eff['overall']:.1f}</b>\n"
            )
        lines.append("\n<b>Effective car package</b>\n")
        for key, label in (
            ("engine", "⚡ Engine"), ("aero", "🌬️ Aero"), ("cornering", "🌀 Cornering"),
            ("tires", "🛞 Tyres"), ("reliability", "🔧 Reliability"), ("fuel", "⛽ Fuel"),
            ("pit_crew", "🛠️ Pit crew"), ("strategy", "🧠 Strategy"),
        ):
            lines.append(f"  {label:<16} {pkg[key]:>5.1f}\n")
    await show(event, "".join(lines), garage_menu(team is not None))


# --------------------------------------------------------------------------- #
# Car development
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "gar:upgrades")
async def cb_upgrades(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lines = ["🔧 <b>CAR DEVELOPMENT</b>\n\n", f"💰 Balance: <b>{money(user.balance)}</b>\n\n"]
        items = []
        for key, (label, effect) in economy.UPGRADES.items():
            level = int(getattr(user, economy.CAR_COLUMN[key], 0) or 0)
            if level >= settings.upgrade_max_level:
                lines.append(f"✅ {label} — <b>MAX</b> (Lv {level})\n<i>{effect}</i>\n")
                continue
            cost = economy.upgrade_cost(level)
            lines.append(f"🔧 {label} — Lv <b>{level}</b> · next level {money(cost)}\n<i>{effect}</i>\n")
            items.append(btn(f"{label} Lv{level}", f"gub:{key}"))
    await show(cb, "".join(lines), upgrade_list(items, "nav:garage"))


@router.callback_query(F.data.startswith("gub:"))
async def cb_buy_upgrade(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        try:
            level, cost = economy.buy_upgrade(db, user, key)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("gar:upgrades")), alert=str(exc), show_alert=True)
            return
        label = economy.UPGRADES[key][0]
        rating = race_svc.car_strength(user, economy.get_team(db, user))
        text = (
            f"✅ <b>{esc(label)}</b> developed to level <b>{level}</b>.\n"
            f"💸 Cost: {money(cost)} · 💰 Balance: <b>{money(user.balance)}</b>\n"
            f"🏎️ Effective car rating: <b>{rating:.2f}</b>"
        )
    await show(cb, text, kb([[btn("🔧 Develop another part", "gar:upgrades")], *back_home("nav:garage")]))


# --------------------------------------------------------------------------- #
# Driver training
# --------------------------------------------------------------------------- #
def _slot_driver(db, user, slot: int) -> Driver | None:
    driver_id = getattr(user, f"driver{slot}_id", None)
    return db.get(Driver, driver_id) if driver_id else None


@router.callback_query(F.data.startswith("gar:driver:"))
async def cb_driver_training(cb: CallbackQuery) -> None:
    slot = int(cb.data.split(":")[2])
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        driver = _slot_driver(db, user, slot)
        if driver is None:
            await show(
                cb,
                f"👨‍✈️ <b>Driver {slot}</b> is an empty seat.\nSign a driver in the Shop first.",
                kb([[btn("🛒 Drivers", "mk:drivers:0")], *back_home("nav:garage")]),
            )
            return
        levels = economy.driver_levels(db, user.id, driver.id)
        eff = race_svc.driver_package(driver, levels)
        lines = [
            f"👨‍✈️ <b>{esc(driver.name)}</b> — training\n",
            f"<i>Effective overall {eff['overall']:.1f} (base {driver.overall})</i>\n\n",
            f"💰 Balance: <b>{money(user.balance)}</b>\n\n",
        ]
        items = []
        for key, (label, effect) in economy.DRIVER_STATS.items():
            level = int(levels.get(key, 0))
            base_value = getattr(driver, key, 0)
            if level >= settings.upgrade_max_level:
                lines.append(f"✅ {label} — <b>MAX</b> ({base_value} + {level * 0.5:.1f})\n<i>{effect}</i>\n")
                continue
            cost = economy.driver_upgrade_cost(level)
            lines.append(
                f"🎓 {label} — base {base_value}, Lv {level} · next {money(cost)}\n<i>{effect}</i>\n"
            )
            items.append(btn(f"{label} Lv{level}", f"dub:{driver.id}:{key}"))
    await show(cb, "".join(lines), driver_training_list(items, "nav:garage"))


@router.callback_query(F.data.startswith("dub:"))
async def cb_buy_driver_upgrade(cb: CallbackQuery) -> None:
    _, driver_id, stat = cb.data.split(":")
    driver_id = int(driver_id)
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        try:
            level, cost = economy.buy_driver_upgrade(db, user, driver_id, stat)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("nav:garage")), alert=str(exc), show_alert=True)
            return
        label = economy.DRIVER_STATS[stat][0]
        driver = db.get(Driver, driver_id)
        slot = 1 if user.driver1_id == driver_id else 2
        eff = race_svc.driver_package(driver, economy.driver_levels(db, user.id, driver_id))
        text = (
            f"✅ <b>{esc(label)}</b> trained to level <b>{level}</b>.\n"
            f"💸 Cost: {money(cost)} · 💰 Balance: <b>{money(user.balance)}</b>\n"
            f"👨‍✈️ {esc(driver.name) if driver else ''} effective OVR: <b>{eff['overall']:.2f}</b>"
        )
    await show(
        cb,
        text,
        kb([[btn("🎓 Train another attribute", f"gar:driver:{slot}")], *back_home("nav:garage")]),
    )
