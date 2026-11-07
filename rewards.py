"""
🏆 НЕДЕЛЬНЫЕ ИТОГИ, ВЫПЛАТЫ И РАСПИСАНИЕ

• Понедельник 00:00 МСК — итоги прошлой недели: топ-3 (по настройке призов)
  получают алмазы и крутки в ManhwCard, в чат уходит красивый пост (+ закреп).
• Каждую ночь в 00:00 — «итоги дня» (можно выключить: /toggle daily).
• Воскресенье в reminder_hour — напоминание «до конца недели N часов».
• Раз в 10 минут — повторная попытка выдать отложенные награды
  (если победитель ещё не был зарегистрирован в ManhwCard).

Всё идемпотентно: перезапуск бота не приведёт к двойной выплате.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta

import db
import manhwcard
import stats
import views
from config import MANHWCARD_USERNAME
from counter import COUNTER
from emojis import e
from stats import num
from views import LINE, btn, kb, medal, prize_txt

PENDING_DAYS = 30


# ═══════════════ выплата одной награды ═══════════════
async def pay(reward_id: int, notify: bool = True) -> str:
    r = db.one("SELECT week_key, place, user_id, messages, diamonds, attempts, status FROM rewards WHERE id = ?",
               (reward_id,))
    if not r:
        return "missing"
    wk, place, uid, msgs, dia, att, status = r
    if status in ("paid", "void", "expired"):
        return status

    if not dia and not att:
        res = "paid"
    else:
        res = await asyncio.to_thread(
            manhwcard.credit, f"patrol:{wk}:{place}", uid, dia, att, f"ManhwPatrol {wk} #{place}")

    now = int(time.time())
    if res in ("paid", "already"):
        db.exe("UPDATE rewards SET status = 'paid', paid_at = ?, note = NULL WHERE id = ?", (now, reward_id))
        if res == "paid" and notify and (dia or att):
            s = date.fromisoformat(wk)
            await manhwcard.notify(uid, (
                f"{e('trophy')} <b>Награда ManhwPatrol!</b>\n\n"
                f"Вы заняли {medal(place)} <b>{place} место</b> в недельном топе активности чата "
                f"({stats.fmt_range(wk, (s + timedelta(days=6)).isoformat())}) — "
                f"<b>{num(msgs)}</b> сообщений.\n\n"
                f"{e('gift')} Начислено: {prize_txt_raw(dia, att)}"))
        return "paid"
    if res == "no_user":
        db.exe("UPDATE rewards SET status = 'pending', note = 'не зарегистрирован в ManhwCard' WHERE id = ?",
               (reward_id,))
        return "pending"
    if res == "banned":
        db.exe("UPDATE rewards SET status = 'void', note = 'забанен в ManhwCard' WHERE id = ?", (reward_id,))
        return "void"
    db.exe("UPDATE rewards SET status = 'error', note = ? WHERE id = ?", (res[:200], reward_id))
    logging.error(f"Patrol reward {reward_id}: {res}")
    return "error"


def prize_txt_raw(dia, att) -> str:
    parts = []
    if dia:
        parts.append(f"<b>{num(dia)}</b> {e('diamond')} алмазов")
    if att:
        parts.append(f"<b>{num(att)}</b> {e('attempts')} круток")
    return " и ".join(parts) or "—"


# ═══════════════ подведение итогов недели ═══════════════
def pick_winners(a: str, b: str):
    """[(uid, messages)] — кто получит призы за период a..b."""
    p = views.prizes()
    min_m = int(db.setting("min_messages") or 0)
    out = []
    for uid, m, _ in stats.top_range(a, b, 200):
        if len(out) >= len(p) or m < min_m:
            break
        if manhwcard.is_banned(uid):
            continue
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
    winners = pick_winners(a, b)
    results = []
    for place, (uid, m) in enumerate(winners, 1):
        dia, att = p[place - 1]
        db.exe("INSERT OR IGNORE INTO rewards (week_key, place, user_id, messages, diamonds, attempts, status, "
               "created_at) VALUES (?, ?, ?, ?, ?, ?, 'new', ?)", (wk, place, uid, m, dia, att, int(time.time())))
        rid = db.val("SELECT id FROM rewards WHERE week_key = ? AND place = ?", (wk, place))
        results.append((place, uid, m, await pay(rid)))

    total = db.one(f"SELECT SUM(messages), COUNT(DISTINCT user_id) FROM {stats.SRC} "
                   f"WHERE day BETWEEN ? AND ? AND messages > 0", (a, b))
    tm, au = (total[0] or 0, total[1] or 0) if total else (0, 0)
    db.exe("UPDATE weeks SET status = 'done', total_messages = ?, active_users = ? WHERE week_key = ?",
           (tm, au, wk))
    logging.info(f"ManhwPatrol: неделя {wk} — {len(results)} победителей, {tm} сообщений")

    if post and tm:
        await post_results(bot, wk, a, b, results, tm, au)
    return results


def results_text(a, b, results, tm, au) -> str:
    lines = [f"{e('trophy')} <b>ИТОГИ НЕДЕЛИ</b> · {stats.fmt_range(a, b)}", LINE, ""]
    if results:
        for place, uid, m, status in results:
            lines.append(f"{medal(place)} {stats.mention(uid)} — <b>{num(m)}</b> {e('chat')}")
            reward = prize_txt(place)
            if status == "paid":
                lines.append(f"      {e('gift')} {reward} {e('check')}")
            elif status == "pending":
                lines.append(f"      {e('gift')} {reward} — <i>запусти @{MANHWCARD_USERNAME} и нажми /claim, "
                             f"награда ждёт {PENDING_DAYS} дней</i>")
            elif status == "error":
                lines.append(f"      {e('gift')} {reward} — <i>начислим чуть позже</i>")
    else:
        lines.append(f"{e('moon')} Никто не набрал минимум <b>{num(db.setting('min_messages'))}</b> сообщений — "
                     f"призы этой недели сгорают.")

    rest = stats.top_range(a, b, 10)
    shown = {r[1] for r in results}
    rest = [(u, m) for u, m, _ in rest if u not in shown]
    if rest:
        nm = stats.names([u for u, _ in rest])
        lines += ["", "<b>Дальше в топе:</b>"]
        start = len(results) + 1
        body = [f"{i}. {nm[u]} — {num(m)}" + (" · <i>вне зачёта</i>" if manhwcard.is_banned(u) else "")
                for i, (u, m) in enumerate(rest[:10 - len(results)], start)]
        lines.append("<blockquote>" + "\n".join(body) + "</blockquote>")

    lines += [
        "",
        f"{e('chat')} Сообщений за неделю: <b>{num(tm)}</b> · {e('users')} Активных: <b>{num(au)}</b>",
        "",
        f"{e('rocket')} <b>Новая неделя уже началась</b> — счёт обнулён, гонка за призами стартует заново!",
    ]
    return "\n".join(lines)


async def post_results(bot, wk, a, b, results, tm, au):
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


# ═══════════════ отложенные награды ═══════════════
async def retry_pending(bot=None) -> int:
    rows = db.q("SELECT id, user_id, created_at, status FROM rewards WHERE status IN ('pending', 'error', 'new')")
    paid = 0
    for rid, uid, created, status in rows:
        if status == "pending" and created and time.time() - created > PENDING_DAYS * 86400:
            db.exe("UPDATE rewards SET status = 'expired' WHERE id = ?", (rid,))
            continue
        if await pay(rid) == "paid":
            paid += 1
            if bot:
                try:
                    await bot.send_message(uid, f"{e('gift')} Ваша награда ManhwPatrol зачислена в "
                                                f"@{MANHWCARD_USERNAME}!")
                except Exception:
                    pass
    return paid


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
             f"{e('star')} <b>Активист дня:</b> {nm[rows[0][0]]} — {num(rows[0][1])}"]
    for i, (uid, m, _) in enumerate(rows[1:], 2):
        lines.append(f"{medal(i)} {nm[uid]} — {num(m)}")
    leaders = stats.top("week", 1)
    if leaders:
        lines += ["", f"{e('trophy')} Лидер недели: {stats.name(leaders[0][0])} — {num(leaders[0][1])} · "
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
    lines = [f"{e('alarm')} <b>ФИНИШНАЯ ПРЯМАЯ!</b>", LINE,
             f"{e('clock')} До итогов недели: <b>{stats.fmt_left(stats.week_end_dt())}</b>", "",
             f"{e('fire')} <b>Сейчас в призах:</b>"]
    for i, (uid, m, _) in enumerate(rows, 1):
        tail = f" · {e('gift')} {prize_txt(i)}" if prize_txt(i) else ""
        lines.append(f"{medal(i)} {nm[uid]} — <b>{num(m)}</b>{tail}")
    lines += ["", f"<i>Ещё можно ворваться в топ! Минимум для приза — {num(min_m)} сообщений.</i>"]
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

    # 4) Отложенные награды — раз в 10 минут
    last = int(db.get_meta("pending_retry") or 0)
    if time.time() - last > 600:
        db.set_meta("pending_retry", str(int(time.time())))
        await retry_pending(bot)


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
