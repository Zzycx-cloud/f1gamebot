"""Transfer market and shop: teams, drivers, tyres, cosmetics, gold, VIP."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import get_user, session
from ..format import esc, money, rating_bar
from ..keyboards import (
    back_home,
    btn,
    buy_confirm,
    contracts_menu,
    driver_slot_picker,
    kb,
    market_list,
    pager_row,
    shop_menu,
    store_menu,
)
from ..models import Driver, Team
from ..render import show
from ..services import economy, shop, store, vip
from ..services import races as race_svc

router = Router(name="market")

PER_PAGE = 8


# --------------------------------------------------------------------------- #
# Shop home
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:market")
@router.message(Command("shop", "market"))
async def cb_shop(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = get_user(db, event.from_user.id, event.from_user.username or "", event.from_user.first_name or "")
        teams, _ = economy.market_teams(db, 0, PER_PAGE)
        drivers, _ = economy.market_drivers(db, 0, PER_PAGE)
        text = (
            "🛒 <b>SHOP</b>\n\n"
            f"💰 Balance: <b>{money(user.balance)}</b>   🪙 <b>{user.gold}</b>\n\n"
            f"🏎️ Constructors on the market: <b>{len(teams)}+</b>\n"
            f"👨‍✈️ Drivers on the market: <b>{len(drivers)}+</b>\n\n"
            "Choose a category."
        )
    await show(event, text, shop_menu())


@router.callback_query(F.data == "sto:menu")
async def cb_store(cb: CallbackQuery) -> None:
    await show(cb, "🛍️ <b>Shop extras</b>\n\nTyre packages really slow your degradation down.", store_menu())


# --------------------------------------------------------------------------- #
# Grid browser (read-only reference of the whole 2026 field)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:teams")
async def cb_all_teams(cb: CallbackQuery) -> None:
    page = 0
    with session() as db:
        teams, pages = economy.all_teams(db, page, 12)
        lines = ["🏎️ <b>THE 2026 GRID — CONSTRUCTORS</b>\n\n"]
        items = []
        for team in teams:
            lines.append(
                f"{team.logo} <b>{esc(team.name)}</b> — OVR {team.rating}, {money(team.price)}\n"
                f"    <i>{esc(team.engine)} · aero {team.aero} · power {team.straight_line} · "
                f"pit {team.pit_crew}</i>\n"
            )
            items.append(btn(f"{team.logo} {esc(team.name)}", f"mk:team:{team.id}:0"))
    rows = [[b] for b in items]
    if pages > 1:
        rows.append(pager_row(page, pages, "mk:teams:{page}"))
    rows += back_home("nav:menu")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data == "nav:drivers")
async def cb_all_drivers(cb: CallbackQuery) -> None:
    page = 0
    with session() as db:
        drivers, pages = economy.all_drivers(db, page, 12)
        owned = economy.owned_driver_ids(db)
        lines = ["👨‍✈️ <b>THE 2026 FIELD — DRIVERS</b>\n\n"]
        items = []
        for driver in drivers:
            tag = " 🔒" if driver.id in owned else ""
            lines.append(
                f"<code>#{driver.number:>2}</code> {driver.country} <b>{esc(driver.name)}</b> — "
                f"OVR {driver.overall}{tag}\n"
                f"    <i>{esc(driver.team_name)} · qual {driver.qualifying} · race {driver.race_pace} · "
                f"wet {driver.wet_skill}</i>\n"
            )
            items.append(btn(f"#{driver.number} {esc(driver.name)}", f"mk:driver:{driver.id}:0"))
    rows = [[b] for b in items]
    if pages > 1:
        rows.append(pager_row(page, pages, "mk:drivers:{page}"))
    rows += back_home("nav:menu")
    await show(cb, "".join(lines), kb(rows))


# --------------------------------------------------------------------------- #
# Constructors
# --------------------------------------------------------------------------- #
def _team_buttons(db, page: int) -> tuple[list[dict], int]:
    teams, pages = economy.market_teams(db, page, PER_PAGE)
    items = [
        btn(f"{t.logo} {esc(t.name)} — {money(t.price)} (OVR {t.rating})", f"mk:team:{t.id}:{page}")
        for t in teams
    ]
    return items, pages


@router.callback_query(F.data.startswith("mk:teams:"))
async def cb_team_list(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2] or 0)
    with session() as db:
        items, pages = _team_buttons(db, page)
    lines = ["🏎️ <b>CONSTRUCTORS' MARKET</b>\n<i>Prices are fixed by the sporting regulations.</i>\n\n"]
    if not items:
        lines.append("<i>Every constructor is already owned. Sell one to free the market.</i>")
    await show(
        cb,
        "".join(lines),
        market_list(items, page, pages, "mk:teams:{page}", "nav:market"),
    )


@router.callback_query(F.data.startswith("mk:team:"))
async def cb_team_detail(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    team_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    with session() as db:
        team = db.get(Team, team_id)
        if team is None:
            await show(cb, "Constructor not found.", kb(back_home("nav:market")))
            return
        owned = team.id in economy.owned_team_ids(db)
        lines = [
            f"{team.logo} <b>{esc(team.name)}</b>\n",
            f"<i>{esc(team.country)} · {esc(team.engine)}</i>\n\n",
            f"💵 Price: <b>{money(team.price)}</b>\n",
            f"⭐ Overall: <b>{team.rating}</b>\n\n",
        ]
        for _key, label, value in team.stat_lines():
            lines.append(f"{label:<22} {value:>3}  <i>{rating_bar(value)}</i>\n")
        if owned:
            lines.append("\n⚠️ Already under a contract elsewhere.")
    markup = (
        kb([[btn("💵 Buy this constructor", f"mk:buy:team:{team.id}")], *back_home(f"mk:teams:{page}")])
        if not owned
        else kb(back_home(f"mk:teams:{page}"))
    )
    await show(cb, "".join(lines), markup)


# --------------------------------------------------------------------------- #
# Drivers
# --------------------------------------------------------------------------- #
def _driver_buttons(db, page: int) -> tuple[list[dict], int]:
    drivers, pages = economy.market_drivers(db, page, PER_PAGE)
    items = [
        btn(f"#{d.number} {esc(d.name)} — {money(d.price)} (OVR {d.overall})", f"mk:driver:{d.id}:{page}")
        for d in drivers
    ]
    return items, pages


@router.callback_query(F.data.startswith("mk:drivers:"))
async def cb_driver_list(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2] or 0)
    with session() as db:
        items, pages = _driver_buttons(db, page)
    lines = ["👨‍✈️ <b>DRIVERS' MARKET</b>\n\n"]
    if not items:
        lines.append("<i>All drivers are signed. Check back next season.</i>")
    await show(cb, "".join(lines), market_list(items, page, pages, "mk:drivers:{page}", "nav:market"))


@router.callback_query(F.data.startswith("mk:driver:"))
async def cb_driver_detail(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    driver_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    with session() as db:
        driver = db.get(Driver, driver_id)
        if driver is None:
            await show(cb, "Driver not found.", kb(back_home("nav:market")))
            return
        owned = driver.id in economy.owned_driver_ids(db)
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        slots = economy.free_slots(user)
        lines = [
            f"👨‍✈️ <b>{esc(driver.name)}</b> {driver.country}  <code>#{driver.number}</code>\n",
            f"<i>{esc(driver.team_name)}</i>\n\n",
            f"💵 Price: <b>{money(driver.price)}</b>\n",
            f"🎟️ Weekend salary: <b>{money(driver.salary)}</b>\n",
            f"⭐ Overall: <b>{driver.overall}</b>\n\n",
        ]
        for _key, label, value in driver.stat_lines():
            lines.append(f"{label:<22} {value:>3}  <i>{rating_bar(value)}</i>\n")
        if owned:
            lines.append("\n⚠️ Already under contract.")
    if not owned and not slots:
        lines.append("\n⚠️ Both of your race seats are filled. Sell a driver first.")
    markup = (
        kb([[btn("💵 Sign this driver", f"mk:buy:driver:{driver.id}")], *back_home(f"mk:drivers:{page}")])
        if not owned and slots
        else kb(back_home(f"mk:drivers:{page}"))
    )
    await show(cb, "".join(lines), markup)


# --------------------------------------------------------------------------- #
# Purchase flow: view -> buy -> seat picker -> confirm -> done
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("mk:buy:"))
async def cb_buy_first_step(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")  # mk:buy:<kind>:<id>
    kind, item_id = parts[2], int(parts[3])
    if kind == "driver":
        with session() as db:
            user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
            slots = economy.free_slots(user)
            driver = db.get(Driver, item_id)
        if not slots:
            await show(cb, "Both race seats are filled. Sell a driver first.", kb(back_home("nav:market")))
            return
        await show(
            cb,
            f"👨‍✈️ <b>{esc(driver.name) if driver else ''}</b>\n\nPick the race seat for this driver.",
            driver_slot_picker(item_id, slots, "nav:market"),
        )
        return

    with session() as db:
        team = db.get(Team, item_id)
        if team is None:
            await show(cb, "Constructor not found.", kb(back_home("nav:market")))
            return
        price = team.price
        name, balance = team.name, _balance(db, cb)
    await show(
        cb,
        f"🏎️ <b>Confirm purchase</b>\n\n{esc(name)}\nPrice: <b>{money(price)}</b>\n"
        f"Your balance: <b>{money(balance)}</b>\nAfter purchase: <b>{money(balance - price)}</b>",
        buy_confirm(f"team:{item_id}", f"mk:team:{item_id}:0"),
    )


@router.callback_query(F.data.startswith("mk:buys:"))
async def cb_buy_seat_step(cb: CallbackQuery) -> None:
    _ns, _act, driver_id, slot = cb.data.split(":")
    driver_id, slot = int(driver_id), int(slot)
    with session() as db:
        driver = db.get(Driver, driver_id)
        if driver is None:
            await show(cb, "Driver not found.", kb(back_home("nav:market")))
            return
        price, balance = driver.price, _balance(db, cb)
    await show(
        cb,
        f"👨‍✈️ <b>Confirm purchase</b>\n\n{esc(driver.name)} → seat {slot}\n"
        f"Price: <b>{money(price)}</b>\nYour balance: <b>{money(balance)}</b>\n"
        f"After purchase: <b>{money(balance - price)}</b>",
        buy_confirm(f"driver:{driver_id}:{slot}", f"mk:driver:{driver_id}:0"),
    )


@router.callback_query(F.data.startswith("mk:confirm:"))
async def cb_confirm_purchase(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    kind = parts[2]
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        try:
            if kind == "team":
                team = economy.buy_team(db, user, int(parts[3]))
                text = (
                    f"✅ <b>Purchase complete!</b>\n\n{team.logo} <b>{esc(team.name)}</b> is yours.\n"
                    f"💰 New balance: <b>{money(user.balance)}</b>\n"
                    f"⭐ Car rating: <b>{race_svc.car_strength(user, team):.1f}</b>"
                )
                markup = kb([[btn("🚗 Garage", "nav:garage")], *back_home("nav:menu")])
            else:
                driver = economy.buy_driver(db, user, int(parts[3]), int(parts[4]))
                text = (
                    f"✅ <b>Contract signed!</b>\n\n👨‍✈️ <b>{esc(driver.name)}</b> joins your line-up.\n"
                    f"💰 New balance: <b>{money(user.balance)}</b>\n"
                    f"🎟️ Weekend salary: <b>{money(driver.salary)}</b>"
                )
                markup = kb([[btn("🏁 Race", "nav:races")], *back_home("nav:menu")])
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("nav:market")), alert=str(exc), show_alert=True)
            return
    await show(cb, text, markup)


def _balance(db, event) -> int:
    from ..db import get_user

    return get_user(db, event.from_user.id, event.from_user.username or "", event.from_user.first_name or "").balance


@router.callback_query(F.data == "mk:refresh")
async def cb_refresh_prices(cb: CallbackQuery) -> None:
    with session() as db:
        from ..services import adminlog

        if not settings.is_admin(cb.from_user.id):
            await show(cb, "Only the sporting director can reprice the market.", kb(back_home("nav:market")))
            return
        count = economy.refresh_driver_prices(db)
        adminlog.log(db, cb.from_user.id, "REFRESH_PRICES", None, count, "drivers")
    await show(cb, f"🔃 Reprised <b>{count}</b> drivers from the rating curve.", kb(back_home("nav:market")))


# --------------------------------------------------------------------------- #
# My contracts
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "mk:mine")
async def cb_my_contracts(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        team = economy.get_team(db, user)
        drivers = economy.get_drivers(db, user)
        ratio = int(store.sell_ratio(db) * 100)
        lines = ["💼 <b>MY CONTRACTS</b>\n\n"]
        rows: list[list[dict]] = []
        if team:
            payout = int(team.price * store.sell_ratio(db))
            lines.append(f"🏎️ <b>{esc(team.name)}</b> — OVR {team.rating}, resale {money(payout)}\n")
            rows.append([btn(f"💸 Sell {esc(team.name)}", f"mk:sellc:team:{team.id}")])
        else:
            lines.append("🏎️ <i>no constructor</i>\n")
        lines.append("\n")
        for driver in drivers:
            payout = int(driver.price * store.sell_ratio(db))
            lines.append(
                f"👨‍✈️ <b>{esc(driver.name)}</b> <code>#{driver.number}</code> — OVR {driver.overall}, "
                f"resale {money(payout)}\n"
            )
            rows.append([btn(f"💸 Sell {esc(driver.name)}", f"mk:sellc:driver:{driver.id}")])
        if not drivers:
            lines.append("👨‍✈️ <i>no drivers</i>\n")
        lines.append(f"\n<i>Selling returns {ratio}% of what you paid.</i>")
    rows += back_home("nav:market")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data.startswith("mk:sellc:"))
async def cb_confirm_sell(cb: CallbackQuery) -> None:
    kind, item_id = cb.data.split(":")[2], int(cb.data.split(":")[3])
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        label = "Item"
        if kind == "team":
            team = db.get(Team, item_id)
            label = team.name if team else "Constructor"
            payout = int(team.price * store.sell_ratio(db)) if team else 0
        else:
            driver = db.get(Driver, item_id)
            label = driver.name if driver else "Driver"
            payout = int(driver.price * store.sell_ratio(db)) if driver else 0
    await show(
        cb,
        f"💸 <b>Sell {esc(label)}?</b>\n\nYou will receive <b>{money(payout)}</b>.\n"
        "This cannot be undone.",
        kb(
            [
                [btn("✅ Confirm", f"mk:sell:{kind}:{item_id}"), btn("❌ Cancel", "mk:mine")],
                *back_home("nav:menu"),
            ]
        ),
    )


@router.callback_query(F.data.startswith("mk:sell:"))
async def cb_sell(cb: CallbackQuery) -> None:
    kind, item_id = cb.data.split(":")[2], int(cb.data.split(":")[3])
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        try:
            payout = (
                economy.sell_team(db, user, item_id)
                if kind == "team"
                else economy.sell_driver(db, user, item_id)
            )
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("mk:mine")), alert=str(exc), show_alert=True)
            return
    await show(
        cb,
        f"✅ Sold for <b>{money(payout)}</b>.\n💰 New balance: <b>{money(user.balance)}</b>",
        kb([[btn("💼 My contracts", "mk:mine")], *back_home("nav:menu")]),
    )


# --------------------------------------------------------------------------- #
# Tyres / cosmetics / gold / vip storefronts
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "sto:tires")
async def cb_store_tires(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        owned = shop.owned_keys(db, user.id, "tire")
        lines = [
            "🛞 <b>TYRE DEVELOPMENT</b>\n\n",
            f"💰 Balance: <b>{money(user.balance)}</b>\n",
            f"Current tyre package bonus: <b>+{shop.kit_gain(db, user):.0f}</b>\n\n",
            "<i>Each package permanently lowers your tyre degradation in the race simulation.</i>\n\n",
        ]
        rows = []
        for key, (label, desc, price, gain) in shop.TIRE_KITS.items():
            mark = "✅" if key in owned else "💵"
            lines.append(f"{mark} <b>{label}</b> — {money(price)} (+{gain:.0f} tyre package)\n<i>{desc}</i>\n")
            if key not in owned:
                rows.append([btn(f"💵 Buy {label}", f"stb:tire:{key}")])
    rows += back_home("nav:market")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data == "sto:cosmetics")
async def cb_store_cosmetics(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        owned = shop.owned_keys(db, user.id, "cosmetic")
        lines = ["🎨 <b>COSMETICS</b>\n\n", f"💰 Balance: <b>{money(user.balance)}</b>\n\n"]
        rows = []
        for key, (label, desc, price) in shop.COSMETICS.items():
            mark = "✅" if key in owned else "💵"
            lines.append(f"{mark} <b>{label}</b> — {money(price)}\n<i>{desc}</i>\n")
            if key not in owned:
                rows.append([btn(f"💵 Buy {label}", f"stb:cos:{key}")])
    rows += back_home("nav:market")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data == "sto:gold")
async def cb_store_gold(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lines = [
            "🪙 <b>GOLD SHOP</b>\n\n",
            f"💰 Balance: <b>{money(user.balance)}</b>\n",
            f"🪙 Gold: <b>{user.gold}</b>\n\n",
            "<i>Gold pays for VIP and is awarded on the podium.</i>\n\n",
        ]
        rows = []
        for key, (amount, price) in shop.GOLD_PACKS.items():
            lines.append(f"🪙 <b>{amount} gold</b> — {money(price)}\n")
            rows.append([btn(f"💵 Buy {amount} 🪙", f"stb:gold:{key}")])
    rows += back_home("nav:market")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data == "sto:vip")
async def cb_store_vip(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lines = [
            "⭐ <b>VIP STORE</b> — pay with gold\n\n",
            f"🪙 Your gold: <b>{user.gold}</b>\n",
            f"Your level: <b>{vip.label(user)}</b>\n\n",
        ]
        rows = []
        for level in range(1, vip.MAX_LEVEL + 1):
            name, prize, gold_back, daily = vip.PERKS[level]
            price = store.get(db, f"vip_price_{level}")
            lines.append(
                f"⭐ <b>{name}</b> — {price} 🪙 / 30 days\n"
                f"    prize +{int(prize * 100)}% · daily ×{daily}"
                + (f" · {gold_back} 🪙 per race" if gold_back else "")
                + "\n"
            )
            rows.append([btn(f"🪙 Buy {name} ({price})", f"stb:vip:{level}")])
    rows += back_home("nav:market")
    await show(cb, "".join(lines), kb(rows))


@router.callback_query(F.data.startswith("stb:"))
async def cb_store_buy(cb: CallbackQuery) -> None:
    kind, key = cb.data.split(":")[1], cb.data.split(":")[2]
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        try:
            if kind == "tire":
                label, price = shop.buy_tire_kit(db, user, key)
                text = (
                    f"✅ <b>{esc(label)}</b> installed.\n"
                    f"💸 Paid: {money(price)} · 💰 Balance: <b>{money(user.balance)}</b>\n"
                    f"🛞 Tyre package bonus is now <b>+{shop.kit_gain(db, user):.0f}</b>."
                )
            elif kind == "cos":
                label, price = shop.buy_cosmetic(db, user, key)
                text = f"✅ <b>{esc(label)}</b> unlocked.\n💸 Paid: {money(price)} · 💰 Balance: <b>{money(user.balance)}</b>"
            elif kind == "gold":
                amount, price = shop.buy_gold(db, user, key)
                text = (
                    f"✅ Bought <b>{amount} 🪙</b>.\n💸 Paid: {money(price)}\n"
                    f"🪙 Gold balance: <b>{user.gold}</b>"
                )
            elif kind == "vip":
                spent, days = shop.buy_vip(db, user, int(key))
                text = (
                    f"✅ <b>{vip.label(user)}</b> activated for {days} days.\n"
                    f"🪙 Spent: {spent}\n💰 Prize money multiplier: <b>×{vip.prize_multiplier(user):.2f}</b>"
                )
            else:
                await show(cb, "Unknown item.", kb(back_home("nav:market")))
                return
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("nav:market")), alert=str(exc), show_alert=True)
            return
    await show(cb, text, kb([[btn("🛒 Shop", "nav:market")], *back_home("nav:menu")]))
