"""Super Admin Panel — every button wired to a real server-side action.

Access: only the super admin (Telegram id 7203210832, see config.SUPER_ADMIN_ID)
plus the extra operators in ADMIN_IDS. Every mutation is validated server-side,
writes an AdminLog row and never trusts callback data for amounts.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, or_, select

from ..config import settings
from ..db import get_user, session
from ..flow import announce_weekend, open_weekend, start_race, weekend_summary
from ..format import esc, money, pager
from ..i18n import t
from ..keyboards import (
    admin_ban_menu,
    admin_broadcast_confirm,
    admin_broadcast_menu,
    admin_crud_menu,
    admin_edit_menu,
    admin_economy_menu,
    admin_list_menu,
    admin_main,
    admin_moderation_menu,
    admin_race_menu,
    admin_rewards_menu,
    admin_settings_menu,
    admin_user_menu,
    admin_users_menu,
    admin_vip_days_menu,
    admin_vip_level_menu,
    back_row,
    btn,
    confirm_kb,
    kb,
    nav_row,
    pager_row,
)
from ..models import Achievement, Driver, Race, Team, Track, User, UserAchievement
from ..render import show
from ..seed import seed_all
from ..services import adminlog, economy, moderation, notify, stats, store, vip, wallet
from ..services import races as svc
from ..services.runtime import get_bot, spawn_auto_start

router = Router(name="admin")


class Admin(StatesGroup):
    search = State()
    amount = State()
    value = State()          # generic field editor (teams / drivers / tracks)
    setting = State()        # runtime settings editor
    bcast_target = State()   # broadcast: pick one user id
    broadcast = State()      # broadcast: capture text/photo/video


def guard(event) -> bool:
    user = getattr(event, "from_user", None)
    if not (user and settings.is_admin(user.id)):
        return False
    # The admin panel lives in the bot's private chat only — never in groups.
    chat = getattr(
        getattr(event, "message", None) if isinstance(event, CallbackQuery) else event, "chat", None
    )
    if getattr(chat, "type", "private") in ("group", "supergroup"):
        return False
    return True


# --------------------------------------------------------------------------- #
# Panel home
# --------------------------------------------------------------------------- #
async def admin_panel(event) -> None:
    with session() as db:
        moderation.sync_expired(db)
        players = int(db.scalar(select(func.count(User.id))) or 0)
        banned = moderation.banned_user_ids_count(db)
        race = svc.current_race(db)
        cash = int(db.scalar(select(func.coalesce(func.sum(User.balance), 0))) or 0)
        gold = int(db.scalar(select(func.coalesce(func.sum(User.gold), 0))) or 0)
        vip_count = vip.vip_user_count(db)
    text = (
        "━━━━━━━━━━━━━━\n⚙️ <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━\n\n"
        f"👥 Players: <b>{players}</b> · 🚫 banned {banned} · ⭐ VIP {vip_count}\n"
        f"💰 Cash in circulation: <b>{money(cash)}</b>\n"
        f"🪙 Gold in circulation: <b>{gold}</b>\n"
        + (
            f"\n🏁 Active weekend: {race.flag} <b>R{race.round_no} {esc(race.gp_name)}</b>"
            f" ({race.status}, 👥 {race.participants})"
            if race
            else "\n🏁 Active weekend: <i>none</i>"
        )
    )
    await show(event, text, admin_main())


@router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject) -> None:
    if not guard(message):
        await message.answer("⛔ Access denied. This panel is restricted.")
        return
    await admin_panel(message)


@router.callback_query(F.data.in_({"nav:admin", "adm:panel", "adm:home"}))
async def cb_admin_open(cb: CallbackQuery) -> None:
    if not guard(cb):
        await show(cb, "⛔ <b>Access denied.</b>", kb([nav_row()]), alert="Admins only", show_alert=True)
        return
    await admin_panel(cb)


# --------------------------------------------------------------------------- #
# Users: search, list, manage
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "adm:users")
async def cb_users_menu(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(cb, "👥 <b>USER MANAGEMENT</b>", admin_users_menu())


@router.callback_query(F.data == "adm:usearch")
async def cb_user_search(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await state.set_state(Admin.search)
    await show(cb, "🔎 <b>Search user</b>\n\nSend a Telegram ID, <code>@username</code> or a name fragment.")


@router.message(Admin.search, F.text)
async def do_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not guard(message):
        return
    raw = (message.text or "").strip().lstrip("@")
    with session() as db:
        stmt = select(User)
        if raw.isdigit():
            stmt = stmt.where(
                or_(User.id == int(raw), User.username.ilike(f"%{raw}%"), User.first_name.ilike(f"%{raw}%"))
            )
        else:
            stmt = stmt.where(or_(User.username.ilike(f"%{raw}%"), User.first_name.ilike(f"%{raw}%")))
        found = list(db.scalars(stmt.limit(10)))
        if not found:
            await message.answer("🔎 Nobody found. Try another ID or username.")
            return
        if len(found) == 1:
            await _show_user_card(message, db, found[0].id)
            return
        rows = [
            [btn(f"{u.display_name} · {u.id}", f"adm:user:{u.id}")] for u in found
        ]
        rows.append(back_row("adm:users"))
    await message.answer("🔎 <b>Search results</b>", reply_markup=kb(rows))


async def _show_user_card(event, db, user_id: int) -> None:
    player = db.get(User, user_id)
    if player is None:
        await show(event, "Player not found.", kb([back_row("adm:users")]), alert="Not found", show_alert=True)
        return
    moderation.sync_expired(db)
    ban = moderation.active_ban(db, player.id)
    team = economy.get_team(db, player)
    drivers = economy.get_drivers(db, player)
    text = (
        f"👤 <b>{esc(player.display_name)}</b> <code>{player.id}</code>\n"
        f"{('@' + esc(player.username)) if player.username else '<i>no username</i>'}\n\n"
        f"💰 Balance: <b>{money(player.balance)}</b>   🪙 Gold: <b>{player.gold}</b>\n"
        f"⭐ VIP: <b>{vip.label(player)}</b>\n"
        f"🏎️ Team: <b>{esc(team.name) if team else '—'}</b>\n"
        f"👨‍✈️ Drivers: {', '.join(esc(d.name) for d in drivers) if drivers else '—'}\n\n"
        f"🏁 Races: <b>{player.races_entered}</b> · 🥇 {player.wins} · 🏆 {player.podiums} · "
        f"Points: <b>{player.race_points}</b>\n"
        f"💵 Earnings {money(player.total_earnings)} · 💸 Spending {money(player.total_spending)}\n\n"
        f"Status: <b>{esc(moderation.describe(ban))}</b>"
    )
    await show(event, text, admin_user_menu(player.id, ban is not None, player.vip_level > 0))


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user_card(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    with session() as db:
        await _show_user_card(cb, db, user_id)


@router.callback_query(F.data.startswith("adm:ulist:"))
async def cb_user_list(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    page = int(cb.data.split(":")[2] or 0)
    size = 8
    with session() as db:
        total = int(db.scalar(select(func.count(User.id))) or 0)
        rows = list(db.scalars(select(User).order_by(User.id.asc()).offset(page * size).limit(size)))
        items = [
            btn(
                f"{esc(u.display_name)} · {money(u.balance)} · {u.race_points}p" + (" 🚫" if u.banned else ""),
                f"adm:user:{u.id}",
            )
            for u in rows
        ]
        markup = admin_list_menu(items, "adm:users", page, max(1, -(-total // size)), "adm:ulist:{page}")
    await show(cb, f"👥 <b>ALL USERS</b> — {total}", markup)


@router.callback_query(F.data == "adm:ubanned")
async def cb_banned_list(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    from ..models import Ban

    with session() as db:
        moderation.sync_expired(db)
        rows = list(db.scalars(select(Ban).where(Ban.active.is_(True)).order_by(Ban.id.desc()).limit(12)))
        lines = ["🚫 <b>BANNED USERS</b>\n\n"]
        if not rows:
            lines.append("<i>Nobody is banned.</i>")
        for ban in rows:
            player = db.get(User, ban.user_id)
            lines.append(
                f"• <b>{esc(player.display_name) if player else ban.user_id}</b> <code>{ban.user_id}</code>\n"
                f"  <i>{esc(moderation.describe(ban))} · admin {ban.admin_id}</i>\n"
            )
    await show(cb, "".join(lines), kb([back_row("adm:users"), nav_row()]))


@router.callback_query(F.data == "adm:bans")
async def cb_ban_history(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    from ..models import Ban

    with session() as db:
        rows = list(db.scalars(select(Ban).order_by(Ban.id.desc()).limit(15)))
        lines = ["📜 <b>BAN HISTORY</b>\n\n"]
        if not rows:
            lines.append("<i>No bans recorded.</i>")
        for ban in rows:
            player = db.get(User, ban.user_id)
            status = "🟢 lifted" if not ban.active else "🔴 active"
            lines.append(
                f"{status} <b>{esc(player.display_name) if player else ban.user_id}</b>\n"
                f"  <i>{esc(ban.reason)} · by {ban.admin_id} · {ban.created_at:%d.%m.%Y %H:%M}</i>\n"
            )
    await show(cb, "".join(lines), kb([back_row("adm:mod"), nav_row()]))


# --------------------------------------------------------------------------- #
# Money / gold operations with confirmation
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith(("adm:cash:", "adm:cashminus:", "adm:gold:", "adm:goldminus:")))
async def cb_money_op(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    kind = {
        "adm:cash": "cash_give",
        "adm:cashminus": "cash_remove",
        "adm:gold": "gold_give",
        "adm:goldminus": "gold_remove",
    }[cb.data.rsplit(":", 1)[0]]
    user_id = int(cb.data.split(":")[2])
    await state.set_state(Admin.amount)
    await state.update_data(kind=kind, target=user_id)
    labels = {
        "cash_give": "💰 Give money",
        "cash_remove": "💸 Remove money",
        "gold_give": "🪙 Give gold",
        "gold_remove": "💎 Remove gold",
    }
    await show(cb, f"<b>{labels[kind]}</b>\nTarget: <code>{user_id}</code>\n\nSend the amount, e.g. <code>50000000</code> or <code>50M</code>.")


def _parse_amount(raw: str, cap: int | None = None) -> int | None:
    text = raw.strip().lower().replace(" ", "").replace("$", "").replace(",", "")
    if text in {"all", "max"}:
        return cap
    multiplier = 1
    if text.endswith("b"):
        multiplier, text = 1_000_000_000, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    elif text.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    try:
        value = int(float(text) * multiplier)
    except ValueError:
        return None
    return value if value > 0 else None


@router.message(Admin.amount, F.text)
async def do_amount(message: Message, state: FSMContext) -> None:
    if not guard(message):
        return
    data = await state.get_data()
    raw = (message.text or "").strip()
    kind, target = data.get("kind"), int(data.get("target", 0))
    with session() as db:
        player = db.get(User, target)
        if player is None:
            await message.answer("Player not found.")
            await state.set_state(None)
            return
        cap = (
            player.balance if kind == "cash_remove" else player.gold if kind == "gold_remove" else None
        )
        amount = _parse_amount(raw, cap)
        if amount is None:
            await message.answer("🚫 Could not parse that amount. Send e.g. <code>50M</code> or <code>all</code>.")
            return
        await state.set_state(None)
        await state.update_data(amount=amount)
        shown = money(amount) if kind.startswith("cash") else f"{amount} 🪙"
        await message.answer(
            f"<b>Confirm</b>\n\n{'Give' if kind.endswith('give') else 'Remove'} <b>{shown}</b> "
            f"{'to' if kind.endswith('give') else 'from'} <b>{esc(player.display_name)}</b> <code>{player.id}</code>?",
            reply_markup=confirm_kb("adma:ok", "adma:no"),
        )


@router.callback_query(F.data.startswith("adma:"))
async def cb_amount_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    action = cb.data.split(":")[1]
    data = await state.get_data()
    if action == "no":
        await state.clear()
        await show(cb, "↩️ Cancelled.", admin_user_menu(int(data.get("target", 0)), False, False))
        return
    kind, target, amount = data.get("kind"), int(data.get("target", 0)), int(data.get("amount", 0))
    if not kind or not amount:
        await state.clear()
        await cb.answer("Nothing pending", show_alert=True)
        return
    await state.clear()
    with session() as db:
        player = db.get(User, target)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        admin_id = cb.from_user.id
        if kind == "cash_give":
            wallet.add_cash(db, player, amount, "ADMIN_GRANT", f"by admin {admin_id}", admin_id=admin_id)
            adminlog.log(db, admin_id, "GIVE_MONEY", target, amount, "ok")
        elif kind == "cash_remove":
            amount = min(amount, int(player.balance))
            wallet.spend_cash(db, player, amount, "ADMIN_REMOVE", f"by admin {admin_id}", admin_id=admin_id)
            adminlog.log(db, admin_id, "REMOVE_MONEY", target, amount, "ok")
        elif kind == "gold_give":
            wallet.add_gold(db, player, amount, "ADMIN_GRANT", f"by admin {admin_id}", admin_id=admin_id)
            adminlog.log(db, admin_id, "GIVE_GOLD", target, amount, "ok")
        elif kind == "gold_remove":
            amount = min(amount, int(player.gold))
            wallet.spend_gold(db, player, amount, "ADMIN_REMOVE", f"by admin {admin_id}", admin_id=admin_id)
            adminlog.log(db, admin_id, "REMOVE_GOLD", target, amount, "ok")
        shown = money(amount) if kind.startswith("cash") else f"{amount} 🪙"
        text = (
            f"✅ Done: <b>{shown}</b> {'given to' if kind.endswith('give') else 'taken from'} "
            f"<b>{esc(player.display_name)}</b>.\n"
            f"💰 Balance: <b>{money(player.balance)}</b> · 🪙 <b>{player.gold}</b>"
        )
        ban = moderation.active_ban(db, target)
        markup = admin_user_menu(target, ban is not None, player.vip_level > 0)
        try:
            bot = get_bot()
            if bot is not None:
                await bot.send_message(
                    target,
                    f"⚙️ An administrator {'credited' if kind.endswith('give') else 'removed'} "
                    f"<b>{shown}</b> {'to' if kind.endswith('give') else 'from'} your wallet.",
                    parse_mode="HTML",
                )
        except Exception:
            pass
    await show(cb, text, markup)


# --------------------------------------------------------------------------- #
# VIP management
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("adm:vipg:"))
async def cb_vip_give(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    await show(cb, f"⭐ <b>Give VIP</b>\nTarget: <code>{user_id}</code>\nPick the level.", admin_vip_level_menu(user_id))


@router.callback_query(F.data.startswith("admvi:l:"))
async def cb_vip_level_pick(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, _op, user_id, level = cb.data.split(":")
    await show(cb, f"⭐ VIP {level}: pick the duration.", admin_vip_days_menu(int(user_id), int(level)))


@router.callback_query(F.data.startswith("admvi:d:"))
async def cb_vip_grant(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, _op, user_id, level, days = cb.data.split(":")
    user_id, level, days = int(user_id), int(level), int(days)
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        vip.grant(db, player, level, days, admin_id=cb.from_user.id)
        adminlog.log(db, cb.from_user.id, "GIVE_VIP", user_id, days, f"VIP {level}")
        label = vip.label(player)
        text = (
            f"✅ <b>{esc(player.display_name)}</b> now holds <b>{label}</b>\n"
            + (
                "♾️ Permanent"
                if player.vip_permanent
                else f"⏳ Until <b>{player.vip_expires_at.strftime('%d.%m.%Y %H:%M') if player.vip_expires_at else '-'}</b> UTC"
            )
        )
    try:
        bot = get_bot()
        if bot is not None:
            await bot.send_message(user_id, f"⭐ You were granted <b>{label}</b>!", parse_mode="HTML")
    except Exception:
        pass
    await show(cb, text, admin_user_menu(user_id, False, True))


@router.callback_query(F.data.startswith("adm:viprm:"))
async def cb_vip_remove(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        vip.remove(player)
        adminlog.log(db, cb.from_user.id, "REMOVE_VIP", user_id, 0, "ok")
    await show(cb, f"❌ VIP removed from <b>{esc(player.display_name)}</b>.", admin_user_menu(user_id, False, False))


@router.callback_query(F.data == "adm:vip")
async def cb_vip_overview(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        rows = list(db.scalars(select(User).where(User.vip_level > 0).order_by(User.vip_level.desc()).limit(15)))
        lines = [
            "⭐ <b>VIP MANAGEMENT</b>\n\n",
            f"VIP users: <b>{vip.vip_user_count(db)}</b> · expiring within 7 days: <b>{vip.expiring(db, 7)}</b>\n\n",
        ]
        if not rows:
            lines.append("<i>No VIP players.</i>")
        for player in rows:
            lines.append(f"⭐ <b>{esc(player.display_name)}</b> — {vip.label(player)} <code>{player.id}</code>\n")
    await show(cb, "".join(lines), kb([back_row("adm:home"), nav_row()]))


# --------------------------------------------------------------------------- #
# Ban / unban
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("adm:ban:"))
async def cb_ban_menu(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    await show(cb, f"🚫 <b>Ban user {user_id}</b>\nPick the duration.", admin_ban_menu(user_id))


@router.callback_query(F.data.startswith("admb:"))
async def cb_ban_apply(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, user_id, minutes = cb.data.split(":")
    user_id, minutes = int(user_id), int(minutes)
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        row = moderation.ban(db, player, cb.from_user.id, minutes, "admin panel ban")
        race = svc.current_race(db)
        if race is not None and race.status == "open":
            entry = svc.entry_of(db, race.id, user_id)
            if entry is not None:
                svc.leave_race(db, race, player)
        text = f"🚫 <b>{esc(player.display_name)}</b> is now {esc(moderation.describe(row))}."
        vip_flag = player.vip_level > 0
    try:
        bot = get_bot()
        if bot is not None:
            await bot.send_message(user_id, f"🚫 You were banned: {esc(row.reason)}.", parse_mode="HTML")
    except Exception:
        pass
    await show(cb, text, admin_user_menu(user_id, True, vip_flag))


@router.callback_query(F.data.startswith("adm:unban:"))
async def cb_unban(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        cleared = moderation.unban(db, player, cb.from_user.id, "admin panel")
        adminlog.log(db, cb.from_user.id, "UNBAN_USER", user_id, 0, f"{cleared} bans lifted")
        vip_flag = player.vip_level > 0
    try:
        bot = get_bot()
        if bot is not None:
            await bot.send_message(user_id, "✅ You were unbanned. Welcome back to the paddock!", parse_mode="HTML")
    except Exception:
        pass
    await show(cb, f"✅ <b>{esc(player.display_name)}</b> unbanned ({cleared} bans lifted).", admin_user_menu(user_id, False, vip_flag))


# --------------------------------------------------------------------------- #
# User extras: stats, transactions, reset
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("adm:ustat:"))
async def cb_user_stats(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        p = stats.player_stats(db, player)
    text = (
        f"📊 <b>{esc(player.display_name)}</b> statistics\n\n"
        f"🏁 Races {p['races']} · 🥇 {p['wins']} · 🏆 {p['podiums']} · 💥 {p['dnfs']}\n"
        f"⏱️ {p['poles']} · ⚡ {p['fastest_laps']} · 🏁 {p['points']} pts\n"
        f"💵 {money(p['earnings'])} · 💸 {money(p['spending'])}\n"
        f"🎯 Win rate {p['win_rate']}% · rating {p['rating']}"
    )
    await show(cb, text, kb([back_row(f"adm:user:{user_id}"), nav_row()]))


@router.callback_query(F.data.startswith("adm:utx:"))
async def cb_user_transactions(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    parts = cb.data.split(":")
    user_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    per = 10
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        total = wallet.history_count(db, user_id)
        rows = wallet.history(db, user_id, limit=per, offset=page * per)
        lines = [f"📜 <b>{esc(player.display_name)}</b> — transactions ({total})\n\n"]
        if not rows:
            lines.append("<i>None.</i>")
        for txn in rows:
            sign = "+" if txn.amount > 0 else ""
            icon = "💵" if txn.currency == "cash" else "🪙"
            amount = money(txn.amount) if txn.currency == "cash" else str(txn.amount)
            lines.append(f"{icon} <b>{sign}{amount}</b> · {esc(txn.reason)} · {esc(txn.note)}\n")
        pages = max(1, -(-total // per))
        items = [{"text": f"📄 {page + 1}/{pages}", "callback_data": "noop"}]
        markup = admin_list_menu(items, f"adm:user:{user_id}", page, pages, f"adm:utx:{user_id}:{{page}}")
    await show(cb, "".join(lines), markup)


@router.callback_query(F.data.startswith("adm:ureset:"))
async def cb_reset_user(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    await show(
        cb,
        f"🔄 <b>Reset progress of user {user_id}?</b>\nBalance back to starting cash, all contracts, upgrades and statistics wiped.",
        confirm_kb(f"adm:uresetgo:{user_id}", f"adm:user:{user_id}", "🔄 Reset", "❌ Cancel"),
    )


@router.callback_query(F.data.startswith("adm:uresetgo:"))
async def cb_reset_user_go(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    user_id = int(cb.data.split(":")[2])
    with session() as db:
        player = db.get(User, user_id)
        if player is None:
            await show(cb, "Player not found.", None, "Not found", True)
            return
        economy.reset_progress(db, player)
        adminlog.log(db, cb.from_user.id, "RESET_USER", user_id, 0, "ok")
    await show(cb, f"🔄 Progress of <b>{esc(player.display_name)}</b> was reset.", admin_user_menu(user_id, False, False))


# --------------------------------------------------------------------------- #
# Race management
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "adm:race")
async def cb_race_admin(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        race = svc.current_race(db)
        if race is None:
            await show(
                cb,
                "🏁 <b>RACE MANAGEMENT</b>\n\nNo active weekend. Create one:",
                kb(
                    [
                        [btn("➕ Create Grand Prix", "admr:new:gp"), btn("➕ Create Sprint", "admr:new:sprint")],
                        back_row("adm:home"),
                        nav_row(),
                    ]
                ),
            )
            return
        text = (
            f"🏁 <b>{race.flag} R{race.round_no} {esc(race.gp_name)}</b> ({race.kind})\n"
            f"Status: <b>{race.status}</b> · 👥 {race.participants}/{store.max_participants(db)}\n"
            f"Minimum players: <b>{store.min_participants(db)}</b>\n"
        )
        markup = admin_race_menu(race.id, race.status)
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("admr:new:"))
async def cb_race_create(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    kind = cb.data.split(":")[2]
    with session() as db:
        try:
            race = open_weekend(db, None, kind)
        except ValueError as exc:
            await show(cb, f"🚫 {esc(exc)}", None, str(exc), True)
            return
        race_id = race.id
        adminlog.log(db, cb.from_user.id, "CREATE_RACE", None, race.round_no, f"{race.gp_name} ({kind})")
        summary = weekend_summary(race)
    spawn_auto_start(max(60, settings.auto_start_minutes * 60), start_race, race_id)
    await show(cb, f"🟢 <b>Weekend created!</b>\n\n{summary}", admin_race_menu(race_id, "open"))
    with session() as db:
        fresh = db.get(Race, race_id)
    if fresh is not None:
        await announce_weekend(fresh)


@router.callback_query(F.data.startswith("admr:pause:"))
async def cb_race_pause(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        race.status = "paused"
        adminlog.log(db, cb.from_user.id, "PAUSE_REGISTRATION", None, race_id, race.gp_name)
    await show(cb, "⏸️ Registration paused.", admin_race_menu(race_id, "paused"))


@router.callback_query(F.data.startswith("admr:open:"))
async def cb_race_resume(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        race.status = "open"
        adminlog.log(db, cb.from_user.id, "RESUME_REGISTRATION", None, race_id, race.gp_name)
    await show(cb, "▶️ Registration resumed.", admin_race_menu(race_id, "open"))


@router.callback_query(F.data.startswith("admr:ext:"))
async def cb_race_extend(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    await show(
        cb,
        "⏱️ <b>Extend registration</b> — pick the extra time:",
        kb(
            [
                [btn("+10 min", f"admrx:{race_id}:10"), btn("+30 min", f"admrx:{race_id}:30")],
                [btn("+60 min", f"admrx:{race_id}:60"), btn("+100 min", f"admrx:{race_id}:100")],
                back_row("adm:race"),
                nav_row(),
            ]
        ),
    )


@router.callback_query(F.data.startswith("admrx:"))
async def cb_race_extend_apply(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, race_id, minutes = cb.data.split(":")
    race_id, minutes = int(race_id), int(minutes)
    from ..flow import extend_weekend

    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        if race.status not in ("open", "paused"):
            await show(cb, "🚫 Registration for this weekend is already closed.", None, "Closed", True)
            return
    # extend_weekend does the single real extension (and notifies the entrants)
    await extend_weekend(race_id, minutes, admin_id=cb.from_user.id)
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        text = (
            f"⏱️ Registration of <b>{esc(race.gp_name)}</b> extended by <b>{minutes}</b> min.\n"
            f"New deadline: <b>{race.registration_ends_at.strftime('%H:%M UTC') if race.registration_ends_at else '-'}</b> · 👥 {race.participants}"
        )
        status = race.status
    await show(cb, text, admin_race_menu(race_id, status))


@router.callback_query(F.data.startswith("admr:start:"))
async def cb_race_start(cb: CallbackQuery) -> None:
    import asyncio

    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        minimum = store.min_participants(db)
        if race is None or race.status not in ("open", "paused"):
            await show(cb, "This weekend is not open.", None, "Not open", True)
            return
        if race.participants < minimum:
            await show(
                cb,
                f"🚫 Only <b>{race.participants}</b> entries — the minimum is <b>{minimum}</b>.",
                admin_race_menu(race_id, race.status),
                alert=f"Minimum {minimum} players",
                show_alert=True,
            )
            return
    await show(cb, "🚦 <b>Race launched.</b> The live broadcast is running.", admin_race_menu(race_id, "live"))
    asyncio.create_task(start_race(race_id, force=True))


@router.callback_query(F.data.startswith("admr:part:"))
async def cb_race_participants(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    from ..models import RaceEntry

    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        entries = (
            svc.race_classification(db, race_id)
            if race.status == "finished"
            else list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race_id)))
        )
        users = {
            u.id: u
            for u in db.scalars(select(User).where(User.id.in_([e.user_id for e in entries] or [0])))
        }
        lines = [f"👥 <b>{esc(race.gp_name)} — participants ({race.participants})</b>\n\n"]
        if not entries:
            lines.append("<i>Nobody entered.</i>")
        for entry in entries:
            player = users.get(entry.user_id)
            name = esc(player.display_name) if player else str(entry.user_id)
            extra = ""
            if race.status == "finished":
                extra = f" · P{entry.finish_pos} · {entry.points}p · {money(entry.money_won)}"
            elif entry.quali_avg > 0:
                extra = f" · ⏱️ {entry.quali_avg:.3f}s"
            lines.append(f"• <b>{name}</b>{extra}\n")
    await show(cb, "".join(lines), kb([back_row("adm:race"), nav_row()]))


@router.callback_query(F.data.startswith("admr:res:"))
async def cb_race_results(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        entries = svc.race_classification(db, race_id)
        users = {
            u.id: u
            for u in db.scalars(select(User).where(User.id.in_([e.user_id for e in entries] or [0])))
        }
        lines = [f"📊 <b>{esc(race.gp_name)} — result</b>\n\n"]
        if not entries or all(e.finish_pos == 0 for e in entries):
            lines.append("<i>Not finished yet.</i>")
        for entry in entries:
            player = users.get(entry.user_id)
            name = esc(player.display_name) if player else str(entry.user_id)
            marker = "💥" if entry.dnf else f"P{entry.finish_pos}"
            lines.append(f"{marker} <b>{name}</b> — {entry.points}p, {money(entry.money_won)}\n")
    await show(cb, "".join(lines), kb([back_row("adm:race"), nav_row()]))


@router.callback_query(F.data.startswith("admr:cancel:"))
async def cb_race_cancel(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    await show(cb, "❌ <b>Cancel this weekend?</b>\nAll entry fees will be refunded.", confirm_kb(f"admr:cancelgo:{race_id}", "adm:race"))


@router.callback_query(F.data.startswith("admr:cancelgo:"))
async def cb_race_cancel_go(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    race_id = int(cb.data.split(":")[2])
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", None, "Not found", True)
            return
        refunded = svc.cancel_race(db, race, "cancelled by admin")
        adminlog.log(db, cb.from_user.id, "CANCEL_RACE", None, race_id, f"{len(refunded)} refunds")
    await show(cb, f"❌ Weekend cancelled, <b>{len(refunded)}</b> entries refunded.", kb([back_row("adm:home"), nav_row()]))


@router.callback_query(F.data == "adm:restart")
async def cb_race_restart(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    from ..models import QualifyingResult, RaceEntry, RaceEvent, Result, WeatherLog
    from ..services.runtime import clear_race_handled

    with session() as db:
        race = svc.current_race(db)
        if race is None:
            await show(cb, "No active weekend.", None, "None", True)
            return
        # wipe everything the previous running wrote so the weekend can re-run
        for row in list(db.scalars(select(Result).where(Result.race_id == race.id))):
            db.delete(row)
        for row in list(db.scalars(select(RaceEvent).where(RaceEvent.race_id == race.id))):
            db.delete(row)
        for row in list(db.scalars(select(WeatherLog).where(WeatherLog.race_id == race.id))):
            db.delete(row)
        for row in list(db.scalars(select(QualifyingResult).where(QualifyingResult.race_id == race.id))):
            db.delete(row)
        for entry in db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)):
            entry.finished = False
            entry.finish_pos = 0
            entry.points = 0
            entry.money_won = 0
            entry.gold_won = 0
            entry.dnf = False
            entry.fastest_lap = False
            entry.pit_stops = 0
            entry.race_avg = 0.0
            entry.race_times = None
            entry.gap = 0.0
            entry.total_time = 0.0
        race.status = "open"
        race.quali_done = False
        race.grid = None
        race.started_at = None
        race.live_message_id = None
        adminlog.log(db, cb.from_user.id, "RESTART_RACE", None, race.id, race.gp_name)
        race_id = race.id
    clear_race_handled(race_id)
    await show(cb, "🔄 Weekend reset back to registration.", admin_race_menu(race_id, "open"))


# --------------------------------------------------------------------------- #
# CRUD: teams / drivers / tracks
# --------------------------------------------------------------------------- #
KIND_MODEL = {"team": Team, "driver": Driver, "track": Track}
KIND_BACK = {"team": "adm:teams", "driver": "adm:drivers", "track": "adm:tracks"}


@router.callback_query(F.data.startswith(("adm:teams", "adm:drivers", "adm:tracks")))
async def cb_crud_list(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    parts = cb.data.split(":")
    kind = {"teams": "team", "drivers": "driver", "tracks": "track"}.get(parts[1], parts[1])
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    size = 8
    with session() as db:
        model = KIND_MODEL[kind]
        total = int(db.scalar(select(func.count(model.id))) or 0)
        if kind == "team":
            rows = list(db.scalars(select(Team).order_by(Team.rating.desc()).offset(page * size).limit(size)))
            items = [btn(f"{o.logo} {esc(o.name)} (OVR {o.rating})", f"ade:view:team:{o.id}") for o in rows]
        elif kind == "driver":
            rows = list(db.scalars(select(Driver).order_by(Driver.overall.desc()).offset(page * size).limit(size)))
            items = [btn(f"#{o.number} {esc(o.name)} (OVR {o.overall})", f"ade:view:driver:{o.id}") for o in rows]
        else:
            rows = list(db.scalars(select(Track).order_by(Track.round_no).offset(page * size).limit(size)))
            items = [btn(f"R{o.round_no} {esc(o.gp_name)}", f"ade:view:track:{o.id}") for o in rows]
        markup = admin_crud_menu(kind, items, f"ade:add:{kind}", f"adm:{kind}s", page, max(1, -(-total // size)), f"adm:{kind}s:{{page}}")
    title = {"team": "🏎️ TEAMS", "driver": "👨‍✈️ DRIVERS", "track": "🗺️ TRACKS"}[kind]
    await show(cb, f"<b>{title}</b> — {total} total", markup)


@router.callback_query(F.data.startswith("ade:view:"))
async def cb_entity_view(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    kind, item_id = cb.data.split(":")[2], int(cb.data.split(":")[3])
    with session() as db:
        obj = db.get(KIND_MODEL[kind], item_id)
        if obj is None:
            await show(cb, "Not found.", None, "Not found", True)
            return
        if kind == "team":
            text = f"✏️ <b>{esc(obj.name)}</b> ({esc(obj.code)}) · {money(obj.price)}\n\n"
        elif kind == "driver":
            text = f"✏️ <b>{esc(obj.name)}</b> <code>#{obj.number}</code> · {esc(obj.team_name)} · {money(obj.price)}\n\n"
        else:
            text = f"✏️ <b>R{obj.round_no} {esc(obj.gp_name)}</b> · {esc(obj.circuit)}\n\n"
        fields = [(key, label, getattr(obj, key)) for key, label, _v in obj.stat_lines()]
        for _key, label, value in fields:
            text += f"{label}: <b>{value}</b>\n"
        markup = admin_edit_menu(kind, item_id, fields, KIND_BACK[kind])
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("ade:"))
async def cb_entity_edit(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    parts = cb.data.split(":")
    if parts[1] == "add":
        kind = parts[2]
        await state.set_state(Admin.value)
        await state.update_data(kind=kind, item_id=0, field="__name__")
        await show(cb, f"➕ <b>Add {kind}</b>\n\nSend the name of the new {kind}.")
        return
    # ade:<kind>:<id>:<field>
    kind, item_id, field = parts[1], int(parts[2]), parts[3]
    await state.set_state(Admin.value)
    await state.update_data(kind=kind, item_id=item_id, field=field)
    await show(cb, f"✏️ Send the new value for <b>{field}</b>.")


FIELD_TYPES: dict[str, dict[str, str]] = {
    "team": {
        "rating": "int", "price": "money", "aero": "int", "straight_line": "int",
        "cornering": "int", "reliability": "int", "tire_management": "int",
        "pit_crew": "int", "potential": "int",
    },
    "driver": {
        "overall": "int", "speed": "int", "qualifying": "int", "race_pace": "int",
        "overtaking": "int", "defending": "int", "wet_skill": "int",
        "tire_management": "int", "consistency": "int", "experience": "int",
        "potential": "int", "price": "money", "salary": "money", "number": "int",
    },
    "track": {
        "round_no": "int", "length_km": "float", "laps": "int", "lap_record": "float",
        "overtaking": "float", "downforce": "float", "tire_degradation": "float",
        "safety_car_prob": "float", "rain_prob": "float", "reliability_stress": "float",
    },
}


@router.message(Admin.value, F.text)
async def do_entity_value(message: Message, state: FSMContext) -> None:
    if not guard(message):
        return
    data = await state.get_data()
    await state.set_state(None)
    kind, item_id, field = data.get("kind"), int(data.get("item_id", 0)), data.get("field")
    raw = (message.text or "").strip()
    with session() as db:
        if field == "__name__":
            if kind == "team":
                obj = Team(name=raw[:80], code=raw[:4].upper(), price=30_000_000)
            elif kind == "driver":
                obj = Driver(name=raw[:80], code=raw[:3].upper(), team_name="Free agent")
            else:
                obj = Track(round_no=25, gp_name=raw[:80], circuit=raw[:80])
            db.add(obj)
            db.flush()
            adminlog.log(db, message.from_user.id, f"CREATE_{kind.upper()}", None, obj.id, raw)
            await message.answer(
                f"✅ New {kind} <b>{esc(raw)}</b> created (id {obj.id}). Open it from the list to edit every stat."
            )
            return
        obj = db.get(KIND_MODEL[kind], item_id)
        if obj is None:
            await message.answer("Not found.")
            return
        ftype = FIELD_TYPES[kind].get(field, "int")
        try:
            if ftype == "int":
                value = max(0, min(1_000_000, int(float(raw))))
            elif ftype == "float":
                value = max(0.0, min(100_000.0, float(raw)))
            elif ftype == "money":
                value = _parse_amount(raw)
                if value is None:
                    raise ValueError
            else:
                value = raw[:80]
        except ValueError:
            await message.answer("🚫 Invalid value.")
            return
        setattr(obj, field, value)
        db.flush()
        adminlog.log(db, message.from_user.id, f"EDIT_{kind.upper()}", None, item_id, f"{field}={value}")
        name = getattr(obj, "name", None) or getattr(obj, "gp_name", "")
        await message.answer(f"✅ <b>{esc(name)}</b> — {field} set to <b>{esc(value)}</b>")


@router.callback_query(F.data.startswith("adm:del:"))
async def cb_entity_delete(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, kind, item_id = cb.data.split(":")
    with session() as db:
        obj = db.get(KIND_MODEL[kind], int(item_id))
        if obj is None:
            await show(cb, "Not found.", None, "Not found", True)
            return
        name = getattr(obj, "name", None) or getattr(obj, "gp_name", "")
    await show(cb, f"❌ <b>Delete {esc(name)}?</b>", confirm_kb(f"adm:delgo:{kind}:{item_id}", f"ade:view:{kind}:{item_id}", "🗑 Delete", "❌ Cancel"))


@router.callback_query(F.data.startswith("adm:delgo:"))
async def cb_entity_delete_go(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    _ns, kind, item_id = cb.data.split(":")
    with session() as db:
        obj = db.get(KIND_MODEL[kind], int(item_id))
        if obj is None:
            await show(cb, "Not found.", None, "Not found", True)
            return
        name = getattr(obj, "name", None) or getattr(obj, "gp_name", "")
        if kind == "team":
            for user in db.scalars(select(User).where(User.team_id == obj.id)):
                user.team_id = None
            # drop the ownership history so the market does not see a ghost owner
            from ..models import UserTeam

            for row in list(db.scalars(select(UserTeam).where(UserTeam.team_id == obj.id))):
                db.delete(row)
        elif kind == "driver":
            for user in db.scalars(select(User).where(User.driver1_id == obj.id)):
                user.driver1_id = None
            for user in db.scalars(select(User).where(User.driver2_id == obj.id)):
                user.driver2_id = None
            from ..models import UserDriver

            for row in list(db.scalars(select(UserDriver).where(UserDriver.driver_id == obj.id))):
                db.delete(row)
        db.delete(obj)
        adminlog.log(db, cb.from_user.id, f"DELETE_{kind.upper()}", None, int(item_id), name)
    await show(cb, f"🗑 Deleted <b>{esc(name)}</b>.", kb([back_row(KIND_BACK[kind]), nav_row()]))


# --------------------------------------------------------------------------- #
# Championship / economy / rewards / settings / logs / statistics
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "adm:champ")
async def cb_champ(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        drivers = svc.season_standings(db, limit=10)
        teams = svc.constructored_standings(db, limit=10)
        lines = ["🏆 <b>CHAMPIONSHIP</b>\n\n<b>Drivers</b>\n"]
        for idx, (player, points, wins, podiums) in enumerate(drivers, start=1):
            lines.append(f"{idx}. {esc(player.display_name)} — {points}p ({wins}W {podiums}P)\n")
        lines.append("\n<b>Constructors</b>\n")
        for idx, (team, points, riders) in enumerate(teams, start=1):
            lines.append(f"{idx}. {esc(team.name)} — {points}p ({riders})\n")
    await show(cb, "".join(lines), kb([back_row("adm:home"), nav_row()]))


@router.callback_query(F.data == "adm:economy")
async def cb_economy(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        totals = wallet.totals(db)
        text = (
            "💰 <b>ECONOMY</b>\n\n"
            f"💵 Total cash held by players: <b>{money(totals['total_cash'])}</b>\n"
            f"🪙 Total gold held: <b>{totals['total_gold']}</b>\n"
            f"📈 Money created: <b>{money(totals['cash_created'])}</b>\n"
            f"📉 Money spent: <b>{money(totals['cash_spent'])}</b>\n"
            f"🪙 Gold created: <b>{totals['gold_created']}</b> · 💎 spent: <b>{totals['gold_spent']}</b>\n"
            f"📜 Transactions: <b>{totals['transactions']}</b> · 🛒 purchases {totals['purchases']}"
        )
    await show(cb, text, admin_economy_menu())


@router.callback_query(F.data == "adbe:refresh")
async def cb_reprice(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        count = economy.refresh_driver_prices(db)
        adminlog.log(db, cb.from_user.id, "REFRESH_PRICES", None, count, "drivers")
    await show(cb, f"♻️ Repriced <b>{count}</b> drivers.", admin_economy_menu())


@router.callback_query(F.data.startswith("admset:"))
async def cb_setting_edit(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    key = cb.data.split(":", 1)[1]
    if key not in store.LABELS:
        await show(cb, "Unknown setting.", admin_economy_menu())
        return
    await state.set_state(Admin.setting)
    await state.update_data(key=key)
    with session() as db:
        value = store.get(db, key)
    await show(
        cb,
        f"⚙️ <b>{esc(store.LABELS[key])}</b>\n\nCurrent: <b>{value:,}</b> · default: <b>{store.DEFAULTS.get(key, 0):,}</b>\n"
        "Send the new value (plain number, or <code>5M</code>/<code>250K</code>).",
    )


@router.message(Admin.setting, F.text)
async def do_setting(message: Message, state: FSMContext) -> None:
    if not guard(message):
        return
    data = await state.get_data()
    await state.set_state(None)
    key = data.get("key")
    value = _parse_amount((message.text or "").strip())
    if value is None or key is None:
        await message.answer("🚫 Invalid number.")
        return
    with session() as db:
        store.set_raw(db, key, str(value))
        adminlog.log(db, message.from_user.id, "SET_SETTING", None, value, key)
    await message.answer(f"✅ <b>{esc(store.LABELS.get(key, key))}</b> = <b>{value:,}</b>")


@router.callback_query(F.data == "adm:rewards")
async def cb_rewards(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(cb, "🎁 <b>REWARDS</b>\n\nConfigure what the game pays out.", admin_rewards_menu())


@router.callback_query(F.data == "adbr:achv")
async def cb_achv_list(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        rows = list(db.scalars(select(Achievement).order_by(Achievement.id)))
        lines = ["🏅 <b>ACHIEVEMENTS</b>\n\n"]
        for row in rows:
            holders = int(
                db.scalar(
                    select(func.count(UserAchievement.id)).where(UserAchievement.achievement_code == row.code)
                )
                or 0
            )
            lines.append(
                f"{row.icon} <b>{esc(row.name)}</b> — {esc(row.description)}\n"
                f"    <i>unlocked by {holders} players · reward {money(row.reward_cash)}"
                + (f" +{row.reward_gold}🪙" if row.reward_gold else "")
                + "</i>\n"
            )
    await show(cb, "".join(lines), kb([back_row("adm:rewards"), nav_row()]))


@router.callback_query(F.data == "adm:gold")
async def cb_gold_admin(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        totals = wallet.totals(db)
        top = list(db.scalars(select(User).order_by(User.gold.desc()).limit(10)))
        lines = [
            "🪙 <b>GOLD ECONOMY</b>\n\n",
            f"🪙 Total gold in circulation: <b>{totals['total_gold']}</b>\n",
            f"📈 Gold created: <b>{totals['gold_created']}</b> · 💎 spent: <b>{totals['gold_spent']}</b>\n\n",
            "<b>Top holders</b>\n",
        ]
        if not top or all(u.gold == 0 for u in top):
            lines.append("<i>Nobody holds gold yet.</i>")
        for player in top:
            if player.gold:
                lines.append(f"• {esc(player.display_name)} — <b>{player.gold} 🪙</b>\n")
    await show(cb, "".join(lines), kb([back_row("adm:home"), nav_row()]))


@router.callback_query(F.data == "adm:logs")
async def cb_logs(cb: CallbackQuery) -> None:
    await _show_logs(cb, 0)


@router.callback_query(F.data.startswith("adm:logs:"))
async def cb_logs_page(cb: CallbackQuery) -> None:
    await _show_logs(cb, int(cb.data.split(":")[2] or 0))


async def _show_logs(cb: CallbackQuery, page: int) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    per = 12
    with session() as db:
        total = adminlog.count(db)
        rows = adminlog.recent(db, limit=per, offset=page * per)
        lines = [f"📜 <b>ADMIN LOGS</b> — {total} total\n\n"]
        if not rows:
            lines.append("<i>No admin actions recorded yet.</i>")
        for row in rows:
            when = row.created_at.strftime("%d.%m %H:%M") if row.created_at else ""
            amount = f" {money(row.amount)}" if row.amount else ""
            target = f" → {row.target_user}" if row.target_user else ""
            lines.append(f"<code>{esc(row.action)}</code>{amount}{target} by {row.admin_id} · {when}\n")
    markup_rows = []
    if total > per:
        markup_rows.append(pager_row(page, max(1, -(-total // per)), "adm:logs:{page}"))
    markup_rows.append(back_row("adm:home"))
    await show(cb, "".join(lines), kb(markup_rows))


@router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        svc.refresh_stats(db)
        g = stats.global_stats(db)
        totals = wallet.totals(db)
        text = (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Users: <b>{g['users']}</b>\n"
            f"🟢 Active: <b>{g['active']}</b>\n"
            f"🚫 Banned: <b>{g['banned']}</b>\n"
            f"⭐ VIP: <b>{g['vip']}</b>\n\n"
            f"🏁 Races: <b>{g['races']}</b> (completed <b>{g['finished']}</b>, active <b>{g['races_active']}</b>)\n"
            f"🎟️ Entries: <b>{g['entries']}</b> · results stored <b>{g['results']}</b>\n\n"
            f"💰 Total cash: <b>{money(totals['total_cash'])}</b>\n"
            f"🪙 Total gold: <b>{totals['total_gold']}</b>\n"
            f"📜 Transactions: <b>{g['transactions']}</b> · 🛒 Purchases: <b>{g['purchases']}</b>\n"
            f"🏆 Championships: <b>{g['championships']}</b>"
        )
    await show(cb, text, kb([back_row("adm:home"), nav_row()]))


@router.callback_query(F.data == "adm:mod")
async def cb_moderation(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(cb, "🚫 <b>MODERATION</b>\n\nSearch a user to ban or unban them.", admin_moderation_menu())


@router.callback_query(F.data == "adm:settings")
async def cb_settings_menu(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        rows = store.all_values(db)
        lines = ["⚙️ <b>SETTINGS</b>\n\n"]
        for _key, label, value, modified in rows:
            lines.append(f"• {esc(label)}: <b>{value:,}</b>" + (" <i>(edited)</i>" if modified else "") + "\n")
    await show(cb, "".join(lines), admin_settings_menu())


@router.callback_query(F.data == "adbs:resetmk")
async def cb_reset_market(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(cb, "🧹 <b>Free every contract back to the market?</b>", confirm_kb("adbs:resetmk:go", "adm:settings"))


@router.callback_query(F.data == "adbs:resetmk:go")
async def cb_reset_market_go(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        total = economy.reset_market(db)
        adminlog.log(db, cb.from_user.id, "RESET_MARKET", None, total, "ok")
    await show(cb, f"🧹 Returned <b>{total}</b> contracts to the market.", admin_settings_menu())


@router.callback_query(F.data == "adbs:wipe")
async def cb_wipe(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(
        cb,
        "🧨 <b>Wipe EVERYTHING?</b>\nAll players, contracts, races and results are deleted and the 2026 season re-seeded.",
        confirm_kb("adbs:wipe:go", "adm:settings", "🧨 Wipe everything", "❌ Cancel"),
    )


@router.callback_query(F.data == "adbs:wipe:go")
async def cb_wipe_go(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    from ..db import engine, init_db
    from ..models import Base

    Base.metadata.drop_all(engine)
    init_db()
    with session() as db:
        seed_all(db)
        adminlog.log(db, cb.from_user.id, "WIPE_DB", None, 0, "full reset")
    await show(cb, "🧨 Database wiped and re-seeded with the 2026 season.", admin_main())


# --------------------------------------------------------------------------- #
# Broadcast
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "adm:bcast")
async def cb_broadcast_menu(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    await show(cb, "📢 <b>BROADCAST</b>\n\nPick the audience, then send text, photo or video.", admin_broadcast_menu())


@router.callback_query(F.data.startswith("adb:"))
async def cb_broadcast_pick(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    audience_key = cb.data.split(":")[1]
    if audience_key == "one":
        await state.set_state(Admin.bcast_target)
        await show(cb, "🎯 Send the Telegram ID of the user to message.")
        return
    with session() as db:
        count = notify.audience_count(db, audience_key)
    await state.set_state(Admin.broadcast)
    await state.update_data(audience=audience_key, target=None)
    await show(
        cb,
        f"📢 <b>{esc(notify.AUDIENCES[audience_key][0])}</b> — {count} recipients.\n\nNow send the message: text, photo or video (caption included).",
    )


@router.message(Admin.bcast_target, F.text)
async def do_bcast_target(message: Message, state: FSMContext) -> None:
    if not guard(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("🚫 Send a numeric Telegram ID.")
        return
    with session() as db:
        player = db.get(User, int(raw))
        if player is None:
            await message.answer("User not found — they must /start the bot first.")
            return
    await state.set_state(Admin.broadcast)
    await state.update_data(audience="one", target=int(raw))
    await message.answer(f"📢 Now send the message for <b>{esc(player.display_name)}</b>: text, photo or video.")


@router.message(Admin.broadcast, F.text | F.photo | F.video)
async def do_broadcast_capture(message: Message, state: FSMContext) -> None:
    if not guard(message):
        return
    if (message.text or "").startswith("/cancel"):
        await state.clear()
        await message.answer("↩️ Broadcast cancelled.")
        return
    data = await state.get_data()
    audience_key = data.get("audience", "all")
    target = data.get("target")
    with session() as db:
        count = notify.audience_count(db, audience_key)
    await state.update_data(
        text=message.html_text or message.caption or "",
        photo=message.photo[-1].file_id if message.photo else None,
        video=message.video.file_id if message.video else None,
    )
    await state.set_state(None)
    await message.answer(
        f"📢 <b>Recipients: {count}</b>\n\nPreview received. Send it?",
        reply_markup=admin_broadcast_confirm(count),
    )


@router.callback_query(F.data == "adbs:yes")
async def cb_broadcast_send(cb: CallbackQuery, state: FSMContext) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    data = await state.get_data()
    await state.clear()
    audience_key = data.get("audience", "all")
    target = data.get("target")
    text, photo, video = data.get("text", ""), data.get("photo"), data.get("video")
    bot = get_bot()
    with session() as db:
        users = notify.audience(db, audience_key, target)
    if bot is not None:
        sent, failed, blocked = await notify.send_to_users(bot, users, text, photo=photo, video=video)
    else:
        sent, failed, blocked = 0, len(users), 0
    with session() as db:
        notify.log_broadcast(db, cb.from_user.id, audience_key, text, sent, failed, blocked)
        adminlog.log(db, cb.from_user.id, "BROADCAST", target, sent, audience_key)
    await show(cb, f"📢 Sent: <b>{sent}</b> · Failed: <b>{failed}</b> · Blocked: <b>{blocked}</b>", admin_broadcast_menu())


@router.callback_query(F.data == "adbs:no")
async def cb_broadcast_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, "❌ Broadcast cancelled.", admin_broadcast_menu())


# --------------------------------------------------------------------------- #
# Reload + security guard for unknown admin callbacks
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "adm:reload")
async def cb_reload(cb: CallbackQuery) -> None:
    if not guard(cb):
        await cb.answer("Admins only", show_alert=True)
        return
    with session() as db:
        created = seed_all(db)
    await show(
        cb,
        "♻️ 2026 database reloaded (existing rows kept):\n"
        f"teams <b>{created['teams']}</b> · drivers <b>{created['drivers']}</b> · "
        f"rounds <b>{created['rounds']}</b> · achievements <b>{created['achievements']}</b>",
        kb([back_row("adm:home"), nav_row()]),
    )


@router.callback_query(F.data.startswith(("adm:", "ade:", "admr:", "admrx:", "adma:", "admvi:", "admb:", "adb:", "adbs:", "adbe:", "adbr:")))
async def cb_admin_guard(cb: CallbackQuery) -> None:
    if guard(cb):
        await cb.answer("Unknown admin action", show_alert=True)
    else:
        await cb.answer("Admins only", show_alert=True)


# --------------------------------------------------------------------------- #
# Quick commands: give money / gold / VIP / upgrades / drivers by id or @username
# Everything is admin-only, validated server-side and written to the admin log.
# --------------------------------------------------------------------------- #
#: car part name -> User column
PART_COLUMNS = {
    "engine": "up_engine", "aero": "up_aero", "tires": "up_tires",
    "reliability": "up_reliability", "fuel": "up_fuel", "ers": "up_ers",
    "pitcrew": "up_pitcrew", "race_pace": "up_race_pace", "quali_pace": "up_quali_pace",
    "chassis": "up_chassis", "strategy": "up_strategy",
}


def _resolve_target(db, ref: str) -> User | None:
    """Find a player by numeric id or @username (case-insensitive)."""
    ref = (ref or "").strip().lstrip("@")
    if not ref:
        return None
    if ref.lstrip("-").isdigit():
        return db.get(User, int(ref))
    return db.scalar(select(User).where(func.lower(User.username) == ref.lower()))


async def _command_guard(message: Message) -> bool:
    if not settings.is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return False
    return True


@router.message(Command("give", "givecash", "pul"))
async def cmd_give_cash(message: Message, command: CommandObject) -> None:
    """/give <id|@user> <amount> — hand out cash."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: <code>/give 123456 10000000</code> (id or @username)", parse_mode="HTML")
        return
    with session() as db:
        target = _resolve_target(db, parts[0])
        if target is None:
            await message.answer(f"🚫 Player not found: <code>{esc(parts[0])}</code>", parse_mode="HTML")
            return
        amount = int(parts[1])
        wallet.add_cash(db, target, amount, "ADMIN_GIFT", f"admin {message.from_user.id}")
        adminlog.log(db, message.from_user.id, "GIVE_CASH", target.id, amount, "command")
        name, balance = target.display_name, target.balance
    await message.answer(f"✅ <b>{esc(name)}</b>: +{money(amount)}\n💰 {t('en', 'p_cash')}: {money(balance)}", parse_mode="HTML")


