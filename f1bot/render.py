"""Small helper to edit a message in place with graceful fallbacks."""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .format import esc  # re-export for handlers


async def show(
    event: CallbackQuery | Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    alert: str | None = None,
    show_alert: bool = False,
) -> None:
    """Edit the current message (callback) or send a new one (command).

    Every screen rendered from a callback press is recorded in the per-user
    navigation history so the ⬅️ Back button can return to the previous screen.
    """
    if isinstance(event, CallbackQuery):
        data = getattr(event, "data", None)
        if data and data != "nav:back":
            from .services.runtime import push_screen

            try:
                push_screen(event.from_user.id, data)
            except Exception:
                pass
    if not isinstance(event, Message):
        message = getattr(event, "message", None)
        if message is not None:
            try:
                await message.edit_text(
                    text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True
                )
            except TelegramAPIError as exc:
                if "message is not modified" not in str(exc).lower():
                    # The old message is gone or has no markup — send a fresh one.
                    try:
                        await message.answer(
                            text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True
                        )
                    except TelegramAPIError:
                        pass
        await event.answer(text=alert, show_alert=show_alert)
    else:
        await event.answer(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


async def resend(
    event: CallbackQuery | Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Always send a brand new message (used for confirmations and results)."""
    if not isinstance(event, Message):
        message = getattr(event, "message", None)
        if message is not None:
            await message.answer(
                text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True
            )
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
