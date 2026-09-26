"""Reference data for the 2026 FIA Formula One World Championship.

Sources: en.wikipedia.org/wiki/2026_Formula_One_World_Championship (teams,
drivers, power units) and formula1.com/calendar (24 confirmed rounds).

The seed is idempotent: existing rows are kept, missing rows are inserted, so
every value can afterwards be retuned from the admin panel.
"""

from __future__ import annotations

from math import exp

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Driver, Team, Track
from .services import achievements as achievements_svc

# code, name, country, engine, logo, rating, price, aero, straight-line,
# cornering, reliability, tyre management, pit crew, development potential
TEAMS: list[tuple[str, str, str, str, str, int, int, int, int, int, int, int, int, int]] = [
    ("MER", "Mercedes", "🇩🇪 Germany", "Mercedes-AMG M17", "🩷", 95, 100_000_000, 94, 96, 93, 95, 94, 96, 80),
    ("FER", "Ferrari", "🇮🇹 Italy", "Ferrari 068/12", "🟥", 94, 98_000_000, 95, 93, 94, 92, 93, 94, 82),
    ("MCL", "McLaren", "🇬🇧 UK", "Mercedes-AMG M17", "🟠", 93, 95_000_000, 96, 92, 95, 93, 94, 92, 88),
    ("RBR", "Red Bull Racing", "🇦🇹 Austria", "Red Bull Ford RA626L", "🟦", 90, 90_000_000, 91, 92, 92, 88, 90, 93, 78),
    ("WIL", "Williams", "🇬🇧 UK", "Mercedes-AMG M17", "🔵", 83, 65_000_000, 84, 82, 84, 85, 83, 84, 86),
    ("RAC", "Racing Bulls", "🇮🇹 Italy", "Red Bull Ford RA626L", "🔵", 81, 58_000_000, 82, 80, 82, 83, 82, 85, 89),
    ("AMR", "Aston Martin", "🇬🇧 UK", "Honda RA626H", "🟩", 79, 52_000_000, 80, 78, 80, 80, 79, 80, 84),
    ("AUD", "Audi F1 Team", "🇩🇪 Germany", "Audi 26 E2", "⬜", 77, 45_000_000, 76, 79, 76, 78, 77, 78, 92),
    ("HAA", "Haas F1 Team", "🇺🇸 USA", "Ferrari 068/12", "⬜", 76, 38_000_000, 75, 78, 75, 79, 76, 77, 70),
    ("ALP", "Alpine", "🇫🇷 France", "Mercedes-AMG M17", "🔵", 74, 32_000_000, 74, 74, 75, 75, 74, 76, 83),
    ("CAD", "Cadillac F1 Team", "🇺🇸 USA", "Ferrari 068/12", "⬛", 71, 25_000_000, 69, 74, 69, 74, 71, 73, 86),
]

