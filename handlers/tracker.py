"""Подсчёт сообщений в отслеживаемых чатах + приветствие при добавлении в чат."""
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated, Message

import db
import stats
from chat_guard import leave_foreign
from config import CHAT_ID, CHAT_USERNAME
from counter import COUNTER
from emojis import e

router = Router(name="tracker")
GROUPS = {"group", "supergroup"}


@router.my_chat_member(F.chat.type.in_(GROUPS))
async def on_bot_added(ev: ChatMemberUpdated, bot: Bot):
    old, new = ev.old_chat_member.status, ev.new_chat_member.status
    if old not in ("left", "kicked") or new not in ("member", "administrator"):
        return
    if ev.chat.id != CHAT_ID:
        try:
            await bot.send_message(ev.chat.id, f"{e('lock')} ManhwPatrol работает только в @{CHAT_USERNAME}. "
                                               f"Ухожу отсюда — заглядывайте к нам!")
        except Exception:
            pass
        await leave_foreign(bot, ev.chat.id)
        return
    text = (f"{e('patrol')} <b>ManhwPatrol на посту!</b>\n\n"
            f"Я считаю активность чата: кто больше пишет — тот поднимается в топе, а топ-3 недели "
            f"получают {e('diamond')} алмазы и {e('attempts')} крутки в ManhwCard.\n\n"
            f"{e('check')} Подсчёт <b>включён</b>. Команды: /top · /me · /prizes")
    try:
        await bot.send_message(ev.chat.id, text)
    except Exception:
        pass


@router.message(F.chat.type.in_(GROUPS))
async def count_message(msg: Message):
    if not db.is_tracked(msg.chat.id):
        return
    u = msg.from_user
    if (u is None or u.is_bot or msg.sender_chat is not None or msg.via_bot is not None
            or getattr(msg, "forward_origin", None) is not None or getattr(msg, "is_automatic_forward", False)):
        return
    text = msg.text or msg.caption
    if text and text.lstrip().startswith("/"):
        return
    has_media = any((msg.photo, msg.sticker, msg.animation, msg.voice, msg.video_note,
                     msg.video, msg.audio, msg.document))
    ok, chars = COUNTER.judge(u.id, text, has_media, msg.date.timestamp() if msg.date else None)
    if not ok:
        return
    new_rank = COUNTER.add(u.id, chars, u.first_name, u.username)

    if new_rank and db.setting("rankups") and u.id not in db.excluded_ids():
        total = COUNTER.totals.get(u.id, 0)
        rname = stats.RANKS[new_rank][1]
        nxt = stats.RANKS[new_rank + 1] if new_rank + 1 < len(stats.RANKS) else None
        tail = (f"\n{e('up')} Следующее — «{nxt[1]}» через {stats.num(nxt[0] - total)} сообщений"
                if nxt else f"\n{e('crown')} Это высшее звание патруля!")
        try:
            who = f'<a href="tg://user?id={u.id}">{escape((u.first_name or "Игрок")[:28])}</a>'
            await msg.reply(f"{e('sparkle')} <b>Повышение!</b> {who} получает звание "
                            f"{e('r' + str(new_rank))} <b>{rname}</b> — {stats.num(total)} сообщений!{tail}",
                            disable_notification=True)
        except Exception:
            logging.debug("rankup reply failed", exc_info=True)
