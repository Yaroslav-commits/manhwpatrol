"""
🔒 ЗАМОК НА ЧАТ

Бот работает только в config.CHAT_ID (@chatmanhwcard) и в личных сообщениях.
Любое сообщение или нажатие кнопки из другой группы игнорируется,
а бот из такой группы выходит.
"""
import logging

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message

from config import CHAT_ID

GROUPS = {"group", "supergroup"}
_left: set[int] = set()


async def leave_foreign(bot: Bot, chat_id: int):
    if chat_id in _left:
        return
    _left.add(chat_id)
    try:
        await bot.leave_chat(chat_id)
        logging.info(f"ManhwPatrol: вышел из чужого чата {chat_id}")
    except Exception:
        pass


class ChatGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message is not None:
            chat = event.message.chat
        if chat is not None and chat.type in GROUPS and chat.id != CHAT_ID:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            await leave_foreign(data["bot"], chat.id)
            return None
        return await handler(event, data)
