"""Race weekend screens: calendar, entry list, join/leave, qualifying, extend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from ..config import settings
from ..db import get_user, session
from ..format import esc, lap_time, money
from ..i18n import t
from ..keyboards import back_home, btn, extend_menu, kb, race_list, race_menu
from ..models import Driver, Race, RaceEntry, Team, User
from ..render import show
from ..services import economy, moderation, store
from ..services import races as svc
from ..services.runtime import get_bot_username

router = Router(name="races")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _lang(user) -> str:
    return user.language if user.language in ("ru", "uz", "en") else "en"


def _in_group(event) -> bool:
    chat = getattr(getattr(event, "message", None) if isinstance(event, CallbackQuery) else event, "chat", None)
    return getattr(chat, "type", "private") in ("group", "supergroup")


async def group_race_screen(event) -> None:
    """In groups the bot is race-only: the weekend plus a deep-link Join button."""
    chat = getattr(getattr(event, "message", None) if isinstance(event, CallbackQuery) else event, "chat", None)
    chat_id = getattr(chat, "id", 0)
    with session() as db:
        user = get_user(db, event.from_user.id, event.from_user.username or "", event.from_user.first_name or "")
        lang = user.language if user.language in ("ru", "uz", "en") else "uz"
        race = svc.current_race(db)
        rows = []
        if race is not None and race.status in ("open", "paused"):
            un = get_bot_username()
            if un:
                rows.append(
                    [InlineKeyboardButton(text=t(lang, "rc_join"), url=f"https://t.me/{un}?start=join{chat_id}")]
                )
            else:
                rows.append([InlineKeyboardButton(text=t(lang, "rc_join"), callback_data="rc:join")])
            rows.append([InlineKeyboardButton(text=t(lang, "rc_participants"), callback_data="rc:list")])
            rows.append([InlineKeyboardButton(text=t(lang, "m_championship"), callback_data="nav:standings")])
        if not rows:
            await event.answer(t(lang, "g_no_race"), parse_mode="HTML")
            return
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        if race is not None:
            from ..flow import weekend_summary

            text = weekend_summary(race)
        else:
            text = t(lang, "g_no_race")
    if isinstance(event, CallbackQuery):
        await show(event, text, markup)
    else:
        await event.answer(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


def _weekend_markup(db, user) -> object:
    lang = _lang(user)
    race = svc.current_race(db)
    if race is None:
        return kb(
            [
                [btn(t(lang, "rc_calendar"), "rc:cal")],
                [btn(t(lang, "m_championship"), "nav:standings")],
                *back_home("nav:menu", lang=lang),
            ]
        )
    entry = svc.entry_of(db, race.id, user.id)
    return race_menu(
        has_entry=entry is not None,
        quali_done=bool(entry and entry.quali_avg > 0),
        can_start=race.status == "open" and race.participants >= store.min_participants(db),
        registration_open=race.status in ("open", "paused"),
        lang=lang,
    )


def _weekend_text(db, user) -> str:
    lang = _lang(user)
    race = svc.current_race(db)
    if race is None:
        upcoming = svc.upcoming_races(db, limit=3)
        nxt = upcoming[0] if upcoming else None
        lines = [t(lang, "rc_no_weekend") + "\n\n"]
        if nxt:
            lines.append(
                f"{t(lang, 'rc_next')} {nxt['flag']} <b>{esc(nxt['gp'])}</b> — "
                f"{esc(nxt['circuit'])}, {nxt['laps']} {t(lang, 'rc_laps')}\n"
            )
        lines.append("\n" + t(lang, "rc_admin_hint"))
        return "".join(lines)

    minimum = store.min_participants(db)
    maximum = store.max_participants(db)
    entry = svc.entry_of(db, race.id, user.id)
    lines = [
        f"{race.flag} <b>{t(lang, 'rc_round')} {race.round_no} — {esc(race.gp_name)}</b>"
        + (f" {t(lang, 'rc_sprint')}" if race.kind == "sprint" else "")
        + "\n",
        f"<i>{esc(race.circuit)}, {esc(race.country)}</i>\n",
        f"🏁 {race.total_laps} {t(lang, 'rc_laps')} · {race.length_km:.3f} km · {t(lang, 'rc_record')} {race.lap_record:.3f}s\n",
        f"{t(lang, 'rc_forecast')}: <b>{svc.weather_label(race.weather)}</b>\n",
        f"{t(lang, 'rc_players')}: <b>{race.participants}/{maximum}</b> ({t(lang, 'rc_min')} {minimum})\n",
    ]
    if race.registration_ends_at is not None:
        end = race.registration_ends_at
        end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        left = int((end - datetime.now(timezone.utc)).total_seconds() // 60)
        lines.append(f"{t(lang, 'rc_closes')} <b>{max(0, left)} {t(lang, 'rc_min2')}</b>\n")
    status = {
        "open": t(lang, "rc_st_open"),
        "paused": t(lang, "rc_st_paused"),
        "live": t(lang, "rc_st_live"),
    }.get(race.status, race.status)
    lines.append(f"{t(lang, 'rc_status')}: <b>{status}</b>\n")

    fee = store.entry_fee(db)
    drivers = economy.get_drivers(db, user)
    salaries = sum(d.salary for d in drivers)
    lines.append(f"\n{t(lang, 'rc_fee')}: <b>{money(fee)}</b> {t(lang, 'rc_salaries')} <b>{money(salaries)}</b>\n")
    lines.append(f"{t(lang, 'rc_prize1')}: <b>{money(svc.prize_for(1, race.kind))}</b>\n")

    if entry is None:
        lines.append("\n" + t(lang, "rc_not_entered"))
    else:
        if entry.quali_avg > 0:
            table = svc.quali_table(db, race)
            pos = next((i for i, e in enumerate(table, start=1) if e.user_id == user.id), 0)
            lines.append(
                f"\n{t(lang, 'rc_your_quali')}: <b>{lap_time(entry.quali_avg)}</b> — P{pos}"
                + (f" ({t(lang, 'rc_grid_slot')} {entry.grid_pos})" if entry.grid_pos else "")
                + "\n"
            )
            for idx, other in enumerate(table[:8], start=1):
                name = "YOU" if other.user_id == user.id else f"player {other.user_id}"
                lines.append(f"  {idx}. {name} — {lap_time(other.quali_avg)}\n")
        else:
            lines.append("\n" + t(lang, "rc_run_quali"))
    return "".join(lines)


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:races")
@router.message(Command("race", "races"))
async def cb_race(event: CallbackQuery | Message) -> None:
    if _in_group(event):
        # groups are race-only, and Join must deep-link into the bot
        return await group_race_screen(event)
    with session() as db:
        user = get_user(db, event.from_user.id, event.from_user.username or "", event.from_user.first_name or "")
        text = _weekend_text(db, user)
        markup = _weekend_markup(db, user)
    await show(event, text, markup)


@router.callback_query(F.data == "rc:info")
async def cb_race_info(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        text, markup = _weekend_text(db, user), _weekend_markup(db, user)
    await show(cb, text, markup)


@router.callback_query(F.data == "rc:join")
async def cb_join(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lang = _lang(user)
        race = svc.current_race(db)
        if race is None:
            await show(cb, t(lang, "rc_no_race"), _weekend_markup(db, user))
            return
        drivers = economy.get_drivers(db, user)
        try:
            total = svc.join_race(db, race, user, drivers)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", _weekend_markup(db, user), alert=str(exc), show_alert=True)
            return
        maximum = store.max_participants(db)
        text = (
            f"{t(lang, 'rc_entered')}\n\n"
            f"{race.flag} {esc(race.gp_name)} — {t(lang, 'rc_cost')} <b>{money(total)}</b>\n"
            f"{t(lang, 'rc_players')}: <b>{race.participants}/{maximum}</b>\n"
            f"{t(lang, 'rc_balance')}: <b>{money(user.balance)}</b>\n\n"
            f"{t(lang, 'rc_next_step')}"
        )
        markup = _weekend_markup(db, user)
    await show(cb, text, markup, alert=t(lang, "rc_entered").replace("*", ""))


@router.callback_query(F.data == "rc:leave")
async def cb_leave(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lang = _lang(user)
        race = svc.current_race(db)
        if race is None:
            await show(cb, t(lang, "rc_no_race"), kb(back_home("nav:menu", lang=lang)))
            return
        try:
            refund = svc.leave_race(db, race, user)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", _weekend_markup(db, user), alert=str(exc), show_alert=True)
            return
        text = (
            f"{t(lang, 'rc_withdraw')} — {esc(race.gp_name)}.\n"
            f"{t(lang, 'rc_refund')}: <b>{money(refund)}</b>\n"
            f"{t(lang, 'rc_balance')}: <b>{money(user.balance)}</b>"
        )
        markup = _weekend_markup(db, user)
    await show(cb, text, markup)


@router.callback_query(F.data == "rc:quali")
async def cb_quali(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lang = _lang(user)
        race = svc.current_race(db)
        if race is None:
            await show(cb, t(lang, "rc_no_race"), kb(back_home("nav:menu", lang=lang)))
            return
        entry = svc.entry_of(db, race.id, user.id)
        if entry is None:
            await show(cb, t(lang, "rc_join_first"), _weekend_markup(db, user), alert=t(lang, "rc_join_first"), show_alert=True)
            return
        if entry.quali_avg > 0:
            await show(
                cb,
                f"{t(lang, 'rc_quali_set')}: <b>{lap_time(entry.quali_avg)}</b>",
                _weekend_markup(db, user),
                alert=t(lang, "rc_quali_set"),
                show_alert=True,
            )
            return
        team = economy.get_team(db, user)
        driver = db.get(Driver, user.driver1_id) if user.driver1_id else None
        levels = economy.driver_levels(db, user.id, driver.id) if driver else {}
        try:
            avg = svc.run_qualifying(db, race, user, team, driver, levels)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", _weekend_markup(db, user), alert=str(exc), show_alert=True)
            return
        times = entry.quali_times or []
        table = svc.quali_table(db, race)
        pos = next((i for i, e in enumerate(table, start=1) if e.user_id == user.id), 0)
        lines = [
            f"{t(lang, 'rc_quali_title')} — {esc(race.gp_name)}\n\n",
            f"{driver.name if driver else 'Your driver'} ({svc.driver_package(driver, levels)['overall']:.0f} OVR)\n",
        ]
        for idx, tm in enumerate(times, start=1):
            lines.append(f"  {t(lang, 'rc_lap')} {idx}: <code>{lap_time(tm)}</code>\n")
        lines.append(f"\n<b>{t(lang, 'rc_avg')}: {lap_time(avg)}</b> — {t(lang, 'rc_now')} <b>P{pos}</b>\n")
        lines.append("\n" + t(lang, "rc_freeze"))
        markup = _weekend_markup(db, user)
    await show(cb, "".join(lines), markup)


@router.callback_query(F.data == "rc:list")
async def cb_participants(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        lang = _lang(user)
        race = svc.current_race(db)
        if race is None:
            await show(cb, t(lang, "rc_no_race"), kb(back_home("nav:menu", lang=lang)))
            return
        entries = list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)))
        ids = [e.user_id for e in entries] or [0]
        users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
        maximum = store.max_participants(db)
        minimum = store.min_participants(db)
        lines = [
            f"{t(lang, 'rc_entry_list')} — {esc(race.gp_name)}\n",
            f"{t(lang, 'rc_players')}: <b>{race.participants}/{maximum}</b> ({t(lang, 'rc_needs')} {minimum})\n\n",
        ]
        if not entries:
            lines.append(t(lang, "rc_nobody"))
        for entry in sorted(entries, key=lambda e: e.quali_avg if e.quali_avg > 0 else 1e9):
            user = users.get(entry.user_id)
            name = (user.first_name or user.username or str(entry.user_id)) if user else str(entry.user_id)
            who = svc.mention(entry.user_id, name)
            time = f"  ⏱️ {lap_time(entry.quali_avg)}" if entry.quali_avg > 0 else f"  {t(lang, 'rc_no_time')}"
            lines.append(f"• <b>{who}</b>{time}\n")
        left = maximum - race.participants
        if left:
            word = t(lang, "rc_free_p") if left > 1 else t(lang, "rc_free")
            lines.append(f"\n<i>{left} {word}</i>")
        markup = kb([[btn(t(lang, "rc_weekend"), "nav:races")], *back_home("nav:menu", lang=lang)])
    await show(cb, "".join(lines), markup)


# --------------------------------------------------------------------------- #
# Extend registration
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "rc:extend")
async def cb_extend_menu(cb: CallbackQuery) -> None:
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        race = svc.current_race(db)
        if race is None:
            await show(cb, "No race weekend is open right now.", kb(back_home("nav:menu")))
            return
        if not settings.is_admin(user.id) and not svc.is_organiser(db, race, user.id):
            await show(
                cb,
                "⛔ Only the admin or the race organiser can extend registration.",
                kb(back_home("nav:races")),
                alert="Not allowed",
                show_alert=True,
            )
            return
        markup = extend_menu(race.id, _lang(user))
    await show(
        cb,
        "⏱️ <b>Extend registration</b>\n\nPick how much extra time the grid should get.",
        markup,
    )


@router.callback_query(F.data.startswith("rcx:"))
async def cb_extend(cb: CallbackQuery) -> None:
    _ns, race_id, minutes = cb.data.split(":")
    race_id, minutes = int(race_id), int(minutes)
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        race = db.get(Race, race_id)
        if race is None:
            await show(cb, "Race not found.", kb(back_home("nav:races")))
            return
        if not settings.is_admin(user.id) and not svc.is_organiser(db, race, user.id):
            await show(cb, "⛔ Not allowed.", kb(back_home("nav:races")), alert="Not allowed", show_alert=True)
            return
        try:
            deadline = svc.extend_registration(db, race, minutes)
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("nav:races")), alert=str(exc), show_alert=True)
            return
        from ..services import adminlog

        adminlog.log(db, user.id, "EXTEND_RACE", None, minutes, f"race {race.id}")
        text = (
            f"⏱️ <b>Registration extended by {minutes} minutes</b>\n\n"
            f"{race.flag} {esc(race.gp_name)}\n"
            f"New deadline: <b>{deadline.strftime('%H:%M UTC')}</b>\n"
            f"👥 Players: <b>{race.participants}/{store.max_participants(db)}</b>"
        )
        markup = _weekend_markup(db, user)
    await show(cb, text, markup)


# --------------------------------------------------------------------------- #
# Start the race (organiser / admin only, once the minimum is reached)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "rc:start")
async def cb_start(cb: CallbackQuery) -> None:
    from ..flow import start_race

    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        race = svc.current_race(db)
        if race is None:
            await show(cb, "No race weekend is open right now.", kb(back_home("nav:races")))
            return
        minimum = store.min_participants(db)
        if race.participants < minimum:
            await show(
                cb,
                f"🚫 A race needs at least <b>{minimum}</b> players.\n"
                f"Currently entered: <b>{race.participants}</b>.",
                kb([[btn("👥 Participants", "rc:list")], *back_home("nav:races")]),
                alert=f"Minimum {minimum} players required",
                show_alert=True,
            )
            return
        if not settings.is_admin(user.id) and not svc.is_organiser(db, race, user.id):
            await show(cb, "⛔ Only the admin or organiser can start the race.", kb(back_home("nav:races", lang=_lang(user))))
            return
        race_id = race.id
    await show(cb, "🚥 <b>Lights out!</b> Simulating the distance, hold on…", kb(back_home("nav:races", lang=_lang(user))))
    # a group press shares the final standings board with the whole chat
    notify_chat = None
    if _in_group(cb):
        notify_chat = getattr(getattr(cb, "message", None), "chat", None)
        notify_chat = getattr(notify_chat, "id", None)
    outcome = await start_race(race_id, force=True, notify_chat_id=notify_chat)
    await show(cb, f"🏁 Weekend finished ({esc(outcome)}). Results are in 📜 Results.", kb(
        [[btn("📜 Results", "nav:results"), btn("🏆 Championship", "nav:standings")], *back_home("nav:menu")]
    ))


@router.message(Command("extend"))
async def cmd_extend(message: Message, command: CommandObject) -> None:
    """/extend 100 — push the registration deadline of the active weekend."""
    from ..flow import extend_weekend

    if not settings.is_admin(message.from_user.id):
        await message.answer("⛔ Only the admin can extend registration.")
        return
    raw = (command.args or "").strip()
    if not raw.isdigit():
        await message.answer("Usage: <code>/extend 100</code> (minutes).")
        return
    minutes = int(raw)
    with session() as db:
        race = svc.current_race(db)
        if race is None:
            await message.answer("No race weekend is open right now.")
            return
        race_id = race.id
    result = await extend_weekend(race_id, minutes, admin_id=message.from_user.id)
    await message.answer(f"⏱️ {esc(result)}")


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "rc:calendar")
async def cb_calendar(cb: CallbackQuery) -> None:
    await _show_calendar(cb)


@router.callback_query(F.data == "rc:cal")
async def cb_calendar_from_menu(cb: CallbackQuery) -> None:
    await _show_calendar(cb)


async def _show_calendar(cb: CallbackQuery) -> None:
    with session() as db:
        rounds = svc.upcoming_races(db, limit=24)
        active = svc.current_race(db)
        lines = ["📅 <b>2026 FIA FORMULA ONE WORLD CHAMPIONSHIP</b>\n\n"]
        items = []
        for info in rounds:
            mark = "▶️" if active and active.round_no == info["r"] else "•"
            sprint = " 🏃" if info.get("sprint") else ""
            lines.append(
                f"{mark} <b>R{info['r']:>2}</b> {info['flag']} {esc(info['gp'])}"
                f" — <i>{esc(info['circuit'])}, {info['laps']} laps{sprint}</i>\n"
            )
            items.append(btn(f"R{info['r']} {info['flag']} {info['gp']}", f"trk:{info['r']}"))
    markup = race_list(items[:24], "nav:races")
    await show(cb, "".join(lines), markup)


@router.callback_query(F.data.startswith("trk:"))
async def cb_track(cb: CallbackQuery) -> None:
    round_no = int(cb.data.split(":")[1])
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        info = svc.round_info(db, round_no)
        active = svc.current_race(db)
        is_next = active is None or info["r"] > active.round_no
        text = (
            f"{info['flag']} <b>ROUND {info['r']} — {esc(info['gp'])}</b>\n"
            f"<i>{esc(info['circuit'])}, {esc(info['country'])}</i>\n\n"
            f"📏 Length: <b>{info['length']:.3f} km</b> · <b>{info['laps']} laps</b> · "
            f"<b>{info['length'] * info['laps']:.1f} km</b> race distance\n"
            f"⏱️ Lap record: <b>{info['rec']:.3f}s</b>\n"
            f"⚔️ Overtaking: <b>{info['over']:.2f}</b>\n"
            f"🌬️ Downforce: <b>{info['down']:.2f}</b>\n"
            f"🛞 Tyre degradation: <b>{info['deg']:.2f}</b>\n"
            f"🚨 Safety car: <b>{info['sc']:.2f}</b>\n"
            f"🌧️ Rain probability: <b>{info['rain']:.2f}</b>\n"
            f"🔧 Reliability stress: <b>{info['stress']:.2f}</b>\n"
            + ("\n🏃 <b>Sprint weekend</b>" if info.get("sprint") else "")
        )
        rows = []
        if is_next:
            rows.append([btn("🏁 Open this weekend", f"rcopen:{info['r']}")])
    await show(cb, text, kb([*rows, *back_home("rc:cal", lang=_lang(user))]))


# --------------------------------------------------------------------------- #
# /arace — the bot runs the race itself (random track + AI drivers), mafia-style
# --------------------------------------------------------------------------- #
@router.message(Command("arace"))
async def cmd_arace(message: Message, command: CommandObject) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return
    from ..flow import open_weekend, start_race

    args = (command.args or "").split() if command else []
    round_no = next((int(a) for a in args if a.isdigit()), None)
    kind = "sprint" if any(a.lower() in ("sprint", "спринт") for a in args) else "gp"
    with session() as db:
        race = svc.current_race(db)
        reused = race is not None
        if race is None:
            # random track card drops and the weekend opens instantly
            try:
                race = open_weekend(db, round_no, kind)
            except ValueError as exc:
                await message.answer(f"❌ {esc(exc)}")
                return
        elif race.status not in ("open", "paused"):
            await message.answer(f"❌ {t('uz', 'rc_no_race')} (status: {race.status})")
            return
        bots = svc.fill_with_bots(db, race)
        race_id, gp, flag, rnd, n = race.id, race.gp_name, race.flag, race.round_no, race.participants
    await message.answer(
        f"🎲 {flag} <b>R{rnd} {esc(gp)}</b> — 🤖 +{len(bots)} AI\n"
        f"👥 {n} · 🚥 simulyatsiya boshlandi…",
        parse_mode="HTML",
    )
    outcome = await start_race(race_id, force=True, notify_chat_id=message.chat.id)
    await message.answer(f"🏁 {esc(outcome)}")


@router.callback_query(F.data.startswith("rcopen:"))
async def cb_open_round(cb: CallbackQuery) -> None:
    from ..flow import announce_weekend, open_weekend

    round_no = int(cb.data.split(":")[1])
    with session() as db:
        user = get_user(db, cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
        if not settings.is_admin(user.id):
            await show(cb, "⛔ Only the admin can open a weekend.", kb(back_home("nav:races")))
            return
        info = svc.round_info(db, round_no)
        try:
            race = open_weekend(db, round_no, "sprint" if info.get("sprint") else "gp")
        except ValueError as exc:
            await show(cb, f"❌ {esc(exc)}", kb(back_home("nav:races")), alert=str(exc), show_alert=True)
            return
        summary = _weekend_text(db, user)
        race_id = race.id
        from ..services import adminlog

        adminlog.log(db, user.id, "CREATE_RACE", None, round_no, info["gp"])
    # arm the auto-start timer so the weekend cannot stall forever
    from ..flow import start_race as flow_start_race
    from ..services.runtime import spawn_auto_start

    spawn_auto_start(max(60, settings.auto_start_minutes * 60), flow_start_race, race_id)
    await announce_weekend(race)
    await show(
        cb,
        f"✅ <b>Weekend opened!</b>\n\n{summary}",
        kb([[btn("🏁 Weekend", "nav:races")], *back_home("nav:menu")]),
    )
