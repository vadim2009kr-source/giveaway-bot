"""Общие помощники, которые нужны в разных частях бота."""
import json
from datetime import datetime
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import FREE_LIMITS, MSK, PREMIUM_LIMITS


async def limits_for(user_id: int) -> dict:
    return PREMIUM_LIMITS if await db.is_premium(user_id) else FREE_LIMITS


async def is_subscribed(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Подписан ли человек на канал. Бот должен быть админом канала, иначе Telegram не ответит."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    if member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
        return True
    # «Ограниченный» участник всё ещё может быть подписан.
    return member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)


def extra_channels(giveaway) -> list[dict]:
    """Каналы-партнёры розыгрыша: [{"id": ..., "title": ..., "link": ...}]."""
    return json.loads(giveaway["extra_channels"] or "[]")


async def is_subscribed_all(bot: Bot, giveaway, user_id: int) -> bool:
    """Подписан ли человек на основной канал и на все каналы-партнёры."""
    channel_ids = [giveaway["channel_id"]] + [c["id"] for c in extra_channels(giveaway)]
    for chat_id in channel_ids:
        if not await is_subscribed(bot, chat_id, user_id):
            return False
    return True


def channel_link(chat) -> str | None:
    """Ссылка на канал: публичная по @username или пригласительная, если канал закрытый."""
    if chat.username:
        return f"https://t.me/{chat.username}"
    return chat.invite_link


def format_time(ts: int) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m.%Y %H:%M") + " (МСК)"


def post_text(text: str, winners: int, ends_at: int, bot_username: str, watermark: bool,
              partners: list[dict] | None = None) -> str:
    result = (
        f"{text}\n\n"
        f"🏆 Победителей: <b>{winners}</b>\n"
        f"⏰ Итоги: <b>{format_time(ends_at)}</b>\n"
    )
    if partners:
        result += "\nЧтобы участвовать, подпишитесь на этот канал и на каналы-партнёры:\n"
        for c in partners:
            title = escape(c["title"])
            result += f'• <a href="{escape(c["link"])}">{title}</a>\n' if c.get("link") else f"• {title}\n"
        result += "и нажмите кнопку ниже."
    else:
        result += "Чтобы участвовать, подпишитесь на канал и нажмите кнопку ниже."
    if watermark:
        result += f"\n\n<i>Розыгрыш проводится через @{escape(bot_username)}</i>"
    return result


def join_keyboard(giveaway_id: int, members: int = 0, promo_url: str | None = None) -> InlineKeyboardMarkup:
    text = f"🎉 Участвовать ({members})" if members else "🎉 Участвовать"
    rows = [[InlineKeyboardButton(text=text, callback_data=f"join:{giveaway_id}")]]
    if promo_url:
        # В бесплатной версии под постом есть кнопка, которая ведёт новых админов в бота.
        rows.append([InlineKeyboardButton(text="🎁 Провести свой розыгрыш", url=promo_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def post_keyboard(bot: Bot, giveaway_id: int, owner_id: int, members: int = 0) -> InlineKeyboardMarkup:
    """Кнопки под постом розыгрыша: с рекламной кнопкой, если у создателя бесплатная версия."""
    promo_url = None
    if (await limits_for(owner_id))["watermark"]:
        me = await bot.me()
        promo_url = f"https://t.me/{me.username}?start=gw"
    return join_keyboard(giveaway_id, members, promo_url)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'
