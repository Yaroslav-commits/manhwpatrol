"""Команды игроков."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

import stats
import views
from emojis import fb

router = Router(name="public")


async def _edit(cq: CallbackQuery, text, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            await cq.message.answer(text, reply_markup=markup)


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(msg: Message):
    markup = views.kb(
        [views.btn(f"{fb('trophy')} Топ недели", "ptop:week:0", icon="trophy"),
         views.btn(f"{fb('user')} Мой профиль", "pme", icon="user")],
        [views.btn(f"{fb('gift')} Призы", "pprizes", icon="gift"),
         views.btn(f"{fb('history')} Зал славы", "pwinners", icon="history")],
        [views.btn(f"{fb('chat')} Чат", url=views.chat_url(), icon="chat"),
         views.btn(f"{fb('card')} ManhwCard", url=views.mc_url(), icon="card")],
    )
    await msg.answer(views.help_view(), reply_markup=markup)


@router.message(Command("help", "patrol"))
async def cmd_help(msg: Message):
    await msg.answer(views.help_view())


@router.message(Command("top", "топ"))
async def cmd_top(msg: Message, command: CommandObject):
    arg = (command.args or "").strip().lower()
    alias = {"день": "day", "сегодня": "day", "d": "day", "day": "day",
             "неделя": "week", "w": "week", "week": "week",
             "месяц": "month", "m": "month", "month": "month",
             "все": "all", "всё": "all", "all": "all", "a": "all"}
    text, markup = views.top_view(alias.get(arg, "week"), 0)
    await msg.answer(text, reply_markup=markup)


@router.message(Command("me", "stats", "profile", "я"))
async def cmd_me(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        uid = msg.reply_to_message.from_user.id
    elif command.args:
        found = stats.find_user(command.args.split()[0])
        if found:
            uid = found
    text, markup = views.profile_view(uid)
    await msg.answer(text, reply_markup=markup)


@router.message(Command("prizes", "week", "призы"))
async def cmd_prizes(msg: Message):
    text, markup = views.prizes_view()
    await msg.answer(text, reply_markup=markup)


@router.message(Command("winners", "hall"))
async def cmd_winners(msg: Message):
    text, markup = views.winners_view()
    await msg.answer(text, reply_markup=markup)


@router.message(Command("ranks"))
async def cmd_ranks(msg: Message):
    await msg.answer(views.ranks_view(msg.from_user.id))


@router.message(Command("chatstats"))
async def cmd_chatstats(msg: Message):
    text, markup = views.chat_view()
    await msg.answer(text, reply_markup=markup)


# ─── кнопки ───
@router.callback_query(F.data.startswith("ptop:"))
async def cb_top(cq: CallbackQuery):
    try:
        _, period, page = cq.data.split(":")
        page = int(page)
    except ValueError:
        return await cq.answer()
    text, markup = views.top_view(period, page)
    await _edit(cq, text, markup)
    await cq.answer()


@router.callback_query(F.data.startswith("pmy:"))
async def cb_my_place(cq: CallbackQuery):
    period = cq.data.split(":", 1)[1]
    await cq.answer(views.my_place_alert(cq.from_user.id, period), show_alert=True)


@router.callback_query(F.data == "pprizes")
async def cb_prizes(cq: CallbackQuery):
    text, markup = views.prizes_view()
    await cq.message.answer(text, reply_markup=markup)
    await cq.answer()


@router.callback_query(F.data == "pwinners")
async def cb_winners(cq: CallbackQuery):
    text, markup = views.winners_view()
    await cq.message.answer(text, reply_markup=markup)
    await cq.answer()


@router.callback_query(F.data == "pme")
async def cb_me(cq: CallbackQuery):
    text, markup = views.profile_view(cq.from_user.id)
    await cq.message.answer(text, reply_markup=markup)
    await cq.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cq: CallbackQuery):
    await cq.answer()
