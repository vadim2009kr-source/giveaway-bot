"""Точка входа: запустите `python bot.py`, и бот начнёт работать."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import db
from config import BOT_TOKEN
from draw import scheduler
from handlers import admin, join, owner, premium


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN or "ВАШ_ТОКЕН" in BOT_TOKEN:
        raise SystemExit("Не найден токен. Создайте файл .env по образцу .env.example")

    await db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(owner.router, premium.router, join.router, admin.router)
    dp.errors.register(owner.on_error)

    await bot.set_my_commands([
        BotCommand(command="new", description="Создать розыгрыш"),
        BotCommand(command="my", description="Мои розыгрыши"),
        BotCommand(command="premium", description="Премиум"),
        BotCommand(command="invite", description="Пригласить админа"),
        BotCommand(command="paysupport", description="Помощь с оплатой"),
    ])

    checker = asyncio.create_task(scheduler(bot))  # фоновая проверка времени итогов
    backups = asyncio.create_task(owner.backup_loop(bot))  # ежедневная копия базы владельцу
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