# number, name, code, flag, real 2026 team, overall, speed, qualifying, race pace,
# overtaking, defending, wet, tyre management, consistency, experience, potential
DRIVERS: list[tuple[int, str, str, str, str, int, int, int, int, int, int, int, int, int, int, int]] = [
    (1, "Lando Norris", "NOR", "🇬🇧", "McLaren", 97, 97, 96, 98, 96, 95, 94, 96, 90, 78, 92),
    (81, "Oscar Piastri", "PIA", "🇦🇺", "McLaren", 95, 95, 94, 96, 93, 94, 92, 95, 90, 74, 95),
    (63, "George Russell", "RUS", "🇬🇧", "Mercedes", 95, 94, 97, 95, 93, 94, 93, 94, 91, 82, 88),
    (12, "Kimi Antonelli", "ANT", "🇮🇹", "Mercedes", 89, 89, 88, 89, 87, 86, 85, 88, 85, 55, 97),
    (44, "Lewis Hamilton", "HAM", "🇬🇧", "Ferrari", 94, 93, 93, 95, 94, 95, 96, 94, 90, 99, 70),
    (16, "Charles Leclerc", "LEC", "🇲🇨", "Ferrari", 95, 95, 98, 94, 94, 92, 95, 92, 87, 90, 80),
    (3, "Max Verstappen", "VER", "🇳🇱", "Red Bull Racing", 98, 98, 96, 99, 99, 97, 98, 95, 92, 92, 85),
    (6, "Isack Hadjar", "HAD", "🇫🇷", "Red Bull Racing", 86, 86, 85, 86, 87, 84, 84, 84, 84, 52, 94),
    (55, "Carlos Sainz", "SAI", "🇪🇸", "Williams", 92, 91, 92, 93, 91, 92, 93, 94, 91, 92, 72),
    (23, "Alexander Albon", "ALB", "🇹🇭", "Williams", 87, 87, 85, 88, 88, 87, 86, 87, 89, 84, 74),
    (30, "Liam Lawson", "LAW", "🇳🇿", "Racing Bulls", 84, 84, 83, 84, 86, 83, 83, 83, 84, 68, 86),
    (41, "Arvid Lindblad", "LIN", "🇬🇧", "Racing Bulls", 81, 82, 81, 80, 82, 79, 80, 80, 83, 35, 96),
    (14, "Fernando Alonso", "ALO", "🇪🇸", "Aston Martin", 91, 90, 91, 92, 93, 95, 95, 95, 93, 99, 55),
    (18, "Lance Stroll", "STR", "🇨🇦", "Aston Martin", 79, 79, 77, 79, 79, 78, 78, 80, 85, 80, 55),
    (5, "Gabriel Bortoleto", "BOR", "🇧🇷", "Audi F1 Team", 83, 83, 82, 83, 84, 82, 82, 83, 84, 45, 93),
    (27, "Nico Hulkenberg", "HUL", "🇩🇪", "Audi F1 Team", 85, 84, 85, 86, 85, 86, 86, 88, 90, 96, 58),
    (31, "Esteban Ocon", "OCO", "🇫🇷", "Haas F1 Team", 86, 85, 86, 87, 86, 87, 88, 88, 86, 88, 66),
    (87, "Oliver Bearman", "BEA", "🇬🇧", "Haas F1 Team", 83, 83, 83, 83, 83, 82, 81, 84, 84, 50, 92),
    (10, "Pierre Gasly", "GAS", "🇫🇷", "Alpine", 88, 87, 88, 88, 89, 88, 90, 89, 87, 91, 64),
    (43, "Franco Colapinto", "COL", "🇦🇷", "Alpine", 81, 82, 80, 81, 84, 79, 81, 80, 83, 48, 91),
    (11, "Sergio Perez", "PER", "🇲🇽", "Cadillac F1 Team", 88, 87, 85, 89, 90, 90, 92, 90, 86, 97, 60),
    (77, "Valtteri Bottas", "BOT", "🇫🇮", "Cadillac F1 Team", 84, 83, 85, 84, 83, 85, 84, 88, 89, 98, 52),
]

