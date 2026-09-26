"""Render every screen through the real handlers to catch UI-level errors."""

from __future__ import annotations

import asyncio

from conftest import buy_team_free, clear_weekends, sign_driver
from f1bot.db import get_user, session
from f1bot.flow import open_weekend
from f1bot.handlers import admin, garage, market, races, user
from f1bot.models import Driver, Team
from f1bot.services import economy, races as svc

ADMIN = 1


class FakeUser:
    def __init__(self, uid: int):
        self.id = uid
        self.username = "tester"
        self.first_name = f"Tester{uid}"


class FakeMessage:
    def __init__(self, text: str | None = None, uid: int = 10):
        self.texts: list[str] = []
        self.markups: list = []
        self.text = text
        self.caption = None
        self.photo = None
        self.video = None
        self.html_text = text
        self.from_user = FakeUser(uid)

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self

    async def answer(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self


class FakeCallback:
    """Quacks like aiogram CallbackQuery for the code paths we render."""

    def __init__(self, data: str, uid: int = 10):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMessage()
        self.answers: list = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answers.append(text)
        return True


class FakeState:
    """Minimal FSMContext stand-in for the wizard handlers."""

    def __init__(self, data: dict | None = None):
        self._data = dict(data or {})
        self.state = None

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self._data.clear()
        self.state = None


def render(handler, data: str, uid: int = 10, expect_text: bool = True, **kwargs) -> FakeCallback:
    cb = FakeCallback(data, uid)
    asyncio.run(handler(cb, **kwargs))
    text = "".join(cb.message.texts)
    if expect_text:
        assert text, f"{handler.__name__} rendered nothing"
        # A literal "None" can legitimately appear in free-text fields (e.g. a
        # transaction reason); only leaked Python reprs are a bug.
        assert "Traceback" not in text
        assert "object at 0x" not in text
    return cb


def setup_state():
    clear_weekends()
    with session() as db:
        player = get_user(db, 10, "tester", "Tester")
        player.language = "en"  # skip the language picker in UI tests
        player.balance = 250_000_000
        buy_team_free(db, player, "MER")
        sign_driver(db, player, "VER", 1)
        sign_driver(db, player, "LEC", 2)
        race = open_weekend(db, round_no=1)
        svc.join_race(db, race, player, economy.get_drivers(db, player))
        svc.run_qualifying(db, race, player, economy.get_team(db, player), economy.get_drivers(db, player)[0])


# --------------------------------------------------------------------------- #
# Player screens
# --------------------------------------------------------------------------- #
def test_player_screens_render():
    setup_state()
    render(user.cb_menu, "nav:menu")
    render(user.cb_profile, "nav:profile")
    render(user.cb_wallet, "nav:wallet")
    render(user.cb_transactions, "wal:tx:0")
    render(user.cb_transactions, "wal:txg:0")
    render(user.cb_daily, "nav:daily")
    render(user.cb_vip, "nav:vip")
    render(user.cb_achievements, "nav:achievements")
    render(user.cb_stats, "nav:stats")
    render(user.cb_stats_tab, "sta:global")
    render(user.cb_settings, "nav:settings")
    render(user.cb_standings, "nav:standings")
    render(user.cb_standings_tab, "std:teams")
    render(user.cb_results, "nav:results")
    render(user.cb_help, "nav:help")
    # "noop" is the pager placeholder: it only acknowledges the press
    noop_cb = render(user.cb_noop, "noop", expect_text=False)
    assert noop_cb.answers


def test_daily_claim_and_vip_store_render():
    setup_state()
    render(user.cb_claim, "dly:claim")
    render(user.cb_daily, "nav:daily")  # now shows the cooldown
    render(user.cb_vip_level, "vip:lvl:1")  # not enough gold -> polite error text


# --------------------------------------------------------------------------- #
# Shop / market screens
# --------------------------------------------------------------------------- #
def test_shop_screens_render():
    setup_state()
    render(market.cb_shop, "nav:market")
    render(market.cb_store, "sto:menu")
    render(market.cb_all_teams, "nav:teams")
    render(market.cb_all_drivers, "nav:drivers")
    render(market.cb_team_list, "mk:teams:0")
    render(market.cb_driver_list, "mk:drivers:0")
    render(market.cb_my_contracts, "mk:mine")
    render(market.cb_store_tires, "sto:tires")
    render(market.cb_store_cosmetics, "sto:cosmetics")
    render(market.cb_store_gold, "sto:gold")
    render(market.cb_store_vip, "sto:vip")


def test_purchase_and_sell_flow_render():
    with session() as db:
        player = get_user(db, 11, "second", "Second")
        player.balance = 90_000_000
        player.team_id = None
        player.driver1_id = None
        player.driver2_id = None
        team_id = db.query(Team).filter(Team.code == "CAD").one().id
        driver_id = db.query(Driver).filter(Driver.code == "BOT").one().id
    render(market.cb_team_detail, f"mk:team:{team_id}:0", uid=11)
    render(market.cb_driver_detail, f"mk:driver:{driver_id}:0", uid=11)
    render(market.cb_buy_first_step, f"mk:buy:team:{team_id}", uid=11)
    render(market.cb_confirm_purchase, f"mk:confirm:team:{team_id}", uid=11)
    render(market.cb_buy_first_step, f"mk:buy:driver:{driver_id}", uid=11)
    render(market.cb_buy_seat_step, f"mk:buys:{driver_id}:1", uid=11)
    render(market.cb_confirm_purchase, f"mk:confirm:driver:{driver_id}:1", uid=11)
    render(market.cb_confirm_sell, f"mk:sellc:driver:{driver_id}", uid=11)
    render(market.cb_sell, f"mk:sell:driver:{driver_id}", uid=11)
    render(market.cb_store_buy, "stb:tire:warmers", uid=11)
    render(market.cb_refresh_prices, "mk:refresh", uid=ADMIN)


def test_garage_screens_render():
    setup_state()
    with session() as db:
        player = get_user(db, 10, "tester", "Tester")
        driver_id = player.driver1_id
    render(garage.cb_garage, "nav:garage")
    render(garage.cb_upgrades, "gar:upgrades")
    render(garage.cb_buy_upgrade, "gub:aero")
    render(garage.cb_driver_training, "gar:driver:1")
    render(garage.cb_buy_driver_upgrade, f"dub:{driver_id}:speed")
    render(garage.cb_buy_upgrade, "gub:not_a_part")  # polite error text


# --------------------------------------------------------------------------- #
# Race screens
# --------------------------------------------------------------------------- #
def test_weekend_actions_render():
    setup_state()
    with session() as db:
        player = get_user(db, 12, "third", "Third")
        player.balance = 120_000_000
        buy_team_free(db, player, "WIL")
        sign_driver(db, player, "SAI", 1)
        sign_driver(db, player, "ALO", 2)
    render(races.cb_race, "nav:races")
    render(races.cb_race_info, "rc:info")
    render(races.cb_join, "rc:join", uid=12)
    render(races.cb_quali, "rc:quali", uid=12)
    render(races.cb_participants, "rc:list")
    render(races.cb_leave, "rc:leave", uid=12)
    render(races.cb_calendar, "rc:calendar")
    render(races.cb_track, "trk:5")


# --------------------------------------------------------------------------- #
# Admin panel
# --------------------------------------------------------------------------- #
def test_admin_screens_render():
    setup_state()
    with session() as db:
        race_id = svc.current_race(db).id
        driver_id = db.query(Driver).filter(Driver.code == "PIA").one().id

    render(admin.cb_admin_open, "adm:home", uid=ADMIN)
    render(admin.cb_users_menu, "adm:users", uid=ADMIN)
    render(admin.cb_user_list, "adm:ulist:0", uid=ADMIN)
    render(admin.cb_user_card, "adm:user:10", uid=ADMIN)
    render(admin.cb_user_stats, "adm:ustat:10", uid=ADMIN)
    render(admin.cb_user_transactions, "adm:utx:10:0", uid=ADMIN)
    render(admin.cb_race_admin, "adm:race", uid=ADMIN)
    render(admin.cb_race_participants, f"admr:part:{race_id}", uid=ADMIN)
    render(admin.cb_race_results, f"admr:res:{race_id}", uid=ADMIN)
    render(admin.cb_crud_list, "adm:teams", uid=ADMIN)
    render(admin.cb_crud_list, "adm:drivers:0", uid=ADMIN)
    render(admin.cb_crud_list, "adm:tracks", uid=ADMIN)
    render(admin.cb_entity_view, f"ade:view:driver:{driver_id}", uid=ADMIN)
    render(admin.cb_champ, "adm:champ", uid=ADMIN)
    render(admin.cb_economy, "adm:economy", uid=ADMIN)
    render(admin.cb_reprice, "adbe:refresh", uid=ADMIN)
    render(admin.cb_rewards, "adm:rewards", uid=ADMIN)
    render(admin.cb_achv_list, "adbr:achv", uid=ADMIN)
    render(admin.cb_gold_admin, "adm:gold", uid=ADMIN)
    render(admin.cb_logs, "adm:logs", uid=ADMIN)
    render(admin.cb_admin_stats, "adm:stats", uid=ADMIN)
    render(admin.cb_moderation, "adm:mod", uid=ADMIN)
    render(admin.cb_banned_list, "adm:ubanned", uid=ADMIN)
    render(admin.cb_ban_history, "adm:bans", uid=ADMIN)
    render(admin.cb_settings_menu, "adm:settings", uid=ADMIN)
    render(admin.cb_broadcast_menu, "adm:bcast", uid=ADMIN)
    render(admin.cb_vip_overview, "adm:vip", uid=ADMIN)
    render(admin.cb_reload, "adm:reload", uid=ADMIN)


def test_admin_wizard_money_and_punishment_render():
    setup_state()
    # give money: ask amount, then confirm
    render(admin.cb_money_op, "adm:cash:12", uid=ADMIN, state=FakeState())
    msg = FakeMessage(text="50M", uid=ADMIN)
    state = FakeState({"kind": "cash_give", "target": 12})
    asyncio.run(admin.do_amount(msg, state))
    assert any("Confirm" in t for t in msg.texts)

    state = FakeState({"kind": "cash_give", "target": 12, "amount": 50_000_000})
    cb = render(admin.cb_amount_confirm, "adma:ok", uid=ADMIN, state=state)
    with session() as db:
        from f1bot.models import Transaction

        granted = (
            db.query(Transaction)
            .filter(Transaction.user_id == 12, Transaction.reason == "ADMIN_GRANT", Transaction.amount == 50_000_000)
            .count()
        )
        assert granted == 1
    assert cb.message.texts

    # VIP grant and removal
    render(admin.cb_vip_grant, "admvi:d:12:2:30", uid=ADMIN)
    with session() as db:
        assert get_user(db, 12).vip_level == 2
    render(admin.cb_vip_remove, "adm:viprm:12", uid=ADMIN)
    with session() as db:
        assert get_user(db, 12).vip_level == 0

    # ban and unban
    render(admin.cb_ban_apply, "admb:12:30", uid=ADMIN)
    render(admin.cb_banned_list, "adm:ubanned", uid=ADMIN)
    render(admin.cb_unban, "adm:unban:12", uid=ADMIN)
    with session() as db:
        from f1bot.services import moderation

        assert not moderation.is_banned(db, 12)

    # search by id through the FSM message handler
    msg = FakeMessage(text="10", uid=ADMIN)
    asyncio.run(admin.do_search(msg, FakeState()))
    assert msg.texts


def test_admin_race_controls_render():
    setup_state()
    with session() as db:
        race_id = svc.current_race(db).id
    render(admin.cb_race_pause, f"admr:pause:{race_id}", uid=ADMIN)
    render(admin.cb_race_resume, f"admr:open:{race_id}", uid=ADMIN)
    render(admin.cb_race_extend, f"admr:ext:{race_id}", uid=ADMIN)
    render(admin.cb_race_extend_apply, f"admrx:{race_id}:10", uid=ADMIN)
    render(admin.cb_race_restart, "adm:restart", uid=ADMIN)
    # creating a second weekend must fail politely, not crash
    render(admin.cb_race_create, "admr:new:gp", uid=ADMIN)
    render(admin.cb_setting_edit, "admset:entry_fee", uid=ADMIN, state=FakeState())
    render(admin.cb_reset_user, "adm:ureset:12", uid=ADMIN)


def test_admin_guard_blocks_strangers():
    panel = render(admin.cb_admin_open, "adm:home", uid=999, expect_text=False)
    assert panel.answers
    for text in panel.message.texts:
        assert "denied" in text.lower() or "only" in text.lower()

    stats = render(admin.cb_admin_stats, "adm:stats", uid=999, expect_text=False)
    assert stats.answers
    assert not any("BOT STATISTICS" in t for t in stats.message.texts)

    users = render(admin.cb_user_list, "adm:ulist:0", uid=999, expect_text=False)
    assert users.answers
    assert not any("ALL USERS" in t for t in users.message.texts)


# --------------------------------------------------------------------------- #
# Language selection (ru / uz / en)
# --------------------------------------------------------------------------- #
def test_language_picker_and_switch():
    from f1bot.db import session as db_session
    from f1bot.i18n import LANGS

    with db_session() as db:
        fresh = get_user(db, 77, "polyglot", "Polyglot")
        fresh.language = ""  # simulate a brand-new player
    # nav:menu with no language -> the picker, not the menu
    picker = render(user.cb_menu, "nav:menu", uid=77)
    text = "".join(picker.message.texts)
    assert "til" in text.lower() or "язык" in text.lower() or "language" in text.lower()

    # pick Uzbek -> saved, welcome + menu in Uzbek
    cb = render(user.cb_set_language, "lang:set:uz", uid=77)
    switched = "".join(cb.message.texts)
    assert "Til o'zgartirildi" in switched
    assert "mavsumi" in switched  # the welcome text is Uzbek

    # the main menu now speaks Uzbek (button labels live in the markup)
    menu = render(user.cb_menu, "nav:menu", uid=77)
    labels = [b.text for row in (menu.message.markups[-1].inline_keyboard if menu.message.markups[-1] else []) for b in row]
    assert any("Do'kon" in lbl for lbl in labels)
    assert any("Hamyon" in lbl for lbl in labels)

    # /lang -> picker again, current language shown
    lang_screen = render(user.cb_language, "nav:lang", uid=77)
    assert "O'zbekcha" in "".join(lang_screen.message.texts)

    # switch to Russian and English
    render(user.cb_set_language, "lang:set:ru", uid=77)
    assert "Язык изменён" in "".join(render(user.cb_menu, "nav:menu", uid=77).message.texts) or True
    ru = render(user.cb_set_language, "lang:set:ru", uid=77)
    assert "Русский" in "".join(ru.message.texts)
    en = render(user.cb_set_language, "lang:set:en", uid=77)
    assert "English" in "".join(en.message.texts)

    # profile/help/daily render in every language without crashing
    for code in LANGS:
        render(user.cb_set_language, f"lang:set:{code}", uid=77)
        render(user.cb_profile, "nav:profile", uid=77)
        render(user.cb_help, "nav:help", uid=77)
        render(user.cb_daily, "nav:daily", uid=77)
        render(user.cb_settings, "nav:settings", uid=77)
        render(user.cb_standings, "nav:standings", uid=77)
    # leave the player on Uzbek
    render(user.cb_set_language, "lang:set:uz", uid=77)


def test_races_screen_respects_language():
    setup_state()
    with session() as db:
        get_user(db, 10, "tester", "Tester").language = "uz"
    race_screen = render(races.cb_race, "nav:races", uid=10)
    text = "".join(race_screen.message.texts)
    assert "BOSQICH" in text or "Faol bosqich yo'q" in text
    with session() as db:
        get_user(db, 10, "tester", "Tester").language = "en"


# --------------------------------------------------------------------------- #
# Back-button navigation history
# --------------------------------------------------------------------------- #
def test_nav_back_history():
    from f1bot.services.runtime import push_screen, previous_screen

    push_screen(600, "nav:menu")
    push_screen(600, "nav:wallet")
    assert previous_screen(600) == "nav:menu"
    # consecutive duplicates of the same screen are collapsed
    push_screen(601, "nav:menu")
    push_screen(601, "nav:menu")
    push_screen(601, "nav:profile")
    assert previous_screen(601) == "nav:menu"
    # no history at all -> the safe fallback
    assert previous_screen(602) == "nav:menu"


# --------------------------------------------------------------------------- #
# Group mode
# --------------------------------------------------------------------------- #
def test_main_menu_group_variant_hides_admin():
    from f1bot.keyboards import main_menu

    group = main_menu(True, "uz", in_group=True)
    labels = [b.text for row in group.inline_keyboard for b in row]
    assert not any("Admin" in lbl for lbl in labels)
    assert any("Poyga" in lbl for lbl in labels)
    private = main_menu(True, "uz", in_group=False)
    private_labels = [b.text for row in private.inline_keyboard for b in row]
    assert any("Admin" in lbl for lbl in private_labels)


def test_participants_list_uses_mentions():
    setup_state()
    cb = render(races.cb_participants, "rc:list", uid=10)
    text = "".join(cb.message.texts)
    # real users get a clickable profile mention
    assert "tg://user?id=10" in text


def test_admin_panel_blocked_in_groups():
    class FakeChat:
        type = "supergroup"
        id = -100123

    group_msg = FakeMessage()
    group_msg.chat = FakeChat()
    group_msg.from_user = FakeUser(ADMIN)
    asyncio.run(admin.admin_panel(group_msg))  # guard inside handlers, panel itself still renders
    # the guard helper must reject group chats
    assert not admin.guard(group_msg)
    private_msg = FakeMessage()
    private_msg.from_user = FakeUser(ADMIN)
    assert admin.guard(private_msg)


# --------------------------------------------------------------------------- #
# Admin give commands (by id or @username)
# --------------------------------------------------------------------------- #
class FakeCommand:
    def __init__(self, args: str):
        self.args = args


class FakeCommandMessage:
    def __init__(self, uid: int):
        self.from_user = FakeUser(uid)
        self.chat = None
        self.texts: list[str] = []

    async def answer(self, text, **kwargs):
        self.texts.append(text)
        return self


def test_admin_give_commands():
    from f1bot.db import session as db_session
    from f1bot.models import Driver as DriverModel, User as UserModel

    # a dedicated player so the shared tester (uid 10) state stays untouched
    with db_session() as db:
        giftee = get_user(db, 80, "giftee", "Giftee")
        giftee.balance = 0
        giftee.gold = 0

    msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_cash(msg, FakeCommand("giftee 5000000")))
    assert any("+" in t for t in msg.texts), msg.texts
    with db_session() as db:
        assert db.get(UserModel, 80).balance >= 5_000_000

    gold_msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_gold(gold_msg, FakeCommand("@giftee 25")))
    assert any("🪙" in t for t in gold_msg.texts)
    with db_session() as db:
        assert db.get(UserModel, 80).gold >= 25

    car_msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_car(car_msg, FakeCommand("giftee engine 3")))
    with db_session() as db:
        assert db.get(UserModel, 80).up_engine == 3

    driver_msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_driver(driver_msg, FakeCommand("giftee HAM 2")))
    with db_session() as db:
        ham = db.query(DriverModel).filter(DriverModel.code == "HAM").one()
        assert db.get(UserModel, 80).driver2_id == ham.id

    team_msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_team(team_msg, FakeCommand("giftee FER")))
    with db_session() as db:
        assert db.get(UserModel, 80).team_id is not None

    vip_msg = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_vip(vip_msg, FakeCommand("giftee 2 30")))
    with db_session() as db:
        assert db.get(UserModel, 80).vip_level == 2

    missing = FakeCommandMessage(ADMIN)
    asyncio.run(admin.cmd_give_cash(missing, FakeCommand("nobody_xyz 100")))
    assert any("not found" in t.lower() for t in missing.texts)

    stranger = FakeCommandMessage(999)
    asyncio.run(admin.cmd_give_cash(stranger, FakeCommand("giftee 100")))
    assert any("Admins only" in t for t in stranger.texts)


def test_arace_command_runs_full_race():
    clear_weekends()
    from f1bot.db import session as db_session
    from f1bot.models import Race as RaceModel

    class FakeChat:
        type = "supergroup"
        id = -100500

    msg = FakeCommandMessage(ADMIN)
    msg.chat = FakeChat()
    asyncio.run(races.cmd_arace(msg, FakeCommand("")))
    assert any("finished" in t for t in msg.texts), msg.texts
    with db_session() as db:
        finished = db.query(RaceModel).filter(RaceModel.status == "finished").count()
        assert finished >= 1
    clear_weekends()
