"""Inline keyboard builders.

Every button defined here has a matching handler in :mod:`f1bot.handlers`.
Callback data stays well under Telegram's 64 byte limit and each namespace is
handled by exactly one router, so there are no collisions.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .format import pager


def kb(rows: list[list[dict]]) -> InlineKeyboardMarkup | None:
    """Build markup from ``[{"text": ..., "callback_data": ...}, ...]`` rows.

    A "row" that is itself a block of rows (e.g. ``back_home(...)`` embedded
    without unpacking) is flattened instead of crashing.
    """
    button_rows: list[list[InlineKeyboardButton]] = []
    for row in rows:
        if not row:
            continue
        if isinstance(row[0], (list, tuple)):
            row = [b for sub in row for b in sub if b]
            if not row:
                continue
        cells = [b for b in row if b]
        if not cells:
            continue
        button_rows.append(
            [InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]) for b in cells]
        )
    if not button_rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=button_rows)


def btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def nav_row(target: str = "nav:menu", label: str = "🏠 Main Menu") -> list[dict]:
    return [btn(label, target)]


def back_row(target: str, label: str = "⬅️ Back") -> list[dict]:
    return [btn(label, target)]


def back_home(back_to: str, home: str = "nav:menu") -> list[list[dict]]:
    """The standard ⬅️ Back / 🏠 Main Menu footer used by every submenu."""
    return [back_row(back_to), nav_row(home)]


# --------------------------------------------------------------------------- #
# Main menu
# --------------------------------------------------------------------------- #
def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [btn("👤 Profile", "nav:profile"), btn("🏁 Race", "nav:races")],
        [btn("🏆 Championship", "nav:standings"), btn("👨‍✈️ Drivers", "nav:drivers")],
        [btn("🏎️ Teams", "nav:teams"), btn("🚗 Garage", "nav:garage")],
        [btn("🛒 Shop", "nav:market"), btn("💰 Wallet", "nav:wallet")],
        [btn("📊 Statistics", "nav:stats"), btn("🎁 Daily Bonus", "nav:daily")],
        [btn("⭐ VIP", "nav:vip"), btn("🏅 Achievements", "nav:achievements")],
        [btn("⚙️ Settings", "nav:settings"), btn("ℹ️ Help", "nav:help")],
    ]
    if is_admin:
        rows.append([btn("⚙️ Admin Panel", "nav:admin")])
    return kb(rows)


# --------------------------------------------------------------------------- #
# Shop / market
# --------------------------------------------------------------------------- #
def shop_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🏎️ Teams", "mk:teams:0"), btn("👨‍✈️ Drivers", "mk:drivers:0")],
            [btn("🔧 Upgrades", "gar:upgrades"), btn("🛞 Tires", "sto:tires")],
            [btn("🎨 Cosmetics", "sto:cosmetics"), btn("⭐ VIP", "sto:vip")],
            [btn("🪙 Gold", "sto:gold")],
            [btn("💼 My contracts", "mk:mine")],
            back_row("nav:menu"),
            nav_row(),
        ]
    )


def store_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🛞 Tires", "sto:tires"), btn("🎨 Cosmetics", "sto:cosmetics")],
            [btn("⭐ VIP", "sto:vip"), btn("🪙 Gold", "sto:gold")],
            back_row("nav:market"),
            nav_row(),
        ]
    )


def pager_row(page: int, pages: int, template: str) -> list[dict]:
    return pager(page, pages, template)


def market_list(
    items: list[dict], page: int, pages: int, template: str, back_to: str
) -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1:
        rows.append(pager_row(page, pages, template))
    rows.append([btn("🔃 Refresh prices", "mk:refresh")])
    rows += back_home(back_to)
    return kb(rows)


def driver_slot_picker(driver_id: int, slots: list[int], back_to: str) -> InlineKeyboardMarkup:
    rows = [[btn(f"Seat {s}", f"mk:buys:{driver_id}:{s}")] for s in slots]
    rows += back_home(back_to)
    return kb(rows)


def buy_confirm(item_id: str, back_to: str) -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("✅ Confirm purchase", f"mk:confirm:{item_id}")],
            back_home(back_to),
        ]
    )


def contracts_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🏎️ Constructors", "mk:teams:0"), btn("👨‍✈️ Drivers", "mk:drivers:0")],
            back_home("nav:menu"),
        ]
    )


# --------------------------------------------------------------------------- #
# Garage
# --------------------------------------------------------------------------- #
def garage_menu(has_team: bool) -> InlineKeyboardMarkup:
    rows = [
        [btn("🔧 Car development", "gar:upgrades")],
        [btn("👨‍✈️ Driver 1 training", "gar:driver:1")],
        [btn("👨‍✈️ Driver 2 training", "gar:driver:2")],
        [btn("💼 My contracts", "mk:mine")],
    ]
    if not has_team:
        rows.insert(0, [btn("🛒 Buy a constructor first", "mk:teams:0")])
    rows += back_home("nav:menu")
    return kb(rows)


def _pairs(items: list[dict]) -> list[list[dict]]:
    """Pack one-per-row buttons into a two-column grid."""
    return [items[i : i + 2] for i in range(0, len(items), 2)]


def upgrade_list(items: list[dict], back_to: str) -> InlineKeyboardMarkup:
    rows = _pairs(items)
    rows += back_home(back_to)
    return kb(rows)


def driver_training_list(items: list[dict], back_to: str) -> InlineKeyboardMarkup:
    rows = _pairs(items)
    rows += back_home(back_to)
    return kb(rows)


# --------------------------------------------------------------------------- #
# Races
# --------------------------------------------------------------------------- #
def race_menu(
    has_entry: bool = False,
    quali_done: bool = False,
    can_start: bool = False,
    registration_open: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[dict]] = []
    if not has_entry:
        rows.append([btn("🏎️ JOIN RACE", "rc:join")])
    else:
        if not quali_done and registration_open:
            rows.append([btn("⏱️ Run qualifying", "rc:quali")])
        elif not quali_done:
            rows.append([btn("⏳ Waiting for lights out", "noop")])
        if registration_open:
            rows.append([btn("❌ Leave Race", "rc:leave")])
    rows += [
        [btn("👥 Participants", "rc:list")],
        [btn("⏱️ Extend Registration", "rc:extend")],
        [btn("🏁 Start Race", "rc:start")] if can_start else [],
        [btn("🏆 Championship", "nav:standings")],
        back_row("nav:menu"),
        nav_row(),
    ]
    return kb(rows)


def extend_menu(race_id: int) -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("+10 min", f"rcx:{race_id}:10"), btn("+30 min", f"rcx:{race_id}:30")],
            [btn("+60 min", f"rcx:{race_id}:60"), btn("+100 min", f"rcx:{race_id}:100")],
            back_row("rc:info"),
            nav_row(),
        ]
    )


def race_list(races: list[dict], back_to: str = "nav:races") -> InlineKeyboardMarkup:
    rows = [[btn(r["text"], r["callback_data"])] for r in races]
    rows += back_home(back_to)
    return kb(rows)


# --------------------------------------------------------------------------- #
# Wallet / bonus / VIP
# --------------------------------------------------------------------------- #
def wallet_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("📜 Transactions", "wal:tx")],
            [btn("🎁 Daily Bonus", "nav:daily")],
            [btn("🪙 Gold Shop", "sto:gold")],
            back_home("nav:menu"),
        ]
    )


def transactions_menu(page: int, pages: int) -> InlineKeyboardMarkup:
    rows = []
    if pages > 1:
        rows.append(pager_row(page, pages, f"wal:tx:{page}"))
    rows.append([btn("🪙 Gold only", "wal:txg")])
    rows += back_home("nav:wallet")
    return kb(rows)


def daily_menu(available: bool) -> InlineKeyboardMarkup:
    rows = [[btn("🎁 Claim Daily Bonus", "dly:claim")]] if available else []
    rows += back_home("nav:menu")
    return kb(rows)


def vip_menu() -> InlineKeyboardMarkup:
    rows = [[btn(f"VIP {lvl}", f"vip:lvl:{lvl}")] for lvl in range(1, 6)]
    rows.append([btn("⭐ Buy VIP with Gold", "sto:vip")])
    rows += back_home("nav:menu")
    return kb(rows)


def achievements_menu(items: list[dict]) -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    rows += back_home("nav:menu")
    return kb(rows)


def stats_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🙋 My statistics", "sta:me"), btn("🌍 Global statistics", "sta:global")],
            [btn("🏆 Championship", "nav:standings"), btn("📜 Recent results", "nav:results")],
            back_home("nav:menu"),
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return kb([back_home("nav:menu")])


def standings_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("👨‍✈️ Drivers", "std:drivers"), btn("🏎️ Constructors", "std:teams")],
            back_home("nav:menu"),
        ]
    )


def confirm_kb(ok_cb: str, cancel_cb: str, ok_label: str = "✅ Confirm", cancel_label: str = "❌ Cancel") -> InlineKeyboardMarkup:
    return kb([[btn(ok_label, ok_cb), btn(cancel_label, cancel_cb)]])


def ok_kb(cb: str, label: str = "⬅️ Back") -> InlineKeyboardMarkup:
    return kb([[btn(label, cb)]])


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
def admin_main() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("👥 Users", "adm:users"), btn("🏁 Races", "adm:race")],
            [btn("🏎️ Teams", "adm:teams"), btn("👨‍✈️ Drivers", "adm:drivers")],
            [btn("🗺️ Tracks", "adm:tracks"), btn("🏆 Championship", "adm:champ")],
            [btn("💰 Economy", "adm:economy"), btn("🪙 Gold", "adm:gold")],
            [btn("⭐ VIP", "adm:vip"), btn("📢 Broadcast", "adm:bcast")],
            [btn("🚫 Moderation", "adm:mod"), btn("🎁 Rewards", "adm:rewards")],
            [btn("📊 Statistics", "adm:stats"), btn("⚙️ Settings", "adm:settings")],
            [btn("📜 Admin Logs", "adm:logs")],
            nav_row(),
        ]
    )


def admin_users_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🔎 Search User", "adm:usearch")],
            [btn("👥 All Users", "adm:ulist:0")],
            [btn("🚫 Banned Users", "adm:ubanned")],
            back_row("adm:home"),
            nav_row(),
        ]
    )


def admin_user_menu(user_id: int, banned: bool, vip: bool) -> InlineKeyboardMarkup:
    rows = [
        [btn("💰 Give Money", f"adm:cash:{user_id}"), btn("💸 Remove Money", f"adm:cashminus:{user_id}")],
        [btn("🪙 Give Gold", f"adm:gold:{user_id}"), btn("💎 Remove Gold", f"adm:goldminus:{user_id}")],
        [btn("⭐ Give VIP", f"adm:vipg:{user_id}"), btn("❌ Remove VIP", f"adm:viprm:{user_id}")],
    ]
    if banned:
        rows.append([btn("✅ Unban", f"adm:unban:{user_id}")])
    else:
        rows.append([btn("🚫 Ban", f"adm:ban:{user_id}")])
    rows += [
        [btn("📊 Statistics", f"adm:ustat:{user_id}"), btn("📜 Transactions", f"adm:utx:{user_id}")],
        [btn("🔄 Reset Progress", f"adm:ureset:{user_id}")],
        back_row("adm:users"),
        nav_row(),
    ]
    return kb(rows)


def admin_list_menu(items: list[dict], back_to: str, page: int = 0, pages: int = 1, template: str = "") -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1 and template:
        rows.append(pager_row(page, pages, template))
    rows.append(back_row(back_to))
    rows.append(nav_row())
    return kb(rows)


def admin_race_menu(race_id: int, status: str, paused: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[dict]] = []
    if status == "open":
        rows.append([btn("⏸️ Pause Registration", f"admr:pause:{race_id}")])
    elif status == "paused":
        rows.append([btn("▶️ Resume Registration", f"admr:open:{race_id}")])
    rows += [
        [btn("⏱️ Extend", f"admr:ext:{race_id}")],
        [btn("▶️ Start Race", f"admr:start:{race_id}")],
        [btn("👥 Participants", f"admr:part:{race_id}")],
        [btn("📊 Results", f"admr:res:{race_id}")],
        [btn("❌ Cancel Race", f"admr:cancel:{race_id}")],
        [btn("➕ Create New Race", "admr:new")],
        back_row("nav:admin"),
        nav_row(),
    ]
    return kb(rows)


def admin_crud_menu(kind: str, items: list[dict], add_cb: str, back_to: str, page: int = 0, pages: int = 1, template: str = "") -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1 and template:
        rows.append(pager_row(page, pages, template))
    rows.append([btn("➕ Add new", add_cb)])
    rows.append(back_row(back_to))
    rows.append(nav_row())
    return kb(rows)


def admin_edit_menu(kind: str, item_id: int, fields: list[tuple[str, str, object]], back_to: str) -> InlineKeyboardMarkup:
    rows = []
    pairs = list(zip(fields[::2], fields[1::2]))
    for a, b in pairs:
        rows.append([btn(f"{a[1]}: {a[2]}", f"ade:{kind}:{item_id}:{a[0]}"), btn(f"{b[1]}: {b[2]}", f"ade:{kind}:{item_id}:{b[0]}")])
    if len(fields) % 2:
        a = fields[-1]
        rows.append([btn(f"{a[1]}: {a[2]}", f"ade:{kind}:{item_id}:{a[0]}")])
    rows.append([btn("❌ Delete", f"adm:del:{kind}:{item_id}")])
    rows.append(back_row(back_to))
    rows.append(nav_row())
    return kb(rows)


def admin_broadcast_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("👥 All Users", "adb:all"), btn("⭐ VIP Users", "adb:vip")],
            [btn("🏁 Active Users", "adb:active"), btn("🎯 Specific User", "adb:one")],
            back_row("nav:admin"),
            nav_row(),
        ]
    )


def admin_broadcast_confirm(count: int) -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("✅ Send", "adbs:yes"), btn("❌ Cancel", "adbs:no")],
            back_row("adm:bcast"),
        ]
    )


def admin_moderation_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🚫 Ban a user", "adm:usearch")],
            [btn("🔓 Ban history", "adm:bans")],
            back_row("nav:admin"),
            nav_row(),
        ]
    )


def admin_rewards_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("🎁 Daily cash", "admset:daily_cash"), btn("🪙 Daily gold", "admset:daily_gold")],
            [btn("✨ Daily XP", "admset:daily_xp"), btn("🥇 Prize for P1", "admset:prize_1st")],
            [btn("⚡ Fastest lap bonus", "admset:fastest_lap_bonus"), btn("🎟️ Entry fee", "admset:entry_fee")],
            [btn("🏅 Achievements", "adbr:achv")],
            back_row("adm:home"),
            nav_row(),
        ]
    )


def admin_economy_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("💵 Race rewards", "admset:prize_1st"), btn("🎟️ Entry fee", "admset:entry_fee")],
            [btn("🔧 Upgrade prices", "admset:upgrade_base_cost"), btn("👨‍✈️ Training prices", "admset:driver_upgrade_base_cost")],
            [btn("🪙 Gold price", "admset:gold_price"), btn("💸 Resale ratio %", "admset:sell_ratio_pct")],
            [btn("📈 Refresh driver prices", "adbe:refresh")],
            back_row("adm:home"),
            nav_row(),
        ]
    )


def admin_settings_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("👥 Min participants", "admset:min_participants"), btn("👥 Max participants", "admset:max_participants")],
            [btn("⏱️ Registration minutes", "admset:registration_minutes")],
            [btn("🔃 Reset market", "adbs:resetmk"), btn("🗑️ Wipe all data", "adbs:wipe")],
            [btn("♻️ Reload 2026 data", "adm:reload")],
            back_row("adm:home"),
            nav_row(),
        ]
    )


def admin_ban_menu(user_id: int) -> InlineKeyboardMarkup:
    from .services import moderation

    rows = []
    pairs = list(zip(moderation.DURATIONS[::2], moderation.DURATIONS[1::2]))
    for a, b in pairs:
        rows.append([btn(f"🚫 {a[0]}", f"admb:{user_id}:{a[1]}"), btn(f"🚫 {b[0]}", f"admb:{user_id}:{b[1]}")])
    if len(moderation.DURATIONS) % 2:
        a = moderation.DURATIONS[-1]
        rows.append([btn(f"🚫 {a[0]}", f"admb:{user_id}:{a[1]}")])
    rows.append([btn("✅ Do not ban", f"adm:user:{user_id}")])
    return kb(rows)


def admin_vip_level_menu(user_id: int) -> InlineKeyboardMarkup:
    rows = [[btn(f"VIP {lvl}", f"admvi:l:{user_id}:{lvl}") for lvl in range(1, 4)]]
    rows.append([btn("VIP 4", f"admvi:l:{user_id}:4"), btn("VIP 5", f"admvi:l:{user_id}:5")])
    rows.append(back_row(f"adm:user:{user_id}"))
    return kb(rows)


def admin_vip_days_menu(user_id: int, level: int) -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("7 days", f"admvi:d:{user_id}:{level}:7"), btn("30 days", f"admvi:d:{user_id}:{level}:30")],
            [btn("90 days", f"admvi:d:{user_id}:{level}:90"), btn("♾️ Permanent", f"admvi:d:{user_id}:{level}:0")],
            back_row(f"adm:vipg:{user_id}"),
        ]
    )
