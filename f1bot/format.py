"""Text formatting helpers: money, lap times, progress bars, pagination."""

from __future__ import annotations

from html import escape


def esc(text: object) -> str:
    return escape(str(text), quote=False)


def money(value: int | float | None) -> str:
    """1234567890 -> $1.23B, 12500000 -> $12.5M, 250000 -> $250K."""
    if value is None:
        return "-"
    value = int(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.0f}K"
    return f"{sign}${value}"


def lap_time(seconds: float) -> str:
    """90.412 -> 1:30.412"""
    if not seconds or seconds <= 0:
        return "--:--.---"
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:06.3f}"


def gap(delta: float) -> str:
    if delta <= 0:
        return "LEADER"
    return f"+{delta:.3f}s"


def rating_bar(value: int, total: int = 100, length: int = 10) -> str:
    value = max(0, min(total, value))
    filled = round(length * value / total)
    return "█" * filled + "░" * (length - filled)


def progress(done: int, total: int, length: int = 12) -> str:
    total = max(1, total)
    filled = min(length, round(length * max(0, done) / total))
    return "█" * filled + "░" * (length - filled)


def ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def position_emoji(pos: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, f"{pos}.")


def pager(page: int, pages: int, template: str) -> list[dict]:
    """Row of navigation buttons. ``template`` contains a ``{page}`` placeholder."""
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append({"text": "⬅️", "callback_data": template.format(page=page - 1)})
    row.append({"text": f"📄 {page + 1}/{pages}", "callback_data": "noop"})
    if page < pages - 1:
        row.append({"text": "➡️", "callback_data": template.format(page=page + 1)})
    return row
