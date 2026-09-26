"""Player screens: welcome, main menu, profile, wallet, VIP, bonus, statistics."""

from __future__ import annotations

from datetime import timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..db import get_user, session
from ..format import esc, money
from ..i18n import LANGS, lang_name, t
from ..keyboards import (
    achievements_menu,
    back_home,
    btn,
    daily_menu,
    kb,
    language_menu,
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
from ..services.runtime import get_bot, get_bot_username

router = Router(name="user")


def player(db, telegram_user) -> User:
    return get_user(db, telegram_user.id, telegram_user.username or "", telegram_user.first_name or "")


def is_admin(user_id: int | None) -> bool:
    return settings.is_admin(user_id)


def lang_of(user: User) -> str:
    """The player's UI language (ru/uz/en); '' means the picker is due."""
    return user.language if user.language in LANGS else ""


def in_group(event: CallbackQuery | Message) -> bool:
    """True when the interaction happens inside a group/supergroup chat."""
    chat = getattr(getattr(event, "message", None) if isinstance(event, CallbackQuery) else event, "chat", None)
    return getattr(chat, "type", "private") in ("group", "supergroup")


def group_lang(user: User, telegram_user) -> str:
    """Group screens: the user's language, or Telegram's, else Uzbek."""
    if user.language in LANGS:
        return user.language
    code = (getattr(telegram_user, "language_code", "") or "").split("-")[0]
    return code if code in LANGS else "uz"


# --------------------------------------------------------------------------- #
# Welcome / main menu
# --------------------------------------------------------------------------- #
def welcome_text(user: User, lang: str = "en") -> str:
    name = esc(user.first_name or user.username or "Driver")
    return t(
        lang,
        "welcome",
        name=name,
        cash=money(user.balance),
        gold=user.gold,
    )


def _language_picker_message(cb_or_message):
    return t("ru", "pick_title") + "\n\n" + t("ru", "pick_hint")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject | None = None) -> None:
    payload = (getattr(command, "args", None) or "").strip() if command else ""
    # Deep link from the "Join" button in a group: t.me/bot?start=join<chat_id>
    digits = payload[4:] if payload.startswith("join") else (payload if payload.lstrip("-").isdigit() else "")
    if in_group(message):
        # groups are race-only: never the welcome text or the language picker
        from .races import group_race_screen

        return await group_race_screen(message)
    with session() as db:
        user = player(db, message.from_user)
        if digits and digits.lstrip("-").isdigit():
            return await _join_via_group(message, user, int(digits))
        lang = lang_of(user)
        if not lang:
            # First contact: pick the interface language before anything else.
            await message.answer(_language_picker_message(message), reply_markup=language_menu(), parse_mode="HTML")
            return
        text = welcome_text(user, lang)
        admin = is_admin(user.id)
    await message.answer(text, reply_markup=main_menu(admin, lang), parse_mode="HTML")


@router.message(Command("menu", "start"))
@router.message(F.text.lower().regexp(r"^(menu|main menu|🏠 main menu|start)$"))
async def cmd_menu(message: Message) -> None:
    if in_group(message):
        from .races import group_race_screen

        return await group_race_screen(message)
    with session() as db:
        user = player(db, message.from_user)
        lang = lang_of(user)
        if not lang:
            await message.answer(_language_picker_message(message), reply_markup=language_menu(), parse_mode="HTML")
            return
        text, admin = welcome_text(user, lang), is_admin(user.id)
    await message.answer(text, reply_markup=main_menu(admin, lang), parse_mode="HTML")


@router.callback_query(F.data == "nav:menu")
async def cb_menu(cb: CallbackQuery) -> None:
    if in_group(cb):
        from .races import group_race_screen

        return await group_race_screen(cb)
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user)
        if not lang:
            await show(cb, t("ru", "pick_title"), language_menu())
            return
        text, admin = welcome_text(user, lang), is_admin(user.id)
    await show(cb, text, main_menu(admin, lang))


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data == "nav:back")
async def cb_back(cb: CallbackQuery) -> None:
    """The universal ⬅️ Back: re-open the screen shown just before this one."""
    from ..services.runtime import previous_screen, redispatch_callback

    target = previous_screen(cb.from_user.id)
    if target == cb.data:
        target = "nav:menu"
    if not await redispatch_callback(cb, target):
        # No dispatcher around (tests / odd contexts): answer politely.
        await cb.answer()