@router.message(Command("givegold", "givecoin", "coin"))
async def cmd_give_gold(message: Message, command: CommandObject) -> None:
    """/givegold <id|@user> <amount> — hand out gold."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: <code>/givegold 123456 50</code>", parse_mode="HTML")
        return
    with session() as db:
        target = _resolve_target(db, parts[0])
        if target is None:
            await message.answer(f"🚫 Player not found: <code>{esc(parts[0])}</code>", parse_mode="HTML")
            return
        amount = int(parts[1])
        wallet.add_gold(db, target, amount, "ADMIN_GIFT", f"admin {message.from_user.id}")
        adminlog.log(db, message.from_user.id, "GIVE_GOLD", target.id, amount, "command")
        name, gold = target.display_name, target.gold
    await message.answer(f"✅ <b>{esc(name)}</b>: +{amount} 🪙\n🪙 {t('en', 'p_gold')}: {gold}", parse_mode="HTML")


@router.message(Command("givevip", "vip"))
async def cmd_give_vip(message: Message, command: CommandObject) -> None:
    """/givevip <id|@user> <level> [days] — days 0 means permanent."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/givevip 123456 3 30</code> (days 0 = permanent)", parse_mode="HTML")
        return
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
    with session() as db:
        target = _resolve_target(db, parts[0])
        if target is None:
            await message.answer(f"🚫 Player not found: <code>{esc(parts[0])}</code>", parse_mode="HTML")
            return
        vip.grant(db, target, int(parts[1]), days, admin_id=message.from_user.id)
        adminlog.log(db, message.from_user.id, "GIVE_VIP", target.id, int(parts[1]), f"{days}d")
        name = target.display_name
        level = target.vip_level
    span = t("en", "adm_days_perm") if days <= 0 else f"{days}d"
    await message.answer(f"✅ <b>{esc(name)}</b>: VIP {level} ({span})", parse_mode="HTML")