# round, flag, grand prix, circuit, country, length km, laps, lap record,
# overtaking, downforce, tyre degradation, safety car, rain, stress, sprint
TRACKS: list[dict] = [
    dict(r=1, flag="🇦🇺", gp="Australian GP", circuit="Albert Park Circuit", country="Australia",
         length=5.303, laps=58, rec=81.0, over=0.55, down=0.55, deg=0.55, sc=0.45, rain=0.20, stress=0.45),
    dict(r=2, flag="🇨🇳", gp="Chinese GP", circuit="Shanghai International Circuit", country="China",
         length=5.451, laps=56, rec=92.0, over=0.50, down=0.60, deg=0.50, sc=0.40, rain=0.25, stress=0.50,
         sprint=True),
    dict(r=3, flag="🇯🇵", gp="Japanese GP", circuit="Suzuka Circuit", country="Japan",
         length=5.807, laps=53, rec=90.0, over=0.35, down=0.80, deg=0.60, sc=0.35, rain=0.30, stress=0.70),
    dict(r=4, flag="🇧🇭", gp="Bahrain GP", circuit="Bahrain International Circuit", country="Bahrain",
         length=5.412, laps=57, rec=90.5, over=0.60, down=0.45, deg=0.70, sc=0.40, rain=0.02, stress=0.50),
    dict(r=5, flag="🇸🇦", gp="Saudi Arabian GP", circuit="Jeddah Corniche Circuit", country="Saudi Arabia",
         length=6.174, laps=50, rec=90.0, over=0.40, down=0.45, deg=0.35, sc=0.70, rain=0.02, stress=0.80),
    dict(r=6, flag="🇺🇸", gp="Miami GP", circuit="Miami International Autodrome", country="USA",
         length=5.412, laps=57, rec=89.5, over=0.45, down=0.55, deg=0.45, sc=0.40, rain=0.35, stress=0.40,
         sprint=True),
    dict(r=7, flag="🇨🇦", gp="Canadian GP", circuit="Circuit Gilles-Villeneuve", country="Canada",
         length=4.361, laps=70, rec=73.5, over=0.65, down=0.30, deg=0.40, sc=0.75, rain=0.30, stress=0.70,
         sprint=True),
    dict(r=8, flag="🇲🇨", gp="Monaco GP", circuit="Circuit de Monaco", country="Monaco",
         length=3.337, laps=78, rec=72.0, over=0.15, down=0.90, deg=0.25, sc=0.85, rain=0.30, stress=0.50),
    dict(r=9, flag="🇪🇸", gp="Spanish GP", circuit="Circuit de Barcelona-Catalunya", country="Spain",
         length=4.657, laps=66, rec=80.0, over=0.40, down=0.65, deg=0.50, sc=0.35, rain=0.15, stress=0.40),
    dict(r=10, flag="🇦🇹", gp="Austrian GP", circuit="Red Bull Ring", country="Austria",
         length=4.318, laps=71, rec=65.0, over=0.60, down=0.35, deg=0.55, sc=0.45, rain=0.35, stress=0.50),
    dict(r=11, flag="🇬🇧", gp="British GP", circuit="Silverstone Circuit", country="United Kingdom",
         length=5.891, laps=52, rec=85.0, over=0.45, down=0.60, deg=0.60, sc=0.40, rain=0.45, stress=0.50,
         sprint=True),
    dict(r=12, flag="🇧🇪", gp="Belgian GP", circuit="Circuit de Spa-Francorchamps", country="Belgium",
         length=6.998, laps=44, rec=106.0, over=0.50, down=0.55, deg=0.55, sc=0.55, rain=0.50, stress=0.55),
    dict(r=13, flag="🇭🇺", gp="Hungarian GP", circuit="Hungaroring", country="Hungary",
         length=4.381, laps=70, rec=78.0, over=0.30, down=0.75, deg=0.60, sc=0.40, rain=0.20, stress=0.40),
    dict(r=14, flag="🇳🇱", gp="Dutch GP", circuit="Circuit Zandvoort", country="Netherlands",
         length=4.259, laps=72, rec=71.0, over=0.35, down=0.70, deg=0.50, sc=0.45, rain=0.30, stress=0.50,
         sprint=True),
    dict(r=15, flag="🇮🇹", gp="Italian GP", circuit="Autodromo Nazionale Monza", country="Italy",
         length=5.793, laps=53, rec=81.5, over=0.55, down=0.20, deg=0.40, sc=0.40, rain=0.25, stress=0.40),
    dict(r=16, flag="🇦🇿", gp="Azerbaijan GP", circuit="Baku City Circuit", country="Azerbaijan",
         length=6.003, laps=51, rec=100.0, over=0.40, down=0.30, deg=0.35, sc=0.75, rain=0.10, stress=0.80),
    dict(r=17, flag="🇸🇬", gp="Singapore GP", circuit="Marina Bay Street Circuit", country="Singapore",
         length=4.940, laps=62, rec=92.0, over=0.20, down=0.85, deg=0.45, sc=0.80, rain=0.45, stress=0.70,
         sprint=True),
    dict(r=18, flag="🇪🇸", gp="Madrid GP", circuit="IFEMA Madrid Street Circuit", country="Spain",
         length=5.400, laps=65, rec=85.0, over=0.50, down=0.50, deg=0.45, sc=0.45, rain=0.10, stress=0.45),
    dict(r=19, flag="🇺🇸", gp="United States GP", circuit="Circuit of the Americas", country="USA",
         length=5.513, laps=56, rec=93.0, over=0.55, down=0.60, deg=0.60, sc=0.35, rain=0.25, stress=0.45),
    dict(r=20, flag="🇲🇽", gp="Mexico City GP", circuit="Autodromo Hermanos Rodriguez", country="Mexico",
         length=4.304, laps=71, rec=78.0, over=0.50, down=0.40, deg=0.45, sc=0.40, rain=0.25, stress=0.45),
    dict(r=21, flag="🇧🇷", gp="Sao Paulo GP", circuit="Autodromo Jose Carlos Pace", country="Brazil",
         length=4.309, laps=71, rec=71.0, over=0.55, down=0.50, deg=0.55, sc=0.55, rain=0.40, stress=0.50),
    dict(r=22, flag="🇺🇸", gp="Las Vegas GP", circuit="Las Vegas Street Circuit", country="USA",
         length=6.201, laps=50, rec=90.0, over=0.50, down=0.25, deg=0.30, sc=0.60, rain=0.02, stress=0.60),
    dict(r=23, flag="🇶🇦", gp="Qatar GP", circuit="Losail International Circuit", country="Qatar",
         length=5.419, laps=57, rec=82.0, over=0.45, down=0.60, deg=0.85, sc=0.50, rain=0.02, stress=0.60,
         sprint=True),
    dict(r=24, flag="🇦🇪", gp="Abu Dhabi GP", circuit="Yas Marina Circuit", country="UAE",
         length=5.281, laps=58, rec=87.0, over=0.40, down=0.65, deg=0.45, sc=0.45, rain=0.01, stress=0.40),
]


