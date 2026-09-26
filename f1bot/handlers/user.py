"""Player screens: welcome, main menu, profile, wallet, VIP, bonus, statistics."""

from __future__ import annotations

from datetime import timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import get_user, session
from ..format import esc, money
from ..keyboards import (
    achievements_menu,
    back_home,
    btn,
    daily_menu,
    kb,
    main_menu,
    nav_row,
    pager_row,
    settings_menu,
    stats_menu,
    transactions_menu,
    vip_menu,
    wallet_menu,
)
from ..models import Driver, Race, Result, Team, User
from ..render import show
from ..services import achievements, bonus, economy, stats, store, vip, wallet as wallet_svc
from ..services import races as race_svc

router = Router(name="user")


def player(db, telegram_user) -> User:
    return get_user(db, telegram_user.id, telegram_user.username or "", telegram_user.first_name or "")


def is_admin(user_id: int | None) -> bool:
    return settings.is_admin(user_id)


# --------------------------------------------------------------------------- #
# Welcome / main menu
# --------------------------------------------------------------------------- #
def welcome_text(user: User) -> str:
    name = esc(user.first_name or user.username or "Driver")
    return (
        "🏎️ <b>F1 GAME</b> — season 2026\n\n"
        f"Welcome, <b>{name}</b>!\n"
        f"💰 Budget: <b>{money(user.balance)}</b>   🪙 Gold: <b>{user.gold}</b>\n\n"
        "How the season works:\n"
        "1️⃣ Buy a <b>constructor</b> in the Shop\n"
        "2️⃣ Sign <b>two drivers</b> for your race seats\n"
        "3️⃣ Develop the <b>garage</b> and train your drivers\n"
        "4️⃣ Join a <b>Grand Prix</b>, set a qualifying lap, race for prize money\n"
        "5️⃣ Win the <b>Championship</b> across 24 real rounds\n\n"
        "Everything below is a button — no commands needed."
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    with session() as db:
        user = player(db, message.from_user)
        text = welcome_text(user)
        admin = is_admin(user.id)
    await message.answer(text, reply_markup=main_menu(admin), parse_mode="HTML")


@router.message(Command("menu", "start"))
@router.message(F.text.lower().regexp(r"^(menu|main menu|🏠 main menu|start)$"))
async def cmd_menu(message: Message) -> None:
    with session() as db:
        user = player(db, message.from_user)
        text, admin = welcome_text(user), is_admin(user.id)
    await message.answer(text, reply_markup=main_menu(admin), parse_mode="HTML")


@router.callback_query(F.data == "nav:menu")
async def cb_menu(cb: CallbackQuery) -> None:
    with session() as db:
        user = player(db, cb.from_user)
        text, admin = welcome_text(user), is_admin(user.id)
    await show(cb, text, main_menu(admin))


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:profile")
@router.message(Command("profile"))
async def cb_profile(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        team = economy.get_team(db, user)
        drivers = economy.get_drivers(db, user)
        value = economy.roster_value(db, user)
        rating = stats.rating(user)
        from ..services import moderation

        moderation.sync_expired(db)
        ban = moderation.active_ban(db, user.id)

    handle = (
        f"  <a href='https://t.me/{esc(user.username)}'>@{esc(user.username)}</a>" if user.username else ""
    )
    seats = "\n".join(
        f"👨‍✈️ Driver {idx}: <b>{esc(d.name)}</b> <code>#{d.number}</code> {d.country} — OVR {d.overall}"
        for idx, d in enumerate(drivers, start=1)
    ) or "👨‍✈️ <i>no drivers under contract</i>"
    while len(drivers) < 2:
        seats += f"\n👨‍✈️ Driver {len(drivers) + 1}: <i>empty seat</i>"
        drivers.append(None)  # type: ignore[arg-type]

    races = max(1, user.races_entered)
    text = (
        f"👤 <b>{esc(user.first_name or user.username or user.id)}</b>{handle}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"💰 Cash: <b>{money(user.balance)}</b>\n"
        f"🪙 Gold: <b>{user.gold}</b>\n"
        f"⭐ VIP: <b>{vip.label(user)}</b>\n\n"
        f"🏎️ Team: <b>{esc(team.name) if team else '— none —'}</b>"
        + (f" (OVR {team.rating})" if team else "")
        + f"\n{seats}\n\n"
        f"🏁 Races: <b>{user.races_entered}</b>\n"
        f"🥇 Wins: <b>{user.wins}</b>\n"
        f"🏆 Podiums: <b>{user.podiums}</b>\n"
        f"💥 DNFs: <b>{user.dnfs}</b>\n"
        f"👑 Championships: <b>{user.titles}</b>\n"
        f"📊 Rating: <b>{rating}</b>\n"
        f"💵 Total earnings: <b>{money(user.total_earnings)}</b>\n"
        f"💸 Total spending: <b>{money(user.total_spending)}</b>\n"
        f"🏁 Championship points: <b>{user.race_points}</b>\n"
        f"⏱️ Poles: <b>{user.poles}</b>\n"
        f"⚡ Fastest laps: <b>{user.fastest_laps}</b>\n"
        f"🎯 Win rate: <b>{100.0 * user.wins / races:.1f}%</b>\n"
        f"💼 Contracts value: <b>{money(value)}</b>\n"
        + (f"\n🚫 <b>{esc(moderation.describe(ban))}</b>" if ban else "")
    )
    markup = kb(
        [
            [btn("💰 Wallet", "nav:wallet"), btn("🚗 Garage", "nav:garage")],
            [btn("🏁 Race", "nav:races"), btn("🏆 Championship", "nav:standings")],
            *back_home("nav:menu"),
        ]
    )
    await show(event, text, markup)


# --------------------------------------------------------------------------- #
# Wallet
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:wallet")
@router.message(Command("wallet"))
async def cb_wallet(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        recent = wallet_svc.history(db, user.id, limit=5)
    lines = [
        "💰 <b>WALLET</b>\n\n",
        f"💵 Cash: <b>{money(user.balance)}</b>\n",
        f"🪙 Gold: <b>{user.gold}</b>\n\n",
        "<i>Recent transactions</i>\n",
    ]
    if not recent:
        lines.append("<i>Nothing yet.</i>")
    for txn in recent:
        sign = "+" if txn.amount > 0 else ""
        icon = "💵" if txn.currency == "cash" else "🪙"
        amount = money(txn.amount) if txn.currency == "cash" else f"{txn.amount}"
        lines.append(f"{icon} {sign}{amount} — {esc(txn.reason)}\n")
    await show(event, "".join(lines), wallet_menu())


@router.callback_query(F.data.startswith("wal:tx"))
async def cb_transactions(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    gold_only = parts[1] == "txg"
    from ..services import wallet as wallet_svc

    per = 10
    with session() as db:
        user = player(db, cb.from_user)
        total = wallet_svc.history_count(db, user.id, "gold" if gold_only else None)
        rows = wallet_svc.history(db, user.id, "gold" if gold_only else None, limit=per, offset=page * per)
    pages = max(1, -(-total // per))
    lines = [f"📜 <b>TRANSACTIONS</b> ({total})\n\n"]
    if not rows:
        lines.append("<i>No transactions yet.</i>")
    for txn in rows:
        sign = "+" if txn.amount > 0 else ""
        icon = "💵" if txn.currency == "cash" else "🪙"
        amount = money(txn.amount) if txn.currency == "cash" else f"{txn.amount}"
        when = txn.created_at.strftime("%d.%m %H:%M") if txn.created_at else ""
        lines.append(
            f"{icon} <b>{sign}{amount}</b> · {esc(txn.reason)}\n   <i>{when} · balance "
            + (money(txn.balance_after) if txn.currency == "cash" else str(txn.balance_after))
            + (f" · {esc(txn.note)}" if txn.note else "")
            + "</i>\n"
        )
    await show(cb, "".join(lines), transactions_menu(page, pages))


# --------------------------------------------------------------------------- #
# Daily bonus
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:daily")
@router.message(Command("daily"))
async def cb_daily(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        ready = bonus.can_claim(user)
        left = bonus.next_in(user)
        history = bonus.history(db, user.id, limit=5)
    streak = "\n".join(
        f"Day {row.streak}: 💵{money(row.cash)} 🪙{row.gold} ✨{row.xp}" + (f" · {esc(row.bonus)}" if row.bonus else "")
        for row in history
    ) or "<i>No bonuses claimed yet.</i>"
    text = (
        "🎁 <b>DAILY BONUS</b>\n\n"
        + ("✅ Bonus is ready to claim!\n" if ready else f"⏳ Next bonus in <b>{left}</b>\n")
        + f"🔥 Current streak: <b>{user.daily_streak}</b>\n\n"
        f"Base reward: 💵{money(settings.daily_cash)} 🪙{settings.daily_gold} ✨{settings.daily_xp}\n"
        "<i>The reward scales with your streak and your VIP level, and a random bonus can pop.</i>\n\n"
        f"<i>Your last claims</i>\n{streak}"
    )
    await show(event, text, daily_menu(ready))


@router.callback_query(F.data == "dly:claim")
async def cb_claim(cb: CallbackQuery) -> None:
    from ..services import wallet as wallet_svc

    with session() as db:
        user = player(db, cb.from_user)
        try:
            claim = bonus.claim(db, user)
        except ValueError as exc:
            await show(cb, f"🎁 <b>Daily bonus</b>\n\n{esc(exc)}", daily_menu(False), alert=str(exc), show_alert=True)
            return
        unlocked = achievements.check(db, user)
        text = (
            "🎁 <b>Daily bonus claimed!</b>\n\n"
            f"💵 Cash: <b>+{money(claim.cash)}</b>\n"
            f"🪙 Gold: <b>+{claim.gold}</b>\n"
            f"✨ XP: <b>+{claim.xp}</b>\n"
            + (f"🎲 Bonus: <b>{esc(claim.bonus)}</b>\n" if claim.bonus else "")
            + f"🔥 Streak: <b>{claim.streak}</b>\n\n"
            f"💰 New balance: <b>{money(user.balance)}</b> · 🪙 <b>{user.gold}</b>\n"
            f"⏳ Next bonus in <b>{claim.next_in_minutes}</b> minutes"
        )
        if unlocked:
            text += "\n\n🏅 Unlocked: " + ", ".join(esc(t) for t in unlocked)
    await show(cb, text, daily_menu(False))


# --------------------------------------------------------------------------- #
# VIP
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:vip")
@router.message(Command("vip"))
async def cb_vip(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        level = vip.refresh(user)
        lines = [
            "⭐ <b>VIP CLUB</b>\n\n",
            f"Your level: <b>{vip.label(user)}</b>\n",
            f"🪙 Your gold: <b>{user.gold}</b>\n\n",
        ]
        for lvl in range(1, vip.MAX_LEVEL + 1):
            name, prize, gold_back, daily = vip.PERKS[lvl]
            price = store.get(db, f"vip_price_{lvl}")
            mark = "✅" if level >= lvl else "🔒"
            lines.append(
                f"{mark} <b>{name}</b> — {price} 🪙\n"
                f"    prize +{int(prize * 100)}% · daily ×{daily}"
                + (f" · {gold_back} 🪙 per race" if gold_back else "")
                + "\n"
            )
        if user.vip_expires_at is not None and not user.vip_permanent:
            expires = user.vip_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            lines.append(f"\n⏳ Expires: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>")
    await show(event, "".join(lines), vip_menu())


@router.callback_query(F.data.startswith("vip:lvl:"))
async def cb_vip_level(cb: CallbackQuery) -> None:
    level = int(cb.data.split(":")[2])
    name, prize, gold_back, daily = vip.PERKS.get(level, vip.PERKS[1])
    with session() as db:
        price = store.get(db, f"vip_price_{level}")
    text = (
        f"⭐ <b>{name}</b>\n\n"
        f"Price: <b>{price} 🪙</b> (30 days)\n\n"
        f"• Prize money <b>+{int(prize * 100)}%</b>\n"
        f"• Daily bonus <b>×{daily}</b>\n"
        + (f"• <b>{gold_back} 🪙</b> gold after every race\n" if gold_back else "")
        + "\nBuy it in the Shop → ⭐ VIP."
    )
    await show(cb, text, kb([[btn("⭐ Buy VIP", "sto:vip")], *back_home("nav:vip")]))


# --------------------------------------------------------------------------- #
# Achievements
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:achievements")
@router.message(Command("achievements"))
async def cb_achievements(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        achievements.check(db, user)
        rows = achievements.progress_rows(db, user)
    got = sum(1 for r in rows if r[5])
    lines = [f"🏅 <b>ACHIEVEMENTS</b> — {got}/{len(rows)}\n\n"]
    items = []
    for icon, name, description, value, target, unlocked in rows:
        mark = "✅" if unlocked else "🔒"
        lines.append(f"{mark} {icon} <b>{esc(name)}</b> — <i>{esc(description)}</i>\n")
        if not unlocked:
            lines.append(f"    <i>progress {min(value, target)}/{target}</i>\n")
        items.append(btn(f"{mark} {icon} {name}", f"ach:{name[:18]}"))
    await show(event, "".join(lines), achievements_menu(items))


@router.callback_query(F.data.startswith("ach:"))
async def cb_achievement_detail(cb: CallbackQuery) -> None:
    """Detail card behind every achievement button."""
    prefix = cb.data.split(":", 1)[1]
    with session() as db:
        user = player(db, cb.from_user)
        achievements.check(db, user)
        rows = achievements.progress_rows(db, user)
    match = next((r for r in rows if r[1].startswith(prefix)), None)
    if match is None:
        await show(cb, "🏅 Achievement not found.", kb(back_home("nav:achievements")))
        return
    icon, name, description, value, target, unlocked = match
    # find the reward from the catalogue
    definition = achievements.BY_CODE.get(next((c for c, d in achievements.BY_CODE.items() if d[2] == name), ""), None)
    reward_cash = definition[5] if definition else 0
    reward_gold = definition[6] if definition else 0
    text = (
        f"{icon} <b>{esc(name)}</b>\n\n"
        f"<i>{esc(description)}</i>\n\n"
        f"Status: {'✅ <b>unlocked</b>' if unlocked else '🔒 locked'}\n"
        f"Progress: <b>{min(value, target)}/{target}</b>\n"
        f"Reward: 💵 {money(reward_cash)}" + (f" · 🪙 {reward_gold}" if reward_gold else "")
    )
    await show(cb, text, kb(back_home("nav:achievements")))


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:stats")
@router.message(Command("stats"))
async def cb_stats(event: CallbackQuery | Message) -> None:
    await show(event, _stats_text("me", event), stats_menu())


@router.callback_query(F.data.startswith("sta:"))
async def cb_stats_tab(cb: CallbackQuery) -> None:
    await show(cb, _stats_text(cb.data.split(":")[1], cb), stats_menu())


def _stats_text(which: str, event) -> str:
    with session() as db:
        if which == "global":
            g = stats.global_stats(db)
            return (
                "🌍 <b>GLOBAL STATISTICS</b>\n\n"
                f"👥 Users: <b>{g['users']}</b>\n"
                f"🟢 Active users: <b>{g['active']}</b>\n"
                f"🏁 Races created: <b>{g['races']}</b>\n"
                f"✅ Races completed: <b>{g['finished']}</b>\n"
                f"🏆 Championships: <b>{g['championships']}</b>\n"
                f"💰 Total economy: <b>{money(g['total_cash'])}</b>\n"
                f"🪙 Total gold: <b>{g['total_gold']}</b>\n"
                f"⭐ VIP users: <b>{g['vip']}</b>\n"
                f"🚫 Banned users: <b>{g['banned']}</b>\n"
                f"📜 Transactions: <b>{g['transactions']}</b>\n"
                f"🛒 Purchases: <b>{g['purchases']}</b>\n"
                f"🎟️ Race entries: <b>{g['entries']}</b>\n"
                f"💵 Prize money paid: <b>{money(g['prizes'])}</b>"
            )
        user = player(db, event.from_user)
        p = stats.player_stats(db, user)
        return (
            "📊 <b>YOUR STATISTICS</b>\n\n"
            f"🏁 Races: <b>{p['races']}</b>\n"
            f"🥇 Wins: <b>{p['wins']}</b>\n"
            f"🏆 Podiums: <b>{p['podiums']}</b>\n"
            f"💥 DNFs: <b>{p['dnfs']}</b>\n"
            f"⏱️ Poles: <b>{p['poles']}</b>\n"
            f"⚡ Fastest laps: <b>{p['fastest_laps']}</b>\n"
            f"🏁 Championship points: <b>{p['points']}</b>\n"
            f"💵 Earnings: <b>{money(p['earnings'])}</b>\n"
            f"💸 Spending: <b>{money(p['spending'])}</b>\n"
            f"🎯 Win rate: <b>{p['win_rate']:.1f}%</b>\n"
            f"📈 Rating: <b>{p['rating']}</b>\n"
            f"🪙 Gold: <b>{p['gold']}</b>\n"
            f"✨ XP: <b>{p['xp']}</b>\n"
            f"🏅 Achievements: <b>{p['achievements']}</b>"
        )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:settings")
@router.message(Command("settings"))
async def cb_settings(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        text = (
            "⚙️ <b>SETTINGS</b>\n\n"
            f"👤 Name: <b>{esc(user.first_name or '-')}</b>\n"
            f"🔎 Username: <b>{('@' + esc(user.username)) if user.username else 'not set'}</b>\n\n"
            "Game rules you can rely on:\n"
            f"• Grid size: {store.min_participants(db)}–{store.max_participants(db)} players\n"
            f"• Entry fee: {money(store.entry_fee(db))}\n"
            f"• Daily cooldown: {settings.daily_cooldown_hours}h\n"
            f"• Resale ratio: {int(store.sell_ratio(db) * 100)}%\n\n"
            "To change your display name use Telegram itself; the bot reads it automatically."
        )
    await show(event, text, settings_menu())


# --------------------------------------------------------------------------- #
# Championship / results
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:standings")
@router.message(Command("standings"))
async def cb_standings(event: CallbackQuery | Message) -> None:
    await show(event, _standings_text("drivers"), _standings_markup("drivers"))


@router.callback_query(F.data.startswith("std:"))
async def cb_standings_tab(cb: CallbackQuery) -> None:
    which = cb.data.split(":")[1]
    await show(cb, _standings_text(which), _standings_markup(which))


def _standings_markup(which: str) -> object:
    from ..keyboards import standings_menu

    return standings_menu()


def _standings_text(which: str) -> str:
    with session() as db:
        if which == "teams":
            rows = race_svc.constructored_standings(db, limit=15)
            lines = ["🏆 <b>CONSTRUCTORS' CHAMPIONSHIP</b>\n\n"]
            scored = [r for r in rows if r[1] > 0]
            if not scored:
                return "🏆 <b>CONSTRUCTORS' CHAMPIONSHIP</b>\n\n<i>No points scored yet — race first!</i>"
            for idx, (team, points, riders) in enumerate(scored, start=1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
                lines.append(
                    f"{medal} <b>{points:>4}</b> pts  <b>{esc(team.name)}</b>"
                    f"  <i>({riders} car{'s' if riders > 1 else ''})</i>\n"
                )
            return "".join(lines)

        rows = race_svc.season_standings(db, limit=25)
        lines = ["🏆 <b>DRIVERS' CHAMPIONSHIP</b>\n\n"]
        scored = [r for r in rows if r[1] > 0]
        if not scored:
            return "🏆 <b>DRIVERS' CHAMPIONSHIP</b>\n\n<i>No points scored yet — race first!</i>"
        for idx, (user, points, wins, podiums) in enumerate(scored, start=1):
            team = economy.get_team(db, user)
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
            lines.append(
                f"{medal} <b>{points:>4}</b> pts  <b>{esc(user.first_name or user.username or user.id)}</b>"
                f"  <i>{esc(team.name) if team else '—'}</i>\n"
                f"      <i>{wins}W · {podiums}P · {user.poles}⏱ · {user.fastest_laps}⚡</i>\n"
            )
        return "".join(lines)


@router.callback_query(F.data == "nav:results")
async def cb_results(cb: CallbackQuery) -> None:
    with session() as db:
        history = race_svc.race_history(db, limit=12)
    if not history:
        await show(cb, "📜 <b>No finished races yet.</b>", kb(back_home("nav:menu")))
        return
    rows = [[btn(f"{r.flag} R{r.round_no} {r.gp_name}", f"res:{r.id}")] for r in history]
    rows += [
        [btn("🏆 Championship", "nav:standings")],
        *back_home("nav:menu"),
    ]
    await show(cb, "📜 <b>RACE HISTORY</b>\nPick a weekend to see the full classification.", kb(rows))


@router.callback_query(F.data.startswith("res:"))
async def cb_race_result(cb: CallbackQuery) -> None:
    race_id = int(cb.data.split(":", 1)[1])
    with session() as db:
        race = db.get(__import__("f1bot.models", fromlist=["Race"]).Race, race_id)
        if race is None:
            await show(cb, "Race not found.", kb(back_home("nav:menu")))
            return
        entries = race_svc.race_classification(db, race_id)
        ids = [e.user_id for e in entries] or [0]
        users = {u.id: u for u in db.query(User).filter(User.id.in_(ids))}
        results = {
            r.user_id: r
            for r in db.query(__import__("f1bot.models", fromlist=["Result"]).Result).filter_by(race_id=race_id)
        }
        lines = [
            f"🏆 <b>GRAND PRIX RESULT</b>\n{race.flag} <b>Round {race.round_no} — {esc(race.gp_name)}</b>\n"
            f"<i>{esc(race.circuit)}, {esc(race.country)} · {race.total_laps} laps · "
            f"{race_svc.weather_label(race.weather)}</i>\n\n"
        ]
        for e in entries:
            user = users.get(e.user_id)
            name = esc((user.first_name or user.username or str(e.user_id)) if user else str(e.user_id))
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e.finish_pos, f"{e.finish_pos}.")
            marker = "💥" if e.dnf else medal
            fl = " ⚡" if e.fastest_lap else ""
            lines.append(
                f"{marker} <b>{name}</b>{fl}\n"
                f"    <i>{e.points} pts · {money(e.money_won)}"
                + (f" · {e.gold_won} 🪙" if e.gold_won else "")
                + f" · 🛞 {e.pit_stops} pits · "
                + ("DNF" if e.dnf else f"{e.gap:+.3f}s" if e.finish_pos > 1 else "WINNER")
                + "</i>\n"
            )
        markup = kb(
            [
                [btn("🏆 Championship", "nav:standings"), btn("📜 History", "nav:results")],
                *back_home("nav:menu"),
            ]
        )
    await show(cb, "".join(lines), markup)


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #
HELP_TEXT = (
    "ℹ️ <b>HOW THE GAME WORKS</b>\n\n"
    "<b>1 · Build a team</b>\nBuy a constructor and two drivers in the 🛒 Shop.\n\n"
    "<b>2 · Develop</b>\n🚗 Garage: 11 car parts and 8 driver attributes. Every level really "
    "changes the simulated lap time.\n\n"
    "<b>3 · Race weekend</b>\n🏁 Race → JOIN RACE → ⏱️ qualifying → the race is simulated lap by "
    "lap with weather, tyres, pit stops, safety cars and overtakes.\n\n"
    "<b>4 · Rewards</b>\nChampionship points 25-18-15… plus prize money for the top 10 and gold "
    "for the podium.\n\n"
    "<b>5 · Season</b>\n24 real rounds of the 2026 calendar, sprint weekends included."
)


@router.callback_query(F.data == "nav:help")
@router.message(Command("help", "rules"))
async def cb_help(event: CallbackQuery | Message) -> None:
    await show(event, HELP_TEXT, kb(back_home("nav:menu")))
