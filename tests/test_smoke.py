"""End-to-end smoke tests for the game logic (no network, SQLite temp file)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import buy_team_free, clear_weekends, sign_driver

from f1bot.config import settings
from f1bot.db import get_user, session
from f1bot.flow import open_weekend, start_race, weekend_summary
from f1bot.models import Achievement, Championship, Driver, Race, Result, Team, Transaction, User
from f1bot.services import achievements, bonus, economy, moderation, stats, store, vip, wallet
from f1bot.services import races as svc


def _make_team(db, user_id: int, team_code: str, driver_codes: tuple[str, ...]) -> User:
    """Create a player with a team and the requested drivers, fully funded."""
    user = get_user(db, user_id, f"player{user_id}", f"Player {user_id}")
    user.balance = settings.starting_cash
    buy_team_free(db, user, team_code)
    for slot, code in enumerate(driver_codes, start=1):
        sign_driver(db, user, code, slot)
    return user


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
def test_seed_reference_data():
    with session() as db:
        assert db.query(Team).count() == 11
        assert db.query(Driver).count() == 22
        tracks = svc.all_tracks(db)
        assert len(tracks) == 24
        assert db.query(Achievement).count() == 14

        ver = db.query(Driver).filter(Driver.code == "VER").one()
        assert ver.team_name == "Red Bull Racing" and ver.number == 3
        nor = db.query(Driver).filter(Driver.code == "NOR").one()
        assert nor.number == 1  # reigning champion carries #1 in 2026
        monaco = svc.round_info(db, 8)
        assert monaco["gp"] == "Monaco GP" and monaco["laps"] == 78


def test_calendar_rounds_are_unique():
    with session() as db:
        rounds = [info["r"] for info in svc.all_tracks(db)]
        assert sorted(rounds) == list(range(1, 25))


# --------------------------------------------------------------------------- #
# Wallet / economy services
# --------------------------------------------------------------------------- #
def test_wallet_ledger_and_negative_guard():
    with session() as db:
        user = get_user(db, 9001, "walletuser", "Wallet")
        user.balance = 0
        user.gold = 0
        balance = wallet.add_cash(db, user, 10_000_000, "TEST", "seed")
        assert balance == 10_000_000
        assert user.total_earnings == 10_000_000

        with pytest.raises(wallet.NotEnoughFunds):
            wallet.spend_cash(db, user, 11_000_000, "TEST", "too much")
        assert user.balance == 10_000_000

        wallet.spend_cash(db, user, 4_000_000, "TEST", "part")
        assert user.balance == 6_000_000
        assert user.total_spending == 4_000_000

        gold = wallet.add_gold(db, user, 50, "TEST", "gold seed")
        assert gold == 50
        with pytest.raises(wallet.NotEnoughFunds):
            wallet.spend_gold(db, user, 51, "TEST", "overdraft")
        wallet.spend_gold(db, user, 20, "TEST", "spend gold")
        assert user.gold == 30

        rows = wallet.history(db, user.id)
        assert len(rows) == 4
        assert {r.currency for r in rows} == {"cash", "gold"}
        assert wallet.history_count(db, user.id) == 4
        totals = wallet.totals(db)
        assert totals["total_cash"] >= 6_000_000
        assert totals["total_gold"] >= 30


def test_vip_lifecycle_and_perks():
    with session() as db:
        user = get_user(db, 9002, "vipuser", "Vip")
        assert vip.active_level(user) == 0
        before = vip.prize_multiplier(user)

        vip.grant(db, user, 3, 30, admin_id=1)
        assert vip.active_level(user) == 3
        assert "VIP" in vip.label(user)
        assert vip.prize_multiplier(user) > before
        assert vip.vip_user_count(db) >= 1

        vip.remove(user)
        assert vip.active_level(user) == 0
        assert vip.prize_multiplier(user) == before


def test_moderation_timed_ban():
    with session() as db:
        user = get_user(db, 9003, "banned", "Banned")
        assert not moderation.is_banned(db, user.id)

        row = moderation.ban(db, user, admin_id=1, minutes=30, reason="test ban")
        assert moderation.is_banned(db, user.id)
        assert moderation.describe(row).startswith("banned")
        assert "test ban" in moderation.describe(row)

        moderation.unban(db, user, admin_id=1, reason="test unban")
        assert not moderation.is_banned(db, user.id)


def test_daily_bonus_once_per_cooldown():
    with session() as db:
        user = get_user(db, 9004, "bonus", "Bonus")
        claim = bonus.claim(db, user)
        assert claim.cash > 0
        assert claim.streak == 1
        assert user.balance > 0
        with pytest.raises(ValueError):
            bonus.claim(db, user)  # still on cooldown


def test_runtime_settings_override():
    with session() as db:
        default_fee = store.entry_fee(db)
        store.set_raw(db, "entry_fee", str(default_fee + 500_000))
        assert store.entry_fee(db) == default_fee + 500_000
        store.set_raw(db, "entry_fee", str(default_fee))
        assert store.entry_fee(db) == default_fee


# --------------------------------------------------------------------------- #
# Market & garage
# --------------------------------------------------------------------------- #
def test_player_lifecycle_and_market():
    with session() as db:
        user = get_user(db, 1001, "alice", "Alice")
        user.balance = settings.starting_cash

        bought = economy.buy_team(db, user, db.query(Team).filter(Team.code == "CAD").one().id)
        assert user.team_id == bought.id
        assert user.balance == settings.starting_cash - bought.price

        with pytest.raises(ValueError):
            economy.buy_team(db, user, bought.id)  # already owned

        driver = db.query(Driver).order_by(Driver.overall.desc()).first()
        economy.buy_driver(db, user, driver.id, 1)
        assert user.driver1_id == driver.id
        with pytest.raises(ValueError):
            economy.buy_driver(db, user, driver.id, 2)  # already signed

        payout = economy.sell_driver(db, user, driver.id)
        assert payout == int(driver.price * store.sell_ratio(db))
        assert user.driver1_id is None

        team_payout = economy.sell_team(db, user, bought.id)
        assert team_payout == int(bought.price * store.sell_ratio(db))
        assert user.team_id is None


def test_upgrade_costs_and_balance_guard():
    with session() as db:
        user = get_user(db, 1002, "bob", "Bob")
        user.balance = settings.starting_cash
        level, cost = economy.buy_upgrade(db, user, "chassis")
        assert level == 1 and user.up_chassis == 1
        assert user.balance == settings.starting_cash - cost

        user.balance = 0
        with pytest.raises(ValueError):
            economy.buy_upgrade(db, user, "engine")
        with pytest.raises(ValueError):
            economy.buy_upgrade(db, user, "not_a_part")

        user.balance = settings.starting_cash
        driver = db.query(Driver).filter(Driver.code == "PER").one()
        sign_driver(db, user, "PER", 1)
        level, cost = economy.buy_driver_upgrade(db, user, driver.id, "speed")
        assert level >= 1
        assert economy.driver_levels(db, user.id, driver.id)["speed"] >= 1


# --------------------------------------------------------------------------- #
# Race engine
# --------------------------------------------------------------------------- #
def test_join_requires_team_and_driver():
    clear_weekends()
    with session() as db:
        race = open_weekend(db, round_no=1)
        bare = get_user(db, 9101, "bare", "Bare")
        bare.balance = settings.starting_cash
        with pytest.raises(ValueError):
            svc.join_race(db, race, bare)  # no team, no driver


def test_full_race_weekend():
    clear_weekends()
    with session() as db:
        race = open_weekend(db, round_no=8)  # Monaco
        assert race.status == "open"
        assert race.total_laps == 78

        players = []
        for uid, team, drivers in [
            (2001, "MER", ("RUS", "ANT")),
            (2002, "FER", ("LEC", "HAM")),
            (2003, "MCL", ("NOR", "PIA")),
            (2004, "RBR", ("VER", "HAD")),
        ]:
            user = _make_team(db, uid, team, drivers)
            entry_fee = svc.join_race(db, race, user, economy.get_drivers(db, user))
            assert entry_fee > store.entry_fee(db)  # entry fee + driver salaries
            players.append(user)
        assert race.participants == 4

        with pytest.raises(ValueError):
            svc.join_race(db, race, players[0], [])  # duplicate entry

        for user in players:
            team = economy.get_team(db, user)
            lead = economy.get_drivers(db, user)[0]
            assert svc.run_qualifying(db, race, user, team, lead) > 0

        grid = svc.build_grid(db, race)
        assert [g.grid_pos for g in grid] == [1, 2, 3, 4]
        assert race.quali_done and len(race.grid) == 4

        sim_entries = []
        for entry in grid:
            user = db.get(User, entry.user_id)
            team = economy.get_team(db, user)
            lead = economy.get_drivers(db, user)[0]
            levels = economy.driver_levels(db, user.id, lead.id)
            sim_entries.append(
                svc.SimEntrant(
                    user_id=user.id,
                    name=user.first_name,
                    car=svc.car_strength(user, team),
                    package=svc.car_package(user, team),
                    drivers=[svc.driver_package(lead, levels)],
                    quali_avg=entry.quali_avg,
                    grid_pos=entry.grid_pos,
                )
            )
        race_id = race.id

    sim = svc.simulate_race(sim_entries, race, weather="light_rain")
    finishers = [r for r in sim.rows if r.retire_lap is None]
    assert finishers, "nobody finished — simulation is broken"
    assert sorted(r.position for r in sim.rows) == list(range(1, len(sim.rows) + 1))
    assert all(a.total_time <= b.total_time for a, b in zip(finishers, finishers[1:]))

    class FakeBot:
        def __init__(self):
            self.edits = 0
            self.sends = 0

        async def send_message(self, chat_id, text, **kwargs):
            self.sends += 1

            class M:
                message_id = 42

            return M()

        async def edit_message_text(self, **kwargs):
            self.edits += 1

    bot = FakeBot()
    asyncio.run(svc.broadcast_race(bot, 1, race, sim, {2001: "A", 2002: "B", 2003: "C", 2004: "D"}))
    assert bot.sends == 1 and bot.edits > 5

    with session() as db:
        fresh = db.get(Race, race_id)
        before_gold = {uid: db.get(User, uid).gold for uid in (2001, 2002, 2003, 2004)}
        svc.apply_results(db, fresh, sim)
        assert fresh.status == "finished"

        entries = svc.race_classification(db, race_id)
        assert len(entries) == 4
        assert entries[0].points == 25
        assert entries[0].money_won >= svc.prize_for(1, "gp")
        assert entries[0].gold_won > 0  # gold rewards really paid

        assert db.query(Result).count() >= 4
        assert svc.season_standings(db)[0][1] >= 25
        assert svc.constructored_standings(db)[0][1] > 0

        # the prize money and gold must live in the wallet ledger
        tx = (
            db.query(Transaction)
            .filter(Transaction.user_id == entries[0].user_id, Transaction.reason == "PRIZE")
            .count()
        )
        assert tx >= 1
        assert db.get(User, entries[0].user_id).gold > before_gold[entries[0].user_id]

        # championship tables were rebuilt from the stored results
        champ = db.query(Championship).filter(Championship.kind == "drivers").count()
        assert champ == 1

        # events were persisted (pit stops, weather, overtakes...)
        from f1bot.models import RaceEvent

        assert db.query(RaceEvent).filter(RaceEvent.race_id == race_id).count() >= 1


def test_min_participants_rule_cancels_weekend():
    clear_weekends()
    with session() as db:
        race = open_weekend(db, round_no=2)
        race_id = race.id
        for uid, team, drivers in [
            (2101, "WIL", ("SAI", "ALB")),
            (2102, "AMR", ("ALO", "STR")),
        ]:
            user = _make_team(db, uid, team, drivers)
            svc.join_race(db, race, user, economy.get_drivers(db, user))
        assert race.participants < store.min_participants(db)

    result = asyncio.run(start_race(race_id))
    assert result.startswith("cancelled")

    with session() as db:
        fresh = db.get(Race, race_id)
        assert fresh.status == "cancelled"
        # everyone got their entry money back
        for uid in (2101, 2102):
            user = db.get(User, uid)
            refund = (
                db.query(Transaction)
                .filter(Transaction.user_id == uid, Transaction.reason == "ENTRY_REFUND")
                .count()
            )
            assert refund == 1


def test_extend_registration():
    clear_weekends()
    with session() as db:
        race = open_weekend(db, round_no=3)
        before = race.registration_ends_at
        deadline = svc.extend_registration(db, race, 30)
        assert deadline > before
        with pytest.raises(ValueError):
            svc.extend_registration(db, race, 0)  # must be positive
        race.status = "finished"
        with pytest.raises(ValueError):
            svc.extend_registration(db, race, 10)  # only while the weekend is live
    clear_weekends()


def test_cannot_open_two_weekends():
    clear_weekends()
    with session() as db:
        open_weekend(db, round_no=9)
        with pytest.raises(ValueError):
            open_weekend(db, round_no=10)
    clear_weekends()


def test_weekend_summary_renders():
    clear_weekends()
    with session() as db:
        open_weekend(db, round_no=1)
        text = weekend_summary(svc.current_race(db))
        assert "Australian GP" in text and "Entry fee" in text
        assert "min 4" in text
    clear_weekends()


def test_prize_gold_and_points_tables():
    assert svc.prize_for(1) == settings.prize_payouts[0]
    assert svc.prize_for(len(settings.prize_payouts) + 1) == 0
    assert svc.prize_for(1, "sprint") == settings.sprint_payouts[0]
    assert svc.gold_for(1) > 0
    assert len(svc.POINTS) == 10
    assert svc.POINTS[0] == 25


def test_weather_and_tyres_are_real_choices():
    dry = svc.pick_weather({"rain": 0.0}, force=None)
    assert dry in ("dry", "cloudy", "light_rain", "heavy_rain")
    assert svc.best_compound("heavy_rain") in ("intermediate", "wet")
    assert svc.best_compound("dry") in ("soft", "medium", "hard")
    assert svc.weather_label("dry")
    assert svc.tyre_label("soft")


def test_achievements_check_all_runs():
    with session() as db:
        unlocked = achievements.check_all(db)
        assert isinstance(unlocked, list)
        rows = db.query(Achievement).all()
        assert len(rows) == 14
        assert all(r.code and r.name for r in rows)


def test_global_stats_keys():
    with session() as db:
        g = stats.global_stats(db)
        for key in ("users", "races", "finished", "entries", "transactions", "total_cash", "total_gold", "vip"):
            assert key in g
