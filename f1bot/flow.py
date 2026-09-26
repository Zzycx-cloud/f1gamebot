"""Race weekend flow used by handlers, admin tools and background jobs.

Ties the pure race engine together with the bot: it opens weekends, runs the
simulation, broadcasts it, pays the prizes and announces the next round.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import session
from .format import esc, money
from .i18n import t
from .keyboards import kb, nav_row
from .models import Driver, Race, RaceEntry, Team, User
from .services import achievements, economy, notify, vip
from .services import races as svc
from .services.runtime import get_bot, mark_race_handled, race_already_handled


# --------------------------------------------------------------------------- #
# Opening a weekend
# --------------------------------------------------------------------------- #
def open_weekend(db: Session, round_no: int | None = None, kind: str = "gp") -> Race:
    existing = svc.current_race(db)
    if existing is not None:
        raise ValueError(f"Weekend R{existing.round_no} {existing.gp_name} is already running.")
    return svc.create_race(db, round_no, kind)


def weekend_summary(race: Race) -> str:
    status = {
        "open": "🟢 registration open",
        "paused": "⏸️ registration paused",
        "live": "🚥 lights out — race in progress",
        "finished": "🏁 finished",
        "cancelled": "❌ cancelled",
    }.get(race.status, race.status)
    deadline = ""
    if race.registration_ends_at is not None:
        end = race.registration_ends_at
        end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        left = int((end - datetime.now(timezone.utc)).total_seconds() // 60)
        deadline = f"\n⏳ Registration closes in <b>{max(0, left)} min</b>"
    minimum = settings.min_participants
    return (
        f"{race.flag} <b>ROUND {race.round_no} — {esc(race.gp_name)}</b>{' 🏃 SPRINT' if race.kind == 'sprint' else ''}\n"
        f"<i>{esc(race.circuit)}, {esc(race.country)}</i>\n"
        f"🏁 {race.total_laps} laps · lap record {race.lap_record:.3f}s · {svc.weather_label(race.weather)}\n"
        f"Status: {status} · 👥 Players: <b>{race.participants}/{settings.max_participants}</b>"
        f" (min {minimum})"
        f"{deadline}\n"
        f"Entry fee: <b>{money(settings.entry_fee)}</b> + driver salaries\n"
        f"🏆 Winner prize: <b>{money(svc.prize_for(1, race.kind))}</b>"
    )


async def announce_weekend(race: Race) -> tuple[int, int, int]:
    bot = get_bot()
    if bot is None or not settings.lobby_notify:
        return (0, 0, 0)
    with session() as db:
        users = notify.audience(db, "active")
    text = f"🏁 <b>New race weekend!</b>\n\n{weekend_summary(race)}\n\nRun qualifying and take the chequered flag."
    markup = kb([[{"text": "🏎️ JOIN RACE", "callback_data": "rc:join"}], nav_row()])
    return await notify.send_to_users(bot, users, text, markup)


# --------------------------------------------------------------------------- #
# Running the race
# --------------------------------------------------------------------------- #
def _build_sim_entries(db: Session, race: Race, grid: list[RaceEntry]) -> tuple[list[svc.SimEntrant], dict[int, str]]:
    sim_entries: list[svc.SimEntrant] = []
    names: dict[int, str] = {}
    for entry in grid:
        user = db.get(User, entry.user_id)
        if user is None:
            continue
        team = economy.get_team(db, user)
        drivers = economy.get_drivers(db, user)
        lead = drivers[0] if drivers else None
        levels = economy.driver_levels(db, user.id, lead.id) if lead else {}
        package = svc.driver_package(lead, levels)
        sim_entries.append(
            svc.SimEntrant(
                user_id=user.id,
                name=user.first_name or user.username or str(user.id),
                car=svc.car_strength(user, team),
                package=svc.car_package(user, team),
                drivers=[package],
                quali_avg=entry.quali_avg,
                grid_pos=entry.grid_pos,
            )
        )
        names[user.id] = user.first_name or user.username or str(user.id)
    return sim_entries, names


async def start_race(race_id: int, force: bool = False, notify_chat_id: int | None = None) -> str:
    """Freeze the grid, simulate the distance, broadcast it and pay the prizes."""
    if race_already_handled(race_id):
        return "already handled"

    bot = get_bot()
    with session() as db:
        race = db.get(Race, race_id)
        if race is None or race.status == "finished":
            return "no race"
        entries = list(db.scalars(select(RaceEntry).where(RaceEntry.race_id == race.id)))
        minimum = settings.min_participants
        if len(entries) < minimum and not force:
            refunded = svc.cancel_race(db, race, f"only {len(entries)} entries (minimum {minimum})")
            return f"cancelled:{len(refunded)}"
        if not entries:
            race.status = "cancelled"
            race.finished_at = datetime.now(timezone.utc)
            return "empty grid"

        weather = svc.pick_weather({"rain": race.rain_prob})
        grid = svc.build_grid(db, race, weather=weather)
        sim_entries, names = _build_sim_entries(db, race, grid)
        race.status = "live"
        race.started_at = datetime.now(timezone.utc)
        race.weather = weather
        chat_ids = notify.participant_chat_ids(db, race.id) or [
            notify.owner_chat_id(db, settings.super_admin_id)
        ]
        if notify_chat_id:
            chat_ids = [notify_chat_id] + [c for c in chat_ids if c != notify_chat_id]

    if not sim_entries:
        return "no entrants"

    mark_race_handled(race_id)
    sim = svc.simulate_race(sim_entries, race, weather=weather)

    if bot is not None:
        for chat_id in chat_ids[: max(1, settings.max_participants)]:
            if chat_id <= 0:
                continue
            try:
                await svc.broadcast_race(bot, chat_id, race, sim, names)
            except Exception:
                pass

    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            return "race vanished"
        svc.apply_results(db, race, sim)
        classification = svc.race_classification(db, race.id)
        unlocked = achievements.check_all(db)
        season = svc.season_standings(db, limit=1)
        gp, flag, round_no, kind = race.gp_name, race.flag, race.round_no, race.kind
        results = [
            (e.user_id, e.finish_pos, e.points, e.money_won, e.gold_won, e.dnf, e.gap, e.pit_stops)
            for e in classification
        ]
        user_ids = [e.user_id for e in classification] or [0]
        users_map = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        final_text = race_standings_text(race, classification, users_map)
        next_race = None
        try:
            next_race = open_weekend(db)
        except ValueError:
            pass
        winner = classification[0] if classification else None

    if bot is not None:
        for user_id, pos, points, prize, gold, dnf, gap, stops in results:
            if user_id <= 0:  # AI drivers have no private chat
                continue
            marker = "💥 Retired" if dnf else f"P{pos}"
            gap_txt = "" if dnf or pos == 1 else f"\nGap: <i>+{gap:.3f}s</i>"
            text = (
                f"{flag} <b>Round {round_no} — {esc(gp)}</b>{' 🏃 Sprint' if kind == 'sprint' else ''}\n"
                f"Your result: <b>{marker}</b> · 🛞 {stops} pit stops{gap_txt}\n"
                f"Championship points: <b>+{points}</b>\n"
                f"Prize money: <b>{money(prize)}</b>"
                + (f"\nGold: <b>+{gold}</b> 🪙" if gold else "")
            )
            try:
                await bot.send_message(user_id, text, reply_markup=kb([nav_row()]), parse_mode="HTML")
            except Exception:
                pass

        for user_id, titles in unlocked:
            for title in titles:
                try:
                    await bot.send_message(
                        user_id,
                        f"🏅 <b>Achievement unlocked!</b>\n<b>{esc(title)}</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        if winner is not None and winner.finish_pos == 1:
            champion = season[0][0] if season else None
            if champion is not None:
                text = (
                    f"🏆 <b>Championship leader after {flag} {esc(gp)}</b>\n"
                    f"{esc(champion.first_name or champion.username or champion.id)} — <b>{champion.race_points}</b> points"
                )
                for user_id, *_rest in results:
                    try:
                        await bot.send_message(user_id, text, parse_mode="HTML")
                    except Exception:
                        pass

        # the shared "race finished" standings go to the group / origin chat
        if notify_chat_id and bot is not None:
            try:
                await bot.send_message(notify_chat_id, final_text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

        if next_race is not None:
            await announce_weekend(next_race)
    return "finished"


def race_standings_text(race: Race, classification, users: dict) -> str:
    """The shared 'Poyga tugadi' board: who finished where and what they won."""
    lines = ["🏁 <b>POYGA TUGADI · ГОНКА ЗАВЕРШЕНА · RACE FINISHED</b>\n"]
    lines.append(f"{race.flag} <b>{esc(race.gp_name)}</b> — {race.total_laps} {t('en', 'r_laps')}\n\n")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for e in classification:
        user = users.get(e.user_id)
        name = (user.first_name or user.username or str(e.user_id)) if user else str(e.user_id)
        who = svc.mention(e.user_id, name)
        if e.dnf:
            lines.append(f"💥 {who} — <i>DNF</i>\n")
        else:
            medal = medals.get(e.finish_pos, f"{e.finish_pos}.")
            gold = f" · 🪙{e.gold_won}" if e.gold_won else ""
            lines.append(f"{medal} {who} — <b>+{money(e.money_won)}</b> · {e.points} {t('en', 'r_pts')}{gold}\n")
    return "".join(lines)


async def extend_weekend(race_id: int, minutes: int, admin_id: int = 0) -> str:
    """Push the registration deadline forward (used by /extend and the buttons)."""
    with session() as db:
        race = db.get(Race, race_id)
        if race is None:
            return "Race not found."
        try:
            deadline = svc.extend_registration(db, race, minutes)
        except ValueError as exc:
            return str(exc)
        text = (
            f"⏱️ <b>Registration extended by {minutes} minutes</b>\n"
            f"{race.flag} {esc(race.gp_name)} — new deadline "
            f"{deadline.strftime('%H:%M UTC')}\n👥 Players: {race.participants}/{settings.max_participants}"
        )
        users = notify.participant_chat_ids(db, race.id)
    from .services import adminlog

    with session() as db:
        if admin_id:
            adminlog.log(db, admin_id, "EXTEND_RACE", race_id, minutes, "ok")
    bot = get_bot()
    if bot is not None:
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode="HTML")
            except Exception:
                pass
    return f"Extended {race_id} by {minutes} minutes."