def driver_price(overall: int) -> int:
    """Transfer fee curve: cheap in the midfield, brutal at the top."""
    base = 250_000 * exp((int(overall) - 55) * 0.125)
    return int(round(base, -5))


def driver_salary(overall: int) -> int:
    """Entry fee of one race weekend for this driver."""
    base = 50_000 * exp((int(overall) - 55) * 0.09)
    return int(round(base, -4))


def seed_all(db: Session) -> dict[str, int]:
    """Insert teams, drivers, circuits and achievements if they are missing."""
    created = {"teams": 0, "drivers": 0, "rounds": 0, "achievements": 0}

    for row in TEAMS:
        code = row[0]
        if db.scalar(select(Team).where(Team.code == code)) is None:
            db.add(
                Team(
                    code=row[0], name=row[1], country=row[2], engine=row[3], logo=row[4],
                    rating=row[5], price=row[6], aero=row[7], straight_line=row[8],
                    cornering=row[9], reliability=row[10], tire_management=row[11],
                    pit_crew=row[12], potential=row[13],
                )
            )
            created["teams"] += 1

    for row in DRIVERS:
        code = row[2]
        if db.scalar(select(Driver).where(Driver.code == code)) is None:
            overall = row[5]
            db.add(
                Driver(
                    number=row[0], name=row[1], code=row[2], country=row[3], team_name=row[4],
                    overall=overall, speed=row[6], qualifying=row[7], race_pace=row[8],
                    overtaking=row[9], defending=row[10], wet_skill=row[11],
                    tire_management=row[12], consistency=row[13], experience=row[14],
                    potential=row[15], pace=overall,
                    price=driver_price(overall), salary=driver_salary(overall),
                )
            )
            created["drivers"] += 1

    for info in TRACKS:
        if db.scalar(select(Track).where(Track.round_no == info["r"])) is None:
            db.add(
                Track(
                    round_no=info["r"], flag=info["flag"], gp_name=info["gp"],
                    circuit=info["circuit"], country=info["country"], length_km=info["length"],
                    laps=info["laps"], lap_record=info["rec"], overtaking=info["over"],
                    downforce=info["down"], tire_degradation=info["deg"],
                    safety_car_prob=info["sc"], rain_prob=info["rain"],
                    reliability_stress=info["stress"], has_sprint=bool(info.get("sprint")),
                )
            )
            created["rounds"] += 1

    created["achievements"] = achievements_svc.sync_catalog(db)
    return created
