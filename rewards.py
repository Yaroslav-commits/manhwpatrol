"""
🏆 НЕДЕЛЬНЫЕ ИТОГИ И РАСПИСАНИЕ (награды выдаются вручную)

• Понедельник 00:00 МСК: итоги прошлой недели.
    В чат уходит пост с победителями (и закрепляется), а каждому админу
    в личку приходит ведомость с готовыми командами ManhwCard
    (/give_diamond, /give_attempts). Скопировал, отправил в ManhwCard,
    нажал «✅ Выдал», и победителю приходит сообщение от ManhwPatrol
    (если он запускал бота).
• Каждую ночь в 00:00: итоги дня (выключается командой /toggle daily).
• Воскресенье вечером: напоминание о скором конце недели.

Всё идемпотентно: перезапуск бота не подведёт итоги дважды.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta

from aiogram.types import InlineKeyboardMarkup

import db
import stats
import views
from config import ADMIN_IDS, MANHWCARD_USERNAME
from counter import COUNTER
from emojis import e
from stats import num
from views import LINE, btn, kb, medal, prize_txt

STATUS = {"todo": "⏳ выдать", "paid": "✅ выдано", "void": "🚫 отменено"}


def prize_txt_raw(dia, att) -> str:
    parts = []
    if dia:
        parts.append(f"<b>{num(dia)}</b> {e('diamond')} алмазов")
    if att:
        parts.append(f"<b>{num(att)}</b> {e('attempts')} круток")
    return " и ".join(parts) or "ничего"


def week_label(wk: str) -> str:
    s = date.fromisoformat(wk)
    return stats.fmt_range(wk, (s + timedelta(days=6)).isoformat())


# ═══════════════ ведомость для админа ═══════════════
def payout_commands(uid: int, dia: int, att: int) -> str:
    """Готовые команды ManhwCard (нажатие по <code> копирует строку)."""
    out = []
    if dia:
        out.append(f"<code>/give_diamond {uid} {dia}</code>")
    if att:
        out.append(f"<code>/give_attempts {uid} {att}</code>")
    return "\n".join(out)


def payout_sheet(wk: str):
    """Текст и кнопки ведомости выдачи за неделю wk."""
    rows = db.q("SELECT id, place, user_id, messages, diamonds, attempts, status FROM rewards "
                "WHERE week_key = ? ORDER BY place", (wk,))
    nm = stats.names([r[2] for r in rows])
    lines = [f"{e('gift')} <b>ВЫДАЧА НАГРАД</b> · {week_label(wk)}", LINE,
             "<i>Нажмите на команду, чтобы скопировать, и отправьте её в ManhwCard. "
             "После этого нажмите «✅ Выдал».</i>"]
    buttons = []
    for rid, place, uid, m, dia, att, st in rows:
        lines += ["", f"{medal(place)} <b>{place} место</b> · {nm[uid]} · <code>{uid}</code>",
                  f"   {e('chat')} {num(m)} · {e('gift')} {views_prize(dia, att)} · {STATUS.get(st, st)}"]
        if st == "todo":
            lines.append(payout_commands(uid, dia, att))
            buttons.append([btn(f"✅ Выдал {place} месту", f"pdone:{rid}"),
                            btn("🚫", f"pvoid:{rid}")])
    if not rows:
        lines.append("\n<i>Победителей нет, никто не набрал минимум.</i>")
    elif not buttons:
        lines.append(f"\n{e('check')} <b>Все награды выданы.</b>")
    return "\n".join(lines), (InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)


def views_prize(dia, att) -> str:
    parts = []
    if dia:
        parts.append(f"{num(dia)} {e('diamond')}")
    if att:
        parts.append(f"{num(att)} {e('attempts')}")
    return " + ".join(parts) or "ничего"


async def send_sheet_to_admins(bot, wk: str):
    text, markup = payout_sheet(wk)
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text, reply_markup=markup)
        except Exception as ex:
            logging.warning(f"Ведомость админу {aid}: {ex} (админ должен нажать /start у ManhwPatrol)")


async def mark_paid(bot, reward_id: int, admin_id: int) -> bool:
    """Отмечает награду выданной и поздравляет победителя."""
    r = db.one("SELECT week_key, place, user_id, messages, diamonds, attempts FROM rewards "
               "WHERE id = ? AND status = 'todo'", (reward_id,))
    if not r or not db.exe("UPDATE rewards SET status = 'paid', paid_at = ?, note = ? WHERE id = ? AND status = 'todo'",
                           (int(time.time()), f"выдал {admin_id}", reward_id)):
        return False
    wk, place, uid, m, dia, att = r
    db.log(admin_id, "reward_paid", f"#{reward_id} {wk} {place}м {uid} +{dia}💎 +{att}💳")
    try:
        await bot.send_message(uid, (
            f"{e('trophy')} <b>Награда ManhwPatrol</b>\n\n"
            f"Вы заняли {medal(place)} <b>{place} место</b> в недельном топе активности чата "
            f"({week_label(wk)}), у вас <b>{num(m)}</b> сообщений.\n\n"
            f"{e('gift')} В @{MANHWCARD_USERNAME} начислено: {prize_txt_raw(dia, att)}"))
    except Exception:
        pass  # игрок не запускал ManhwPatrol, а ManhwCard и так прислал «Вам начислено…»
    return True


# ═══════════════ подведение итогов недели ═══════════════
def pick_winners(a: str, b: str):
    """[(uid, messages)]: кто получит призы за период a..b."""
    p = views.prizes()
    min_m = int(db.setting("min_messages") or 0)
    out = []
    for uid, m, _ in stats.top_range(a, b, len(p) + 5):
        if len(out) >= len(p) or m < min_m:
            break
        out.append((uid, m))
    return out


async def finalize_week(bot, ws: date, post: bool = True):
    """Подводит итоги недели, начинающейся с понедельника ws. Повторный вызов ничего не делает."""
    wk = ws.isoformat()
    a, b = wk, (ws + timedelta(days=6)).isoformat()
    if not db.exe("INSERT OR IGNORE INTO weeks (week_key, status, finalized_at) VALUES (?, 'processing', ?)",
                  (wk, int(time.time()))):
        return None
    COUNTER.flush()

    p = views.prizes()
    results = []
    for place, (uid, m) in enumerate(pick_winners(a, b), 1):
        dia, att = p[place - 1]
        db.exe("INSERT OR IGNORE INTO rewards (week_key, place, user_id, messages, diamonds, attempts, status, "
               "created_at) VALUES (?, ?, ?, ?, ?, ?, 'todo', ?)", (wk, place, uid, m, dia, att, int(time.time())))
        results.append((place, uid, m))

    total = db.one(f"SELECT SUM(messages), COUNT(DISTINCT user_id) FROM {stats.SRC} "
                   f"WHERE day BETWEEN ? AND ? AND messages > 0", (a, b))
    tm, au = (total[0] or 0, total[1] or 0) if total else (0, 0)
    db.exe("UPDATE weeks SET status = 'done', total_messages = ?, active_users = ? WHERE week_key = ?",
           (tm, au, wk))
    logging.info(f"ManhwPatrol: неделя {wk}, {len(results)} победителей, {tm} сообщений")

    if post and tm:
        await post_results(bot, a, b, results, tm, au)
    if results:
        await send_sheet_to_admins(bot, wk)
    return results


def results_text(a, b, results, tm, au) -> str:
    lines = [f"{e('trophy')} <b>ИТОГИ НЕДЕЛИ</b> · {stats.fmt_range(a, b)}", LINE, ""]
    if results:
        for place, uid, m in results:
            lines.append(f"{medal(place)} {stats.mention(uid)}: <b>{num(m)}</b> {e('chat')}")
            lines.append(f"      {e('gift')} {prize_txt(place)}")
        lines += ["", f"{e('card')} <i>Награды придут в @{MANHWCARD_USERNAME} в ближайшее время.</i>"]
    else:
        lines.append(f"{e('moon')} Никто не набрал минимум в <b>{num(db.setting('min_messages'))}</b> сообщений, "
                     f"поэтому призов на этой неделе нет.")

    shown = {r[1] for r in results}
    rest = [(u, m) for u, m, _ in stats.top_range(a, b, 10) if u not in shown]
    if rest:
        nm = stats.names([u for u, _ in rest])
        start = len(results) + 1
        body = [f"{i}. {nm[u]}: {num(m)}" for i, (u, m) in enumerate(rest[:10 - len(results)], start)]
        lines += ["", "<b>Дальше в топе:</b>", "<blockquote>" + "\n".join(body) + "</blockquote>"]

    lines += [
        "",
        f"{e('chat')} Сообщений за неделю: <b>{num(tm)}</b> · {e('users')} Активных: <b>{num(au)}</b>",
        "",
        f"{e('rocket')} Новая неделя началась, счёт обнулился. Всем удачи!",
    ]
    return "\n".join(lines)


async def post_results(bot, a, b, results, tm, au):
    text = results_text(a, b, results, tm, au)
    markup = kb([btn("🏆 Топ всех времён", "ptop:all:0", icon="trophy"),
                 btn("🎴 ManhwCard", url=views.mc_url(), icon="card")])
    for chat_id in db.tracked_chats():
        try:
            m = await bot.send_message(chat_id, text, reply_markup=markup)
            if db.setting("pin"):
                try:
                    await bot.pin_chat_message(chat_id, m.message_id, disable_notification=True)
                except Exception:
                    pass
        except Exception as ex:
            logging.warning(f"Итоги недели в {chat_id}: {ex}")


# ═══════════════ итоги дня и напоминание ═══════════════
async def daily_summary(bot, day: date):
    COUNTER.flush()
    d = day.isoformat()
    rows = stats.top_range(d, d, 3)
    if not rows:
        return
    tm, au = db.one(f"SELECT SUM(messages), COUNT(DISTINCT user_id) FROM {stats.SRC} WHERE day = ?", (d,))
    nm = stats.names([r[0] for r in rows])
    lines = [f"{e('moon')} <b>ИТОГИ ДНЯ</b> · {stats.fmt_day(d)}", LINE,
             f"{e('chat')} <b>{num(tm)}</b> сообщений · {e('users')} <b>{num(au)}</b> активных", "",
             f"{e('star')} <b>Активист дня:</b> {nm[rows[0][0]]}, {num(rows[0][1])} сообщ."]
    for i, (uid, m, _) in enumerate(rows[1:], 2):
        lines.append(f"{medal(i)} {nm[uid]}: {num(m)}")
    leaders = stats.top("week", 1)
    if leaders:
        lines += ["", f"{e('trophy')} Лидер недели: {stats.name(leaders[0][0])}, {num(leaders[0][1])} сообщ. · "
                      f"до итогов <b>{stats.fmt_left(stats.week_end_dt())}</b>"]
    text = "\n".join(lines)
    for chat_id in db.tracked_chats():
        try:
            await bot.send_message(chat_id, text, disable_notification=True)
        except Exception as ex:
            logging.warning(f"Итоги дня в {chat_id}: {ex}")


async def week_reminder(bot):
    COUNTER.flush()
    rows = stats.top("week", 5)
    if not rows:
        return
    nm = stats.names([r[0] for r in rows])
    min_m = int(db.setting("min_messages") or 0)
    lines = [f"{e('alarm')} <b>Скоро итоги недели</b>", LINE,
             f"{e('clock')} До итогов недели: <b>{stats.fmt_left(stats.week_end_dt())}</b>", "",
             f"{e('fire')} <b>Сейчас в призах:</b>"]
    for i, (uid, m, _) in enumerate(rows, 1):
        tail = f" · {e('gift')} {prize_txt(i)}" if prize_txt(i) else ""
        lines.append(f"{medal(i)} {nm[uid]}: <b>{num(m)}</b>{tail}")
    lines += ["", f"<i>Ещё можно успеть в топ. Для приза нужно минимум {num(min_m)} сообщений.</i>"]
    text = "\n".join(lines)
    markup = kb([btn("🏆 Топ недели", "ptop:week:0", icon="trophy")])
    for chat_id in db.tracked_chats():
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
        except Exception as ex:
            logging.warning(f"Напоминание в {chat_id}: {ex}")


# ═══════════════ планировщик ═══════════════
async def tick(bot):
    now = stats.now()
    today = now.date()
    installed = int(db.get_meta("installed_at") or 0)

    # 1) Итоги прошлой недели (только если бот работал в ту неделю)
    prev_ws = stats.week_start(today) - timedelta(days=7)
    prev_end = datetime.combine(prev_ws + timedelta(days=7), datetime.min.time(), stats.TZ).timestamp()
    if not db.one("SELECT 1 FROM weeks WHERE week_key = ?", (prev_ws.isoformat(),)):
        if prev_end > installed:
            await finalize_week(bot, prev_ws)
        else:
            db.exe("INSERT OR IGNORE INTO weeks (week_key, status, finalized_at, total_messages, active_users) "
                   "VALUES (?, 'skipped', ?, 0, 0)", (prev_ws.isoformat(), int(time.time())))

    # 2) Итоги вчерашнего дня
    yday = today - timedelta(days=1)
    key = f"daily:{yday.isoformat()}"
    if db.get_meta(key) is None:
        db.set_meta(key, "1")
        yend = datetime.combine(today, datetime.min.time(), stats.TZ).timestamp()
        if db.setting("daily") and yend > installed and now.hour < 3:
            await daily_summary(bot, yday)

    # 3) Напоминание в воскресенье
    if today.weekday() == 6 and now.hour >= int(db.setting("reminder_hour") or 20):
        key = f"remind:{stats.week_key(today)}"
        if db.get_meta(key) is None:
            db.set_meta(key, "1")
            if db.setting("reminder") and now.hour < 23:
                await week_reminder(bot)

    # 4) Напоминание админам о невыданных наградах, раз в сутки в 12:00
    key = f"todo_ping:{today.isoformat()}"
    if now.hour >= 12 and db.get_meta(key) is None:
        db.set_meta(key, "1")
        weeks = [r[0] for r in db.q("SELECT DISTINCT week_key FROM rewards WHERE status = 'todo' "
                                    "AND created_at < ?", (int(time.time()) - 6 * 3600,))]
        for wk in weeks:
            await send_sheet_to_admins(bot, wk)


async def scheduler(bot):
    while True:
        try:
            await tick(bot)
        except Exception:
            logging.exception("ManhwPatrol scheduler")
        await asyncio.sleep(30)


async def flusher():
    while True:
        await asyncio.sleep(5)
        try:
            COUNTER.flush()
        except Exception:
            logging.exception("ManhwPatrol flush")