@router.message(Command("givecar", "upgrade", "kuchaytir"))
async def cmd_give_car(message: Message, command: CommandObject) -> None:
    """/givecar <id|@user> <part> [levels] — boost a car part."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) < 2 or parts[1].lower() not in PART_COLUMNS:
        await message.answer(
            "Usage: <code>/givecar 123456 engine 3</code>\nParts: " + ", ".join(sorted(PART_COLUMNS)),
            parse_mode="HTML",
        )
        return
    levels = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    column = PART_COLUMNS[parts[1].lower()]
    with session() as db:
        target = _resolve_target(db, parts[0])
        if target is None:
            await message.answer(f"🚫 Player not found: <code>{esc(parts[0])}</code>", parse_mode="HTML")
            return
        new_level = min(settings.upgrade_max_level, int(getattr(target, column) or 0) + levels)
        setattr(target, column, new_level)
        adminlog.log(db, message.from_user.id, "GIVE_UPGRADE", target.id, new_level, column)
        name = target.display_name
    await message.answer(f"✅ <b>{esc(name)}</b>: {column} → <b>{new_level}</b>", parse_mode="HTML")


@router.message(Command("givedriver", "driver"))
async def cmd_give_driver(message: Message, command: CommandObject) -> None:
    """/givedriver <id|@user> <CODE> [seat 1|2] — sign a driver for free."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/givedriver 123456 VER 1</code>", parse_mode="HTML")
        return
    seat = int(parts[2]) if len(parts) > 2 and parts[2] in ("1", "2") else 1
    with session() as db:
        target = _resolve_target(db, parts[0])
        driver = db.scalar(select(Driver).where(Driver.code == parts[1].upper()))
        if target is None or driver is None:
            missing = "driver" if driver is None else "player"
            await message.answer(f"🚫 {missing.capitalize()} not found: <code>{esc(parts[1] if driver is None else parts[0])}</code>", parse_mode="HTML")
            return
        economy.grant_driver(db, target, driver.id, seat)
        adminlog.log(db, message.from_user.id, "GIVE_DRIVER", target.id, driver.id, f"seat {seat}")
        name = target.display_name
        dname = driver.name
    await message.answer(f"✅ <b>{esc(name)}</b>: {t('en', 'p_driver')} {seat} → <b>{esc(dname)}</b>", parse_mode="HTML")


@router.message(Command("giveteam", "team"))
async def cmd_give_team(message: Message, command: CommandObject) -> None:
    """/giveteam <id|@user> <CODE> — give a constructor for free."""
    if not await _command_guard(message):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer("Usage: <code>/giveteam 123456 FER</code>", parse_mode="HTML")
        return
    with session() as db:
        target = _resolve_target(db, parts[0])
        team = db.scalar(select(Team).where(Team.code == parts[1].upper()))
        if target is None or team is None:
            missing = "team" if team is None else "player"
            await message.answer(f"🚫 {missing.capitalize()} not found: <code>{esc(parts[1] if team is None else parts[0])}</code>", parse_mode="HTML")
            return
        economy.grant_team(db, target, team.id)
        adminlog.log(db, message.from_user.id, "GIVE_TEAM", target.id, team.id, team.code)
        name = target.display_name
        tname = team.name
    await message.answer(f"✅ <b>{esc(name)}</b>: {t('en', 'p_team')} → <b>{esc(tname)}</b>", parse_mode="HTML")
