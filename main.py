"""
🚓 ManhwPatrol, патруль активности чата для ManhwCard

Запуск:  python main.py
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (BotCommand, BotCommandScopeAllGroupChats,
                           BotCommandScopeAllPrivateChats, BotCommandScopeChat)

import db
import rewards
from chat_guard import ChatGuard
from config import ADMIN_IDS, BOT_TOKEN, CHAT_ID, CHAT_USERNAME
from counter import COUNTER
from handlers import admin, public, tracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PUBLIC_COMMANDS = [
    BotCommand(command="top", description="🏆 Топ активности"),
    BotCommand(command="me", description="👤 Мой профиль"),
    BotCommand(command="prizes", description="🎁 Призы недели"),
    BotCommand(command="winners", description="📜 Зал славы"),
    BotCommand(command="ranks", description="🎖 Звания"),
    BotCommand(command="chatstats", description="📊 Статистика чата"),
    BotCommand(command="help", description="❓ Как это работает"),
]
ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="padmin", description="🛡 Админ-панель"),
    BotCommand(command="settings", description="⚙️ Настройки"),
    BotCommand(command="preview", description="🎯 Предпросмотр итогов"),
    BotCommand(command="pending", description="🎁 Выдать награды"),
    BotCommand(command="pstatus", description="🩺 Состояние"),
]


async def set_commands(bot: Bot):
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeChat(chat_id=CHAT_ID))
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        for aid in ADMIN_IDS:
            try:
                await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=aid))
            except Exception:
                pass
    except Exception:
        logging.exception("set_my_commands")


async def main():
    db.init()
    COUNTER.load_totals()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True))
    dp = Dispatcher()
    # Замок: только @chatmanhwcard и личка
    guard = ChatGuard()
    dp.message.outer_middleware(guard)
    dp.callback_query.outer_middleware(guard)
    # Порядок важен: команды раньше счётчика
    dp.include_router(admin.router)
    dp.include_router(public.router)
    dp.include_router(tracker.router)

    await set_commands(bot)
    try:
        chat = await bot.get_chat(CHAT_ID)
        logging.info(f"💬 Чат патруля: {chat.title} (@{CHAT_USERNAME})")
    except Exception as ex:
        logging.warning(f"⚠️ Бот не видит чат {CHAT_ID} (@{CHAT_USERNAME}): {ex}. Добавьте его в чат")
    tasks = [asyncio.create_task(rewards.scheduler(bot)), asyncio.create_task(rewards.flusher())]
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member"])
    finally:
        for t in tasks:
            t.cancel()
        COUNTER.flush()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