# --------------------------------------------------------------------------- #
# Join a race straight from a group (deep link: ?start=join<chat_id>)
# --------------------------------------------------------------------------- #
async def _join_via_group(message: Message, user: User, group_id: int) -> None:
    """The user tapped the group's Join button and landed here with /start."""
    if user.language not in LANGS:
        code = (getattr(message.from_user, "language_code", "") or "").split("-")[0]
        user.language = code if code in LANGS else "uz"
    lang = user.language
    with session() as db:
        race = race_svc.current_race(db)
        if race is None or race.status not in ("open", "paused"):
            await message.answer(t(lang, "g_no_race"), reply_markup=main_menu(False, lang), parse_mode="HTML")
            return
        drivers = economy.get_drivers(db, user)
        try:
            total = race_svc.join_race(db, race, user, drivers)
        except ValueError as exc:
            un = get_bot_username()
            rows = [[InlineKeyboardButton(text=t(lang, "g_open_me"), url=f"https://t.me/{un}")]] if un else []
            await message.answer(
                f"❌ {esc(exc)}\n\n{t(lang, 'g_need_team')}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
            )
            return
        race_name = f"{race.flag} {race.gp_name}"
        maximum = store.max_participants(db)
        text = (
            f"{t(lang, 'rc_entered')}\n\n"
            f"{race_name} — {t(lang, 'rc_cost')} <b>{money(total)}</b>\n"
            f"{t(lang, 'rc_players')}: <b>{race.participants}/{maximum}</b>\n"
            f"{t(lang, 'rc_balance')}: <b>{money(user.balance)}</b>\n\n"
            f"{t(lang, 'g_open_bot')}"
        )
        uid, uname, ufirst = user.id, user.username, user.first_name
    # tell the admin who joined, with a fresh invite link to the group
    bot = get_bot()
    if bot is not None:
        title = f"<code>{group_id}</code>"
        link_markup = None
        try:
            chat = await bot.get_chat(group_id)
            title = esc(getattr(chat, "title", "") or title)
        except Exception:
            pass
        try:
            invite = await bot.create_chat_invite_link(group_id)
            link_markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t(lang, "g_open_group"), url=invite.invite_link)]]
            )
        except Exception:
            pass
        try:
            await bot.send_message(
                settings.super_admin_id,
                t(lang, "g_joined_group", name=esc(ufirst or uname or uid), uid=uid, group=title),
                parse_mode="HTML",
                reply_markup=link_markup,
            )
        except Exception:
            pass
    await message.answer(text, reply_markup=main_menu(False, lang), parse_mode="HTML")


# --------------------------------------------------------------------------- #
# Language selection
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("lang:set:"))
async def cb_set_language(cb: CallbackQuery) -> None:
    code = cb.data.split(":", 2)[2]
    if code not in LANGS:
        await cb.answer("Unknown language", show_alert=True)
        return
    with session() as db:
        user = player(db, cb.from_user)
        user.language = code
        lang = code
        text, admin = welcome_text(user, lang), is_admin(user.id)
    await show(
        cb,
        t(lang, "lang_changed", name=lang_name(lang)) + "\n\n" + text,
        main_menu(admin, lang),
        alert=lang_name(lang),
    )


