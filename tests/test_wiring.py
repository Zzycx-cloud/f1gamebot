"""Every button the UI can emit must have a live handler behind it.

Collects the callback_data strings from keyboards.py + all handlers (static and
f-string templates) and matches each against the real aiogram routers.
"""

from __future__ import annotations

import re
from pathlib import Path

from aiogram.types import CallbackQuery, User as TgUser

from f1bot.handlers import admin, garage, market, races, user

ROUTERS = [user.router, market.router, garage.router, races.router, admin.router]

SRC = [Path(__file__).parent.parent / "f1bot" / "keyboards.py"] + sorted(
    (Path(__file__).parent.parent / "f1bot" / "handlers").glob("*.py")
)

# btn("label", "callback") AND btn(t(lang, "key"), "callback") — collect the
# callback literal from either form.
CALLBACK_RE = re.compile(
    r"btn\(\s*(?:f?[\"'][^\"']*[\"']|t\([^)]*\))\s*,\s*(?:f)?[\"']([^\"']+)[\"']"
)

# f-string placeholders -> sample values that a real press could carry
SAMPLES = {
    "{page}": "0", "{i}": "0", "{id}": "1", "{user_id}": "10", "{race_id}": "1",
    "{kind}": "team", "{item_id}": "1", "{driver_id}": "1", "{team_id}": "1",
    "{field}": "name", "{n}": "30", "{minutes}": "30", "{lvl}": "1", "{level}": "1",
    "{days}": "30", "{r}": "1", "{s}": "1", "{key}": "chassis", "{tab}": "me",
    "{which}": "drivers", "{code}": "MER",
}


def _normalize(template: str) -> str:
    for key, value in SAMPLES.items():
        template = template.replace(key, value)
    return re.sub(r"\{[^}]*\}", "1", template)


def _collect() -> set[str]:
    found = set()
    for path in SRC:
        text = path.read_text(encoding="utf-8")
        for cb in CALLBACK_RE.findall(text):
            if ":" in cb or cb == "noop":
                found.add(_normalize(cb))
    return found


def _fake(data: str) -> CallbackQuery:
    return CallbackQuery(
        id="1", chat_instance="1", data=data,
        from_user=TgUser(id=10, is_bot=False, first_name="T"),
    )


async def _wired(data: str) -> bool:
    cb = _fake(data)
    for router in ROUTERS:
        for handler in router.callback_query.handlers:
            try:
                ok, _data = await handler.check(cb)
            except Exception:
                ok = False
            if ok:
                return True
    return False


def test_all_buttons_have_handlers() -> None:
    import asyncio

    callbacks = _collect()
    assert len(callbacks) > 100, "callback collector found nothing — it is broken"
    missing = [cb for cb in sorted(callbacks) if not asyncio.run(_wired(cb))]
    assert not missing, f"dead buttons without handlers: {missing}"


def test_bogus_callback_is_rejected() -> None:
    """Guard: the matcher above must not trivially match everything."""
    import asyncio

    assert not asyncio.run(_wired("zzz:bogus:xyz"))
