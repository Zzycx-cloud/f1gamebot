"""Inline keyboard builders.

Every button defined here has a matching handler in :mod:`f1bot.handlers`.
Callback data stays well under Telegram's 64 byte limit and each namespace is
handled by exactly one router, so there are no collisions.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .format import pager
from .i18n import t


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


def nav_row(target: str = "nav:back", label: str | None = None, lang: str = "en") -> list[dict]:
    """The footer button. History-based Back unless an explicit target is given."""
    return [btn(label or t(lang, "back"), target)]


def back_row(target: str, label: str | None = None, lang: str = "en") -> list[dict]:
    if target == "nav:back":
        return nav_row("nav:back", label, lang)
    return [btn(label or t(lang, "back"), target)]


def back_home(back_to: str, home: str = "nav:menu", lang: str = "en") -> list[list[dict]]:
    """One ⬅️ Back button: returns to the menu the screen was opened from."""
    return [back_row(back_to, lang=lang)]


# --------------------------------------------------------------------------- #
# Language picker
# --------------------------------------------------------------------------- #
def language_menu() -> InlineKeyboardMarkup:
    from .i18n import LANGS

    rows = [[btn(name, f"lang:set:{code}")] for code, name in LANGS.items()]
    return kb(rows)


# --------------------------------------------------------------------------- #
# Main menu
# --------------------------------------------------------------------------- #
def main_menu(is_admin: bool = False, lang: str = "en", in_group: bool = False) -> InlineKeyboardMarkup:
    """Private chat: the full game menu. Groups get race controls only."""
    if in_group:
        return kb(
            [
                [btn(t(lang, "m_race"), "nav:races")],
                [btn(t(lang, "rc_participants"), "rc:list")],
                [btn(t(lang, "m_championship"), "nav:standings")],
            ]
        )
    rows = [
        [btn(t(lang, "m_profile"), "nav:profile"), btn(t(lang, "m_race"), "nav:races")],
        [btn(t(lang, "m_championship"), "nav:standings"), btn(t(lang, "m_drivers"), "nav:drivers")],
        [btn(t(lang, "m_teams"), "nav:teams"), btn(t(lang, "m_garage"), "nav:garage")],
        [btn(t(lang, "m_shop"), "nav:market"), btn(t(lang, "m_wallet"), "nav:wallet")],
        [btn(t(lang, "m_stats"), "nav:stats"), btn(t(lang, "m_daily"), "nav:daily")],
        [btn(t(lang, "m_vip"), "nav:vip"), btn(t(lang, "m_ach"), "nav:achievements")],
        [btn(t(lang, "m_settings"), "nav:settings"), btn(t(lang, "m_help"), "nav:help")],
    ]
    if is_admin:
        rows.append([btn(t(lang, "m_admin"), "nav:admin")])
    return kb(rows)


# --------------------------------------------------------------------------- #
# Shop / market
# --------------------------------------------------------------------------- #
def shop_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "m_teams"), "mk:teams:0"), btn(t(lang, "m_drivers"), "mk:drivers:0")],
            [btn(t(lang, "sh_upgrades"), "gar:upgrades"), btn(t(lang, "sh_tires"), "sto:tires")],
            [btn(t(lang, "sh_cosmetics"), "sto:cosmetics"), btn(t(lang, "ap_vip"), "sto:vip")],
            [btn(t(lang, "w_gold_shop"), "sto:gold")],
            [btn(t(lang, "sh_contracts"), "mk:mine")],
            back_row("nav:menu", lang=lang),
        ]
    )


def store_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "sh_tires"), "sto:tires"), btn(t(lang, "sh_cosmetics"), "sto:cosmetics")],
            [btn(t(lang, "ap_vip"), "sto:vip"), btn(t(lang, "w_gold_shop"), "sto:gold")],
            back_row("nav:market", lang=lang),
        ]
    )


def pager_row(page: int, pages: int, template: str) -> list[dict]:
    return pager(page, pages, template)


def market_list(
    items: list[dict], page: int, pages: int, template: str, back_to: str, lang: str = "en"
) -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1:
        rows.append(pager_row(page, pages, template))
    rows.append([btn(t(lang, "g_refresh"), "mk:refresh")])
    rows += back_home(back_to, lang=lang)
    return kb(rows)


def driver_slot_picker(driver_id: int, slots: list[int], back_to: str, lang: str = "en") -> InlineKeyboardMarkup:
    rows = [[btn(f"{t(lang, 'g_seat')} {s}", f"mk:buys:{driver_id}:{s}")] for s in slots]
    rows += back_home(back_to, lang=lang)
    return kb(rows)


def buy_confirm(item_id: str, back_to: str, lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "g_confirm"), f"mk:confirm:{item_id}")],
            back_home(back_to, lang=lang),
        ]
    )


def contracts_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "m_teams"), "mk:teams:0"), btn(t(lang, "m_drivers"), "mk:drivers:0")],
            back_home("nav:menu", lang=lang),
        ]
    )


# --------------------------------------------------------------------------- #
# Garage
# --------------------------------------------------------------------------- #
def garage_menu(has_team: bool, lang: str = "en") -> InlineKeyboardMarkup:
    rows = [
        [btn(t(lang, "g_car_dev"), "gar:upgrades")],
        [btn(t(lang, "g_d1"), "gar:driver:1")],
        [btn(t(lang, "g_d2"), "gar:driver:2")],
        [btn(t(lang, "sh_contracts"), "mk:mine")],
    ]
    if not has_team:
        rows.insert(0, [btn(t(lang, "g_buy_first"), "mk:teams:0")])
    rows += back_home("nav:menu", lang=lang)
    return kb(rows)


def _pairs(items: list[dict]) -> list[list[dict]]:
    """Pack one-per-row buttons into a two-column grid."""
    return [items[i : i + 2] for i in range(0, len(items), 2)]


def upgrade_list(items: list[dict], back_to: str, lang: str = "en") -> InlineKeyboardMarkup:
    rows = _pairs(items)
    rows += back_home(back_to, lang=lang)
    return kb(rows)


def driver_training_list(items: list[dict], back_to: str, lang: str = "en") -> InlineKeyboardMarkup:
    rows = _pairs(items)
    rows += back_home(back_to, lang=lang)
    return kb(rows)


# --------------------------------------------------------------------------- #
# Races
# --------------------------------------------------------------------------- #
def race_menu(
    has_entry: bool = False,
    quali_done: bool = False,
    can_start: bool = False,
    registration_open: bool = True,
    lang: str = "en",
) -> InlineKeyboardMarkup:
    rows: list[list[dict]] = []
    if not has_entry:
        rows.append([btn(t(lang, "rc_join"), "rc:join")])
    else:
        if not quali_done and registration_open:
            rows.append([btn(t(lang, "rc_quali"), "rc:quali")])
        elif not quali_done:
            rows.append([btn(t(lang, "rc_wait"), "noop")])
        if registration_open:
            rows.append([btn(t(lang, "rc_leave"), "rc:leave")])
    rows += [
        [btn(t(lang, "rc_participants"), "rc:list")],
        [btn(t(lang, "rc_extend"), "rc:extend")],
        [btn(t(lang, "rc_start"), "rc:start")] if can_start else [],
        [btn(t(lang, "m_championship"), "nav:standings")],
        back_row("nav:menu", lang=lang),
    ]
    return kb(rows)


def extend_menu(race_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("+10 min", f"rcx:{race_id}:10"), btn("+30 min", f"rcx:{race_id}:30")],
            [btn("+60 min", f"rcx:{race_id}:60"), btn("+100 min", f"rcx:{race_id}:100")],
            back_row("rc:info", lang=lang),
        ]
    )


def race_list(races: list[dict], back_to: str = "nav:races") -> InlineKeyboardMarkup:
    rows = [[btn(r["text"], r["callback_data"])] for r in races]
    rows += back_home(back_to)
    return kb(rows)


# --------------------------------------------------------------------------- #
# Wallet / bonus / VIP
# --------------------------------------------------------------------------- #
def wallet_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "w_tx"), "wal:tx")],
            [btn(t(lang, "m_daily"), "nav:daily")],
            [btn(t(lang, "w_gold_shop"), "sto:gold")],
            back_home("nav:menu", lang=lang),
        ]
    )


def transactions_menu(page: int, pages: int, lang: str = "en") -> InlineKeyboardMarkup:
    rows = []
    if pages > 1:
        rows.append(pager_row(page, pages, f"wal:tx:{page}"))
    rows.append([btn(t(lang, "w_gold_only"), "wal:txg")])
    rows += back_home("nav:wallet", lang=lang)
    return kb(rows)


def daily_menu(available: bool, lang: str = "en") -> InlineKeyboardMarkup:
    rows = [[btn(t(lang, "d_claim"), "dly:claim")]] if available else []
    rows += back_home("nav:menu", lang=lang)
    return kb(rows)


def vip_menu(lang: str = "en") -> InlineKeyboardMarkup:
    rows = [[btn(f"VIP {lvl}", f"vip:lvl:{lvl}")] for lvl in range(1, 6)]
    rows.append([btn(t(lang, "v_buygold"), "sto:vip")])
    rows += back_home("nav:menu", lang=lang)
    return kb(rows)


def achievements_menu(items: list[dict], lang: str = "en") -> InlineKeyboardMarkup:
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    rows += back_home("nav:menu", lang=lang)
    return kb(rows)


def stats_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "s_me"), "sta:me"), btn(t(lang, "s_global"), "sta:global")],
            [btn(t(lang, "m_championship"), "nav:standings"), btn(t(lang, "s_results"), "nav:results")],
            back_home("nav:menu", lang=lang),
        ]
    )


def settings_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "set_lang"), "nav:lang")],
            back_home("nav:menu", lang=lang),
        ]
    )


def standings_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return kb(
        [
            [btn(t(lang, "m_drivers"), "std:drivers"), btn(t(lang, "m_teams"), "std:teams")],
            back_home("nav:menu", lang=lang),
        ]
    )


def confirm_kb(ok_cb: str, cancel_cb: str, ok_label: str = "✅ Confirm", cancel_label: str = "❌ Cancel") -> InlineKeyboardMarkup:
    return kb([[btn(ok_label, ok_cb), btn(cancel_label, cancel_cb)]])


def ok_kb(cb: str, label: str = "⬅️ Back") -> InlineKeyboardMarkup:
    return kb([[btn(label, cb)]])


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
def _admin_lang(lang: str) -> str:
    """Resolve the admin panel language: explicit, else the super admin's saved
    language, else English. Keeps every admin call site simple."""
    if lang in ("ru", "uz", "en"):
        return lang
    from .config import SUPER_ADMIN_ID

    try:
        from .db import session
        from .models import User

        with session() as db:
            row = db.get(User, SUPER_ADMIN_ID)
            if row is not None and row.language in LANGS:
                return row.language
    except Exception:
        pass
    return "en"


def admin_main(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_players"), "adm:users"), btn(t(lang, "ap_races"), "adm:race")],
            [btn(t(lang, "ap_teams"), "adm:teams"), btn(t(lang, "ap_drivers"), "adm:drivers")],
            [btn(t(lang, "ap_tracks"), "adm:tracks"), btn(t(lang, "ap_champ"), "adm:champ")],
            [btn(t(lang, "ap_economy"), "adm:economy"), btn(t(lang, "ap_gold"), "adm:gold")],
            [btn(t(lang, "ap_vip"), "adm:vip"), btn(t(lang, "ap_bcast"), "adm:bcast")],
            [btn(t(lang, "ap_mod"), "adm:mod"), btn(t(lang, "ap_rewards"), "adm:rewards")],
            [btn(t(lang, "ap_stats"), "adm:stats"), btn(t(lang, "ap_settings"), "adm:settings")],
            [btn(t(lang, "ap_logs"), "adm:logs")],
            back_row("nav:menu", lang=lang),
        ]
    )


def admin_users_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_search"), "adm:usearch")],
            [btn(t(lang, "ap_all_users"), "adm:ulist:0")],
            [btn(t(lang, "ap_banned"), "adm:ubanned")],
            back_row("adm:home", lang=lang),
        ]
    )


def admin_user_menu(user_id: int, banned: bool, vip: bool, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows = [
        [btn(t(lang, "ap_give_cash"), f"adm:cash:{user_id}"), btn(t(lang, "ap_take_cash"), f"adm:cashminus:{user_id}")],
        [btn(t(lang, "ap_give_gold"), f"adm:gold:{user_id}"), btn(t(lang, "ap_take_gold"), f"adm:goldminus:{user_id}")],
        [btn(t(lang, "ap_give_vip"), f"adm:vipg:{user_id}"), btn(t(lang, "ap_rm_vip"), f"adm:viprm:{user_id}")],
    ]
    if banned:
        rows.append([btn(t(lang, "ap_unban"), f"adm:unban:{user_id}")])
    else:
        rows.append([btn(t(lang, "ap_ban"), f"adm:ban:{user_id}")])
    rows += [
        [btn(t(lang, "ap_ustat"), f"adm:ustat:{user_id}"), btn(t(lang, "ap_utx"), f"adm:utx:{user_id}")],
        [btn(t(lang, "ap_reset"), f"adm:ureset:{user_id}")],
        back_row("adm:users", lang=lang),
    ]
    return kb(rows)


def admin_list_menu(items: list[dict], back_to: str, page: int = 0, pages: int = 1, template: str = "", lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1 and template:
        rows.append(pager_row(page, pages, template))
    rows.append(back_row(back_to, lang=lang))
    return kb(rows)


def admin_race_menu(race_id: int, status: str, paused: bool = False, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows: list[list[dict]] = []
    if status == "open":
        rows.append([btn(t(lang, "ap_pause"), f"admr:pause:{race_id}")])
    elif status == "paused":
        rows.append([btn(t(lang, "ap_resume"), f"admr:open:{race_id}")])
    rows += [
        [btn(t(lang, "ap_extend"), f"admr:ext:{race_id}")],
        [btn(t(lang, "ap_start"), f"admr:start:{race_id}")],
        [btn(t(lang, "rc_participants"), f"admr:part:{race_id}")],
        [btn(t(lang, "ap_results"), f"admr:res:{race_id}")],
        [btn(t(lang, "ap_cancel"), f"admr:cancel:{race_id}")],
        [btn(t(lang, "ap_new"), "admr:new")],
        back_row("nav:admin", lang=lang),
    ]
    return kb(rows)


def admin_crud_menu(kind: str, items: list[dict], add_cb: str, back_to: str, page: int = 0, pages: int = 1, template: str = "", lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows = [[btn(i["text"], i["callback_data"])] for i in items]
    if pages > 1 and template:
        rows.append(pager_row(page, pages, template))
    rows.append([btn(t(lang, "ap_add_new"), add_cb)])
    rows.append(back_row(back_to, lang=lang))
    return kb(rows)


def admin_edit_menu(kind: str, item_id: int, fields: list[tuple[str, str, object]], back_to: str, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows = []
    pairs = list(zip(fields[::2], fields[1::2]))
    for a, b in pairs:
        rows.append([btn(f"{a[1]}: {a[2]}", f"ade:{kind}:{item_id}:{a[0]}"), btn(f"{b[1]}: {b[2]}", f"ade:{kind}:{item_id}:{b[0]}")])
    if len(fields) % 2:
        a = fields[-1]
        rows.append([btn(f"{a[1]}: {a[2]}", f"ade:{kind}:{item_id}:{a[0]}")])
    rows.append([btn(t(lang, "ap_delete"), f"adm:del:{kind}:{item_id}")])
    rows.append(back_row(back_to, lang=lang))
    return kb(rows)


def admin_broadcast_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_all_users"), "adb:all"), btn(t(lang, "ap_vip"), "adb:vip")],
            [btn(t(lang, "ap_vip_all"), "adb:active"), btn(t(lang, "ap_vip_one"), "adb:one")],
            back_row("nav:admin", lang=lang),
        ]
    )


def admin_broadcast_confirm(count: int, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_send"), "adbs:yes"), btn(t(lang, "ap_cancel_btn"), "adbs:no")],
            back_row("adm:bcast", lang=lang),
        ]
    )


def admin_moderation_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_ban_user"), "adm:usearch")],
            [btn(t(lang, "ap_ban_hist"), "adm:bans")],
            back_row("nav:admin", lang=lang),
        ]
    )


def admin_rewards_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_daily_cash"), "admset:daily_cash"), btn(t(lang, "ap_daily_gold"), "admset:daily_gold")],
            [btn(t(lang, "ap_daily_xp"), "admset:daily_xp"), btn(t(lang, "ap_prize1"), "admset:prize_1st")],
            [btn(t(lang, "ap_fl_bonus"), "admset:fastest_lap_bonus"), btn(t(lang, "ap_entry_fee"), "admset:entry_fee")],
            [btn(t(lang, "ap_achv"), "adbr:achv")],
            back_row("adm:home", lang=lang),
        ]
    )


def admin_economy_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_race_rewards"), "admset:prize_1st"), btn(t(lang, "ap_entry_fee"), "admset:entry_fee")],
            [btn(t(lang, "ap_upg_prices"), "admset:upgrade_base_cost"), btn(t(lang, "ap_train_prices"), "admset:driver_upgrade_base_cost")],
            [btn(t(lang, "ap_gold_price"), "admset:gold_price"), btn(t(lang, "ap_sell_ratio"), "admset:sell_ratio_pct")],
            [btn(t(lang, "ap_refresh"), "adbe:refresh")],
            back_row("adm:home", lang=lang),
        ]
    )


def admin_settings_menu(lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn(t(lang, "ap_min_p"), "admset:min_participants"), btn(t(lang, "ap_max_p"), "admset:max_participants")],
            [btn(t(lang, "ap_reg_min"), "admset:registration_minutes")],
            [btn(t(lang, "ap_reset_market"), "adbs:resetmk"), btn(t(lang, "ap_wipe"), "adbs:wipe")],
            [btn(t(lang, "ap_reload"), "adm:reload")],
            back_row("adm:home", lang=lang),
        ]
    )


def admin_ban_menu(user_id: int, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    from .services import moderation

    rows = []
    pairs = list(zip(moderation.DURATIONS[::2], moderation.DURATIONS[1::2]))
    for a, b in pairs:
        rows.append([btn(f"🚫 {a[0]}", f"admb:{user_id}:{a[1]}"), btn(f"🚫 {b[0]}", f"admb:{user_id}:{b[1]}")])
    if len(moderation.DURATIONS) % 2:
        a = moderation.DURATIONS[-1]
        rows.append([btn(f"🚫 {a[0]}", f"admb:{user_id}:{a[1]}")])
    rows.append([btn(t(lang, "ap_no_ban"), f"adm:user:{user_id}")])
    return kb(rows)


def admin_vip_level_menu(user_id: int, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    rows = [[btn(f"VIP {lvl}", f"admvi:l:{user_id}:{lvl}") for lvl in range(1, 4)]]
    rows.append([btn("VIP 4", f"admvi:l:{user_id}:4"), btn("VIP 5", f"admvi:l:{user_id}:5")])
    rows.append(back_row(f"adm:user:{user_id}", lang=lang))
    return kb(rows)


def admin_vip_days_menu(user_id: int, level: int, lang: str = "auto") -> InlineKeyboardMarkup:
    lang = _admin_lang(lang)
    return kb(
        [
            [btn("7d", f"admvi:d:{user_id}:{level}:7"), btn("30d", f"admvi:d:{user_id}:{level}:30")],
            [btn("90d", f"admvi:d:{user_id}:{level}:90"), btn(t(lang, "ap_perm"), f"admvi:d:{user_id}:{level}:0")],
            back_row(f"adm:vipg:{user_id}", lang=lang),
        ]
    )