@router.callback_query(F.data == "nav:lang")
@router.message(Command("lang"))
async def cb_language(event: CallbackQuery | Message) -> None:
    """The /lang command and the Settings → Language button."""
    with session() as db:
        user = player(db, event.from_user)
        current = lang_of(user) or "ru"
    await show(event, t(current, "lang_current", name=lang_name(current)), language_menu())


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:profile")
@router.message(Command("profile"))
async def cb_profile(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
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
        f"{t(lang, 'p_driver')} {idx}: <b>{esc(d.name)}</b> <code>#{d.number}</code> {d.country} — OVR {d.overall}"
        for idx, d in enumerate(drivers, start=1)
    ) or t(lang, "p_no_drivers")
    filled = len(drivers)
    while filled < 2:
        seats += f"\n{t(lang, 'p_driver')} {filled + 1}: <i>{t(lang, 'p_seat_empty')}</i>"
        filled += 1

    races = max(1, user.races_entered)
    text = (
        f"{t(lang, 'p_title')} — <b>{esc(user.first_name or user.username or user.id)}</b>{handle}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"{t(lang, 'p_cash')}: <b>{money(user.balance)}</b>\n"
        f"{t(lang, 'p_gold')}: <b>{user.gold}</b>\n"
        f"⭐ VIP: <b>{vip.label(user)}</b>\n\n"
        f"{t(lang, 'p_team')}: <b>{esc(team.name) if team else t(lang, 'p_none')}</b>"
        + (f" (OVR {team.rating})" if team else "")
        + f"\n{seats}\n\n"
        f"{t(lang, 'p_races')}: <b>{user.races_entered}</b>\n"
        f"{t(lang, 'p_wins')}: <b>{user.wins}</b>\n"
        f"{t(lang, 'p_podiums')}: <b>{user.podiums}</b>\n"
        f"{t(lang, 'p_dnfs')}: <b>{user.dnfs}</b>\n"
        f"{t(lang, 'p_titles')}: <b>{user.titles}</b>\n"
        f"{t(lang, 'p_rating')}: <b>{rating}</b>\n"
        f"{t(lang, 'p_earned')}: <b>{money(user.total_earnings)}</b>\n"
        f"{t(lang, 'p_spent')}: <b>{money(user.total_spending)}</b>\n"
        f"{t(lang, 'p_points')}: <b>{user.race_points}</b>\n"
        f"{t(lang, 'p_poles')}: <b>{user.poles}</b>\n"
        f"{t(lang, 'p_fl')}: <b>{user.fastest_laps}</b>\n"
        f"{t(lang, 'p_winrate')}: <b>{100.0 * user.wins / races:.1f}%</b>\n"
        f"{t(lang, 'p_value')}: <b>{money(value)}</b>"
        + (f"\n🚫 <b>{esc(moderation.describe(ban))}</b>" if ban else "")
    )
    markup = kb(
        [
            [btn(t(lang, "m_wallet"), "nav:wallet"), btn(t(lang, "m_garage"), "nav:garage")],
            [btn(t(lang, "m_race"), "nav:races"), btn(t(lang, "m_championship"), "nav:standings")],
            *back_home("nav:menu", lang=lang),
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
        lang = lang_of(user) or "en"
        recent = wallet_svc.history(db, user.id, limit=5)
    lines = [
        f"{t(lang, 'w_title')}\n\n",
        f"{t(lang, 'p_cash')}: <b>{money(user.balance)}</b>\n",
        f"{t(lang, 'p_gold')}: <b>{user.gold}</b>\n\n",
        f"{t(lang, 'w_recent')}\n",
    ]
    if not recent:
        lines.append(t(lang, "w_empty"))
    for txn in recent:
        sign = "+" if txn.amount > 0 else ""
        icon = "💵" if txn.currency == "cash" else "🪙"
        amount = money(txn.amount) if txn.currency == "cash" else f"{txn.amount}"
        lines.append(f"{icon} {sign}{amount} — {esc(txn.reason)}\n")
    await show(event, "".join(lines), wallet_menu(lang))


@router.callback_query(F.data.startswith("wal:tx"))
async def cb_transactions(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    gold_only = parts[1] == "txg"
    from ..services import wallet as wallet_svc

    per = 10
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        total = wallet_svc.history_count(db, user.id, "gold" if gold_only else None)
        rows = wallet_svc.history(db, user.id, "gold" if gold_only else None, limit=per, offset=page * per)
    pages = max(1, -(-total // per))
    lines = [t(lang, "w_tx_title", n=total) + "\n\n"]
    if not rows:
        lines.append(t(lang, "w_tx_none"))
    for txn in rows:
        sign = "+" if txn.amount > 0 else ""
        icon = "💵" if txn.currency == "cash" else "🪙"
        amount = money(txn.amount) if txn.currency == "cash" else f"{txn.amount}"
        when = txn.created_at.strftime("%d.%m %H:%M") if txn.created_at else ""
        lines.append(
            f"{icon} <b>{sign}{amount}</b> · {esc(txn.reason)}\n   <i>{when} · "
            + f"{t(lang, 'w_balance')} {money(txn.balance_after) if txn.currency == 'cash' else txn.balance_after}"
            + (f" · {esc(txn.note)}" if txn.note else "")
            + "</i>\n"
        )
    await show(cb, "".join(lines), transactions_menu(page, pages, lang))


# --------------------------------------------------------------------------- #
# Daily bonus
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:daily")
@router.message(Command("daily"))
async def cb_daily(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
        ready = bonus.can_claim(user)
        left = bonus.next_in(user)
        history = bonus.history(db, user.id, limit=5)
    streak = "\n".join(
        f"Day {row.streak}: 💵{money(row.cash)} 🪙{row.gold} ✨{row.xp}" + (f" · {esc(row.bonus)}" if row.bonus else "")
        for row in history
    ) or t(lang, "d_none")
    text = (
        f"{t(lang, 'd_title')}\n\n"
        + (f"{t(lang, 'd_ready')}\n" if ready else f"{t(lang, 'd_wait', t=left)}\n")
        + f"🔥 {t(lang, 'd_streak')}: <b>{user.daily_streak}</b>\n\n"
        f"{t(lang, 'd_base')}: 💵{money(settings.daily_cash)} 🪙{settings.daily_gold} ✨{settings.daily_xp}\n"
        f"{t(lang, 'd_note')}\n\n"
        f"{t(lang, 'd_last')}\n{streak}"
    )
    await show(event, text, daily_menu(ready, lang))


@router.callback_query(F.data == "dly:claim")
async def cb_claim(cb: CallbackQuery) -> None:
    from ..services import wallet as wallet_svc

    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        try:
            claim = bonus.claim(db, user)
        except ValueError as exc:
            await show(cb, f"{t(lang, 'd_title')}\n\n{esc(exc)}", daily_menu(False, lang), alert=str(exc), show_alert=True)
            return
        unlocked = achievements.check(db, user)
        text = (
            f"{t(lang, 'd_claimed')}\n\n"
            f"{t(lang, 'd_cash')}: <b>+{money(claim.cash)}</b>\n"
            f"{t(lang, 'p_gold')}: <b>+{claim.gold}</b>\n"
            f"{t(lang, 'd_xp')}: <b>+{claim.xp}</b>\n"
            + (f"{t(lang, 'd_bonus')}: <b>{esc(claim.bonus)}</b>\n" if claim.bonus else "")
            + f"🔥 {t(lang, 'd_streak')}: <b>{claim.streak}</b>\n\n"
            f"{t(lang, 'd_newbal')}: <b>{money(user.balance)}</b> · 🪙 <b>{user.gold}</b>\n"
            f"{t(lang, 'd_next')} <b>{claim.next_in_minutes}</b> {t(lang, 'd_minutes')}"
        )
        if unlocked:
            text += "\n\n" + t(lang, "d_unlocked") + " " + ", ".join(esc(x) for x in unlocked)
    await show(cb, text, daily_menu(False, lang))


# --------------------------------------------------------------------------- #
# VIP
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:vip")
@router.message(Command("vip"))
async def cb_vip(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
        level = vip.refresh(user)
        lines = [
            f"{t(lang, 'v_title')}\n\n",
            f"{t(lang, 'v_your')}: <b>{vip.label(user)}</b>\n",
            f"{t(lang, 'v_yourgold')}: <b>{user.gold}</b>\n\n",
        ]
        for lvl in range(1, vip.MAX_LEVEL + 1):
            name, prize, gold_back, daily = vip.PERKS[lvl]
            price = store.get(db, f"vip_price_{lvl}")
            mark = "✅" if level >= lvl else "🔒"
            lines.append(
                f"{mark} <b>{name}</b> — {price} 🪙\n"
                f"    {t(lang, 'v_prize')} +{int(prize * 100)}% · {t(lang, 'v_daily')} ×{daily}"
                + (f" · {gold_back} {t(lang, 'v_perrace')}" if gold_back else "")
                + "\n"
            )
        if user.vip_expires_at is not None and not user.vip_permanent:
            expires = user.vip_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            lines.append(f"\n{t(lang, 'v_expires')}: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>")
    await show(event, "".join(lines), vip_menu(lang))


@router.callback_query(F.data.startswith("vip:lvl:"))
async def cb_vip_level(cb: CallbackQuery) -> None:
    level = int(cb.data.split(":")[2])
    name, prize, gold_back, daily = vip.PERKS.get(level, vip.PERKS[1])
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        price = store.get(db, f"vip_price_{level}")
    text = (
        f"⭐ <b>{name}</b>\n\n"
        f"{t(lang, 'v_price')}: <b>{price} 🪙</b> ({t(lang, 'v_days')})\n\n"
        f"• {t(lang, 'v_prize')} <b>+{int(prize * 100)}%</b>\n"
        f"• {t(lang, 'v_daily')} <b>×{daily}</b>\n"
        + (f"• <b>{gold_back} 🪙</b> {t(lang, 'v_perrace')}\n" if gold_back else "")
        + f"\n{t(lang, 'v_shop_hint')}"
    )
    await show(cb, text, kb([[btn(t(lang, "v_buy"), "sto:vip")], *back_home("nav:vip", lang=lang)]))


# --------------------------------------------------------------------------- #
# Achievements
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:achievements")
@router.message(Command("achievements"))
async def cb_achievements(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
        achievements.check(db, user)
        rows = achievements.progress_rows(db, user)
    got = sum(1 for r in rows if r[5])
    lines = [t(lang, "a_title", got=got, n=len(rows)) + "\n\n"]
    items = []
    for icon, name, description, value, target, unlocked in rows:
        mark = "✅" if unlocked else "🔒"
        lines.append(f"{mark} {icon} <b>{esc(name)}</b> — <i>{esc(description)}</i>\n")
        if not unlocked:
            lines.append(f"    <i>{t(lang, 'a_progress')} {min(value, target)}/{target}</i>\n")
        items.append(btn(f"{mark} {icon} {name}", f"ach:{name[:18]}"))
    await show(event, "".join(lines), achievements_menu(items, lang))


@router.callback_query(F.data.startswith("ach:"))
async def cb_achievement_detail(cb: CallbackQuery) -> None:
    """Detail card behind every achievement button."""
    prefix = cb.data.split(":", 1)[1]
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        achievements.check(db, user)
        rows = achievements.progress_rows(db, user)
    match = next((r for r in rows if r[1].startswith(prefix)), None)
    if match is None:
        await show(cb, t(lang, "a_notfound"), kb(back_home("nav:achievements", lang=lang)))
        return
    icon, name, description, value, target, unlocked = match
    # find the reward from the catalogue
    definition = achievements.BY_CODE.get(next((c for c, d in achievements.BY_CODE.items() if d[2] == name), ""), None)
    reward_cash = definition[5] if definition else 0
    reward_gold = definition[6] if definition else 0
    text = (
        f"{icon} <b>{esc(name)}</b>\n\n"
        f"<i>{esc(description)}</i>\n\n"
        f"{t(lang, 'a_status')}: {t(lang, 'a_unlocked') if unlocked else t(lang, 'a_locked')}\n"
        f"{t(lang, 'a_progress')}: <b>{min(value, target)}/{target}</b>\n"
        f"{t(lang, 'a_reward')}: 💵 {money(reward_cash)}" + (f" · 🪙 {reward_gold}" if reward_gold else "")
    )
    await show(cb, text, kb(back_home("nav:achievements", lang=lang)))


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:stats")
@router.message(Command("stats"))
async def cb_stats(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
    await show(event, _stats_text("me", event, lang), stats_menu(lang))


@router.callback_query(F.data.startswith("sta:"))
async def cb_stats_tab(cb: CallbackQuery) -> None:
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
    await show(cb, _stats_text(cb.data.split(":")[1], cb, lang), stats_menu(lang))


def _stats_text(which: str, event, lang: str = "en") -> str:
    with session() as db:
        if which == "global":
            g = stats.global_stats(db)
            return (
                f"{t(lang, 's_g_title')}\n\n"
                f"{t(lang, 's_users')}: <b>{g['users']}</b>\n"
                f"{t(lang, 's_active')}: <b>{g['active']}</b>\n"
                f"{t(lang, 's_races_c')}: <b>{g['races']}</b>\n"
                f"{t(lang, 's_races_f')}: <b>{g['finished']}</b>\n"
                f"{t(lang, 's_champs')}: <b>{g['championships']}</b>\n"
                f"{t(lang, 's_economy')}: <b>{money(g['total_cash'])}</b>\n"
                f"{t(lang, 's_gold_t')}: <b>{g['total_gold']}</b>\n"
                f"{t(lang, 's_vip')}: <b>{g['vip']}</b>\n"
                f"{t(lang, 's_banned')}: <b>{g['banned']}</b>\n"
                f"{t(lang, 's_tx')}: <b>{g['transactions']}</b>\n"
                f"{t(lang, 's_purch')}: <b>{g['purchases']}</b>\n"
                f"{t(lang, 's_entries')}: <b>{g['entries']}</b>\n"
                f"{t(lang, 's_prizes')}: <b>{money(g['prizes'])}</b>"
            )
        user = player(db, event.from_user)
        p = stats.player_stats(db, user)
        return (
            f"{t(lang, 's_me_title')}\n\n"
            f"{t(lang, 'p_races')}: <b>{p['races']}</b>\n"
            f"{t(lang, 'p_wins')}: <b>{p['wins']}</b>\n"
            f"{t(lang, 'p_podiums')}: <b>{p['podiums']}</b>\n"
            f"{t(lang, 'p_dnfs')}: <b>{p['dnfs']}</b>\n"
            f"{t(lang, 'p_poles')}: <b>{p['poles']}</b>\n"
            f"{t(lang, 'p_fl')}: <b>{p['fastest_laps']}</b>\n"
            f"{t(lang, 'p_points')}: <b>{p['points']}</b>\n"
            f"{t(lang, 's_earnings')}: <b>{money(p['earnings'])}</b>\n"
            f"{t(lang, 's_spending')}: <b>{money(p['spending'])}</b>\n"
            f"{t(lang, 'p_winrate')}: <b>{p['win_rate']:.1f}%</b>\n"
            f"{t(lang, 'p_rating')}: <b>{p['rating']}</b>\n"
            f"{t(lang, 'p_gold')}: <b>{p['gold']}</b>\n"
            f"✨ XP: <b>{p['xp']}</b>\n"
            f"{t(lang, 's_ach')}: <b>{p['achievements']}</b>"
        )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:settings")
@router.message(Command("settings"))
async def cb_settings(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
        text = (
            f"{t(lang, 'set_title')}\n\n"
            f"{t(lang, 'set_name')}: <b>{esc(user.first_name or '-')}</b>\n"
            f"{t(lang, 'set_uname')}: <b>{('@' + esc(user.username)) if user.username else t(lang, 'set_notset')}</b>\n"
            f"🌐 {t(lang, 'set_lang').split(' ', 1)[-1]}: <b>{lang_name(lang)}</b>\n\n"
            f"{t(lang, 'set_rules')}\n"
            f"{t(lang, 'set_grid', min=store.min_participants(db), max=store.max_participants(db))}\n"
            f"{t(lang, 'set_fee', fee=money(store.entry_fee(db)))}\n"
            f"{t(lang, 'set_daily', h=settings.daily_cooldown_hours)}\n"
            f"{t(lang, 'set_sell', p=int(store.sell_ratio(db) * 100))}\n\n"
            f"{t(lang, 'set_name_hint')}"
        )
    await show(event, text, settings_menu(lang))


# --------------------------------------------------------------------------- #
# Championship / results
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:standings")
@router.message(Command("standings"))
async def cb_standings(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
    await show(event, _standings_text("drivers", lang), _standings_markup(lang))


@router.callback_query(F.data.startswith("std:"))
async def cb_standings_tab(cb: CallbackQuery) -> None:
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
    which = cb.data.split(":")[1]
    await show(cb, _standings_text(which, lang), _standings_markup(lang))


def _standings_markup(which: str, lang: str = "en") -> object:
    from ..keyboards import standings_menu

    return standings_menu(lang)


def _standings_text(which: str, lang: str = "en") -> str:
    with session() as db:
        if which == "teams":
            rows = race_svc.constructored_standings(db, limit=15)
            lines = [t(lang, "st_teams") + "\n\n"]
            scored = [r for r in rows if r[1] > 0]
            if not scored:
                return t(lang, "st_teams") + "\n\n" + t(lang, "st_nopoints")
            for idx, (team, points, riders) in enumerate(scored, start=1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
                lines.append(
                    f"{medal} <b>{points:>4}</b> {t(lang, 'st_pts')}  <b>{esc(team.name)}</b>"
                    f"  <i>({riders} {t(lang, 'st_cars')}{'s' if riders > 1 and lang == 'en' else ''})</i>\n"
                )
            return "".join(lines)

        rows = race_svc.season_standings(db, limit=25)
        lines = [t(lang, "st_drivers") + "\n\n"]
        scored = [r for r in rows if r[1] > 0]
        if not scored:
            return t(lang, "st_drivers") + "\n\n" + t(lang, "st_nopoints")
        for idx, (user, points, wins, podiums) in enumerate(scored, start=1):
            team = economy.get_team(db, user)
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
            lines.append(
                f"{medal} <b>{points:>4}</b> {t(lang, 'st_pts')}  <b>{esc(user.first_name or user.username or user.id)}</b>"
                f"  <i>{esc(team.name) if team else '—'}</i>\n"
                f"      <i>{wins}W · {podiums}P · {user.poles}⏱ · {user.fastest_laps}⚡</i>\n"
            )
        return "".join(lines)


@router.callback_query(F.data == "nav:results")
async def cb_results(cb: CallbackQuery) -> None:
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        history = race_svc.race_history(db, limit=12)
    if not history:
        await show(cb, t(lang, "r_hist_empty"), kb(back_home("nav:menu", lang=lang)))
        return
    rows = [[btn(f"{r.flag} R{r.round_no} {r.gp_name}", f"res:{r.id}")] for r in history]
    rows += [
        [btn(t(lang, "m_championship"), "nav:standings")],
        *back_home("nav:menu", lang=lang),
    ]
    await show(cb, t(lang, "r_hist_title"), kb(rows))


@router.callback_query(F.data.startswith("res:"))
async def cb_race_result(cb: CallbackQuery) -> None:
    race_id = int(cb.data.split(":", 1)[1])
    with session() as db:
        user = player(db, cb.from_user)
        lang = lang_of(user) or "en"
        race = db.get(__import__("f1bot.models", fromlist=["Race"]).Race, race_id)
        if race is None:
            await show(cb, "Race not found.", kb(back_home("nav:menu", lang=lang)))
            return
        entries = race_svc.race_classification(db, race_id)
        ids = [e.user_id for e in entries] or [0]
        users = {u.id: u for u in db.query(User).filter(User.id.in_(ids))}
        results = {
            r.user_id: r
            for r in db.query(__import__("f1bot.models", fromlist=["Result"]).Result).filter_by(race_id=race_id)
        }
        lines = [
            f"{t(lang, 'r_result_title')}\n{race.flag} <b>{t(lang, 'r_round')} {race.round_no} — {esc(race.gp_name)}</b>\n"
            f"<i>{esc(race.circuit)}, {esc(race.country)} · {race.total_laps} {t(lang, 'r_laps')} · "
            f"{race_svc.weather_label(race.weather)}</i>\n\n",
        ]
        for e in entries:
            user = users.get(e.user_id)
            name = esc((user.first_name or user.username or str(e.user_id)) if user else str(e.user_id))
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e.finish_pos, f"{e.finish_pos}.")
            marker = "💥" if e.dnf else medal
            fl = " ⚡" if e.fastest_lap else ""
            lines.append(
                f"{marker} <b>{name}</b>{fl}\n"
                f"    <i>{e.points} {t(lang, 'r_pts')} · {money(e.money_won)}"
                + (f" · {e.gold_won} 🪙" if e.gold_won else "")
                + f" · 🛞 {e.pit_stops} {t(lang, 'r_pits')} · "
                + ("DNF" if e.dnf else f"{e.gap:+.3f}s" if e.finish_pos > 1 else "WINNER")
                + "</i>\n"
            )
        markup = kb(
            [
                [btn(t(lang, "m_championship"), "nav:standings"), btn(t(lang, "s_results"), "nav:results")],
                *back_home("nav:menu", lang=lang),
            ]
        )
    await show(cb, "".join(lines), markup)


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #
def help_text(lang: str = "en") -> str:
    return (
        f"{t(lang, 'h_title')}\n\n"
        f"{t(lang, 'h_1')}\n\n"
        f"{t(lang, 'h_2')}\n\n"
        f"{t(lang, 'h_3')}\n\n"
        f"{t(lang, 'h_4')}\n\n"
        f"{t(lang, 'h_5')}"
    )


@router.callback_query(F.data == "nav:help")
@router.message(Command("help", "rules"))
async def cb_help(event: CallbackQuery | Message) -> None:
    with session() as db:
        user = player(db, event.from_user)
        lang = lang_of(user) or "en"
    await show(event, help_text(lang), kb(back_home("nav:menu", lang=lang)))
