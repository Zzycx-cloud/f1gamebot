"""Handler routers of the bot."""

from . import admin, garage, market, races, user  # noqa: F401

routers = [user.router, market.router, garage.router, races.router, admin.router]
