"""Команды администратора ManhwPatrol. Справка: /padmin"""
import asyncio
import io
import json
import logging
import os
import secrets
import sqlite3
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message

import db
import rewards
import stats
import views
from config import ADMIN_IDS, CHAT_ID, CHAT_USERNAME, DB_PATH
from counter import COUNTER, Counter
from emojis import e
from stats import num
from views import LINE, btn, kb

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(set(ADMIN_IDS)))
router.callback_query.filter(F.from_user.id.in_(set(ADMIN_IDS)))

TOGGLES = {
    "daily": "итоги дня в 00:00",
    "reminder": "напоминание в воскресенье",
    "rankups": "поздравления с новым званием",
    "pin": "закреп итогов недели",
}

HELP = (
    f"{e('shield')} <b>АДМИН-ПАНЕЛЬ ManhwPatrol</b>\n{LINE}\n"
    "<i>Цель — ID, @username или ответ на сообщение.</i>\n\n"
    f"{e('chat')} <b>Чаты</b>\n<blockquote expandable>"
    "/chats — чат патруля и статус бота в нём\n"
    "/say текст — объявление во все чаты"
    "</blockquote>\n"
    f"{e('gift')} <b>Призы и правила</b>\n<blockquote expandable>"
    "/settings — все настройки\n"
    "/setprize место алмазы крутки — приз за место (0 0 — убрать)\n"
    "/setmin N — минимум сообщений за неделю для приза\n"
    "/setcd сек [медиа_сек] [в_минуту] — антиспам\n"
    "/toggle daily|reminder|rankups|pin — вкл/выкл"
    "</blockquote>\n"
    f"{e('user')} <b>Игроки</b>\n<blockquote expandable>"
    "/pinfo цель — досье игрока\n"
    "/exclude цель [причина] — убрать из топа и призов\n"
    "/include цель — вернуть в топ\n"
    "/excluded — список исключённых\n"
    "/addmsg цель N — добавить (или N&lt;0 — убрать) сообщения за сегодня\n"
    "/resetweek цель — обнулить игроку текущую неделю"
    "</blockquote>\n"
    f"{e('trophy')} <b>Итоги и награды</b>\n<blockquote expandable>"
    "/pending — ведомость: победители + готовые команды ManhwCard, кнопки «✅ Выдал»\n"
    "/done ID — отметить награду выданной · /voidreward ID — отменить\n"
    "/preview — кто получит призы, если подвести итоги сейчас\n"
    "/finishweek — подвести итоги прошлой недели вручную (если бот был выключен)"
    "</blockquote>\n"
    f"{e('settings')} <b>Система</b>\n<blockquote expandable>"
    "/import — загрузить историю чата (JSON из Telegram Desktop)\n"
    "/plog [N] — журнал действий админов\n"
    "/pbackup — копия базы ManhwPatrol\n"
    "/pstatus — состояние бота и связи с ManhwCard"
    "</blockquote>"
)


def _target(msg: Message, command: CommandObject):
    args = (command.args or "").split()
    if args and (args[0].startswith("@") or (args[0].lstrip("-").isdigit() and abs(int(args[0])) > 100000)):
        return stats.find_user(args[0]), args[1:]
    r = msg.reply_to_message
    if r and r.from_user and not r.from_user.is_bot:
        return r.from_user.id, args
    return None, args


async def _need(msg, uid, usage):
    if uid is None:
        await msg.answer(f"{e('cross')} Не понял, кого. Формат: <code>{usage}</code>")
        return False
    return True


@router.message(Command("padmin", "phelp"))
async def cmd_padmin(msg: Message):
    await msg.answer(HELP)


# ═══════════════ ЧАТЫ ═══════════════
@router.message(Command("chats", "track", "untrack"))
async def cmd_chats(msg: Message, bot: Bot):
    try:
        chat = await bot.get_chat(CHAT_ID)
        title = escape(chat.title or "—")
        me = await bot.get_me()
        member = await bot.get_chat_member(CHAT_ID, me.id)
        status = {"administrator": "🟢 админ", "member": "🟢 участник"}.get(member.status, f"🔴 {member.status}")
    except Exception as ex:
        title, status = "—", f"🔴 бот не в чате ({escape(str(ex))[:80]})"
    await msg.answer(f"{e('chat')} <b>Чат патруля</b>\n{LINE}\n"
                     f"{title} · @{CHAT_USERNAME} · <code>{CHAT_ID}</code>\n"
                     f"Статус бота: {status}\n\n"
                     f"<i>Бот работает только в этом чате. Сменить чат — переменная PATROL_CHAT_ID.</i>")


@router.message(Command("say"))
async def cmd_say(msg: Message, command: CommandObject, bot: Bot):
    text = (command.args or "").strip()
    if not text:
        return await msg.answer("Формат: <code>/say текст</code> (можно с HTML-разметкой)")
    ok = 0
    for cid in db.tracked_chats():
        try:
            await bot.send_message(cid, f"{e('megaphone')} {text}")
            ok += 1
        except Exception:
            try:
                await bot.send_message(cid, f"📣 {text}", parse_mode=None)
                ok += 1
            except Exception as ex:
                await msg.answer(f"{cid}: {escape(str(ex))}")
    db.log(msg.from_user.id, "say", text)
    await msg.answer(f"{e('check')} Отправлено в чатов: {ok}")


# ═══════════════ НАСТРОЙКИ ═══════════════
@router.message(Command("settings"))
async def cmd_settings(msg: Message):
    lines = [f"{e('settings')} <b>НАСТРОЙКИ</b>", LINE, f"{e('gift')} <b>Призы</b>"]
    p = views.prizes()
    lines += [f"{views.medal(i)} {views.prize_txt(i)}" for i in range(1, len(p) + 1)] or ["<i>нет</i>"]
    lines += [
        "",
        f"{e('target')} Минимум для приза: <b>{num(db.setting('min_messages'))}</b> сообщений/неделю",
        f"{e('shield')} Антиспам: раз в <b>{db.setting('cooldown')}</b> с · медиа раз в "
        f"<b>{db.setting('media_cooldown')}</b> с · максимум <b>{db.setting('per_minute')}</b>/мин",
        f"{e('clock')} Напоминание: воскресенье, <b>{db.setting('reminder_hour')}:00</b> МСК",
        "",
    ]
    for k, label in TOGGLES.items():
        lines.append(f"{'🟢' if db.setting(k) else '🔴'} <code>{k}</code> — {label}")
    await msg.answer("\n".join(lines))


@router.message(Command("setprize"))
async def cmd_setprize(msg: Message, command: CommandObject):
    a = (command.args or "").split()
    if len(a) != 3 or not all(x.isdigit() for x in a) or not 1 <= int(a[0]) <= 10:
        return await msg.answer("Формат: <code>/setprize место алмазы крутки</code>\n"
                                "Пример: <code>/setprize 1 200 20</code> · убрать место: <code>/setprize 4 0 0</code>")
    place, dia, att = map(int, a)
    p = [list(x) for x in (db.setting("prizes") or [])]
    while len(p) < place:
        p.append([0, 0])
    p[place - 1] = [dia, att]
    while p and p[-1] == [0, 0]:
        p.pop()
    db.set_setting("prizes", p)
    db.log(msg.from_user.id, "setprize", f"{place}: {dia} {att}")
    await msg.answer(f"{e('check')} Приз за {place} место: {views.prize_txt(place) or 'убран'}\n"
                     f"Сейчас призовых мест: <b>{len(views.prizes())}</b>")


@router.message(Command("setmin"))
async def cmd_setmin(msg: Message, command: CommandObject):
    a = (command.args or "").strip()
    if not a.isdigit():
        return await msg.answer("Формат: <code>/setmin 100</code>")
    db.set_setting("min_messages", int(a))
    db.log(msg.from_user.id, "setmin", a)
    await msg.answer(f"{e('check')} Минимум для приза: <b>{num(a)}</b> сообщений за неделю")


@router.message(Command("setcd"))
async def cmd_setcd(msg: Message, command: CommandObject):
    a = (command.args or "").split()
    if not a or not all(x.isdigit() for x in a):
        return await msg.answer("Формат: <code>/setcd 3 10 15</code> — текст раз в 3 с, медиа раз в 10 с, "
                                "не больше 15 в минуту")
    for key, v in zip(("cooldown", "media_cooldown", "per_minute"), a):
        db.set_setting(key, int(v))
    db.log(msg.from_user.id, "setcd", " ".join(a))
    await msg.answer(f"{e('check')} Антиспам: {db.setting('cooldown')} с · медиа {db.setting('media_cooldown')} с · "
                     f"{db.setting('per_minute')}/мин")


@router.message(Command("toggle"))
async def cmd_toggle(msg: Message, command: CommandObject):
    k = (command.args or "").strip().lower()
    if k not in TOGGLES:
        return await msg.answer("Формат: <code>/toggle " + "|".join(TOGGLES) + "</code>")
    db.set_setting(k, not db.setting(k))
    db.log(msg.from_user.id, "toggle", f"{k}={db.setting(k)}")
    await msg.answer(f"{'🟢 Включено' if db.setting(k) else '🔴 Выключено'}: {TOGGLES[k]}")


# ═══════════════ ИГРОКИ ═══════════════
@router.message(Command("pinfo"))
async def cmd_pinfo(msg: Message, command: CommandObject):
    uid, _ = _target(msg, command)
    if not await _need(msg, uid, "/pinfo цель"):
        return
    text, _ = views.profile_view(uid)
    ex = db.one("SELECT reason, by_id, at FROM excluded WHERE user_id = ?", (uid,))
    u = db.one("SELECT username, first_seen, last_active FROM users WHERE user_id = ?", (uid,))
    rw = db.q("SELECT id, week_key, place, diamonds, attempts, status FROM rewards WHERE user_id = ? "
              "ORDER BY id DESC LIMIT 8", (uid,))
    extra = [
        "", f"{e('shield')} <b>Для админа</b>",
        f"🆔 <code>{uid}</code>" + (f" · @{escape(u[0])}" if u and u[0] else ""),
    ]
    if u and u[1]:
        extra.append(f"👁 Впервые: {datetime.fromtimestamp(u[1], stats.TZ):%d.%m.%Y} · последний раз: "
                     f"{datetime.fromtimestamp(u[2] or u[1], stats.TZ):%d.%m %H:%M}")
    if ex:
        extra.append(f"🔒 Исключён: <i>{escape(ex[0] or '—')}</i> (админ {ex[1]})")
    if rw:
        extra.append("🏆 Награды: " + ", ".join(f"#{r[0]} {r[1]}·{r[2]}м·{r[5]}" for r in rw))
    await msg.answer(text + "\n" + "\n".join(extra))


@router.message(Command("exclude"))
async def cmd_exclude(msg: Message, command: CommandObject):
    uid, rest = _target(msg, command)
    if not await _need(msg, uid, "/exclude цель [причина]"):
        return
    reason = " ".join(rest) or "Накрутка активности"
    db.exclude(uid, reason, msg.from_user.id)
    db.log(msg.from_user.id, "exclude", f"{uid} · {reason}")
    await msg.answer(f"{e('lock')} {stats.mention(uid)} исключён из топа и призов.\nПричина: <i>{escape(reason)}</i>")


@router.message(Command("include"))
async def cmd_include(msg: Message, command: CommandObject):
    uid, _ = _target(msg, command)
    if not await _need(msg, uid, "/include цель"):
        return
    if db.include(uid):
        db.log(msg.from_user.id, "include", str(uid))
        await msg.answer(f"{e('check')} {stats.mention(uid)} снова участвует в топе.")
    else:
        await msg.answer("Игрок не был исключён.")


@router.message(Command("excluded"))
async def cmd_excluded(msg: Message):
    rows = db.q("SELECT user_id, reason FROM excluded ORDER BY at DESC LIMIT 50")
    if not rows:
        return await msg.answer("Исключённых нет.")
    nm = stats.names([r[0] for r in rows])
    await msg.answer(f"{e('lock')} <b>Исключены из топа</b> ({len(rows)})\n" + "\n".join(
        f"• {nm[u]} <code>{u}</code> — <i>{escape(r or '—')}</i>" for u, r in rows))


@router.message(Command("addmsg"))
async def cmd_addmsg(msg: Message, command: CommandObject):
    uid, rest = _target(msg, command)
    if not await _need(msg, uid, "/addmsg цель N"):
        return
    if not rest or not rest[0].lstrip("-").isdigit() or int(rest[0]) == 0:
        return await msg.answer("Формат: <code>/addmsg цель 50</code> или <code>/addmsg цель -50</code>")
    n = int(rest[0])
    COUNTER.flush()
    d = stats.today().isoformat()
    db.exe("INSERT INTO msg_stats (user_id, day, messages, chars) VALUES (?, ?, MAX(0, ?), 0) "
           "ON CONFLICT(user_id, day) DO UPDATE SET messages = MAX(0, messages + ?)", (uid, d, n, n))
    db.exe("INSERT OR IGNORE INTO users (user_id, first_seen, last_active) VALUES (?, ?, ?)",
           (uid, int(time.time()), int(time.time())))
    COUNTER.load_totals()
    db.log(msg.from_user.id, "addmsg", f"{uid} {n:+d}")
    await msg.answer(f"{e('check')} {stats.mention(uid)}: {n:+d} сообщений за сегодня. "
                     f"Неделя: <b>{num(stats.user_period(uid, 'week')[0])}</b>")


@router.message(Command("resetweek"))
async def cmd_resetweek(msg: Message, command: CommandObject):
    uid, _ = _target(msg, command)
    if not await _need(msg, uid, "/resetweek цель"):
        return
    COUNTER.flush()
    a, b = stats.period_range("week")
    n = db.val(f"SELECT SUM(messages) FROM {stats.SRC} WHERE user_id = ? AND day BETWEEN ? AND ?", (uid, a, b))
    db.exe("DELETE FROM msg_stats WHERE user_id = ? AND day BETWEEN ? AND ?", (uid, a, b))
    db.exe("DELETE FROM hist_stats WHERE user_id = ? AND day BETWEEN ? AND ?", (uid, a, b))
    COUNTER.load_totals()
    db.log(msg.from_user.id, "resetweek", f"{uid} −{n}")
    await msg.answer(f"{e('check')} Неделя {stats.mention(uid)} обнулена (было {num(n)}).")


# ═══════════════ ИТОГИ И НАГРАДЫ ═══════════════
@router.message(Command("preview"))
async def cmd_preview(msg: Message):
    COUNTER.flush()
    a, b = stats.period_range("week")
    winners = rewards.pick_winners(a, b)
    results = [(i, uid, m) for i, (uid, m) in enumerate(winners, 1)]
    tm, au = stats.chat_totals("week")
    await msg.answer(f"{e('target')} <b>ПРЕДПРОСМОТР</b> — так выглядели бы итоги прямо сейчас "
                     f"(ничего не выдано)\n\n" + rewards.results_text(a, b, results, tm, au))


_CONFIRM: dict[str, str] = {}


@router.message(Command("finishweek"))
async def cmd_finishweek(msg: Message):
    ws = stats.week_start(stats.today()) - timedelta(days=7)
    row = db.one("SELECT status FROM weeks WHERE week_key = ?", (ws.isoformat(),))
    if row and row[0] == "done":
        return await msg.answer(f"Итоги недели {stats.fmt_day(ws.isoformat())} уже подведены.")
    token = secrets.token_hex(3)
    _CONFIRM[token] = ws.isoformat()
    a, b = ws.isoformat(), (ws + timedelta(days=6)).isoformat()
    w = rewards.pick_winners(a, b)
    nm = stats.names([u for u, _ in w])
    body = "\n".join(f"{views.medal(i)} {nm[u]} — {num(m)} → {views.prize_txt(i)}" for i, (u, m) in enumerate(w, 1))
    await msg.answer(f"{e('alarm')} Подвести итоги недели <b>{stats.fmt_range(a, b)}</b>? В чат уйдёт пост, вам — ведомость выдачи.\n\n"
                     f"{body or '<i>победителей нет</i>'}",
                     reply_markup=kb([btn("✅ Подвести", f"pfin:{token}"), btn("❌ Отмена", f"pfinx:{token}")]))


@router.callback_query(F.data.startswith("pfin"))
async def cb_finish(cq: CallbackQuery, bot: Bot):
    head, token = cq.data.split(":", 1)
    wk = _CONFIRM.pop(token, None)
    if not wk or head == "pfinx":
        await cq.message.edit_text("Отменено." if wk else "Устарело.")
        return await cq.answer()
    db.exe("DELETE FROM weeks WHERE week_key = ? AND status = 'skipped'", (wk,))
    res = await rewards.finalize_week(bot, datetime.fromisoformat(wk).date())
    db.log(cq.from_user.id, "finishweek", wk)
    await cq.message.edit_text(f"{e('check')} Итоги подведены, победителей: {len(res or [])}." if res is not None
                               else "Эта неделя уже обработана.")
    await cq.answer()


@router.message(Command("pending", "payouts"))
async def cmd_pending(msg: Message):
    weeks = [r[0] for r in db.q("SELECT DISTINCT week_key FROM rewards WHERE status = 'todo' ORDER BY week_key")]
    if not weeks:
        last = db.one("SELECT week_key FROM rewards ORDER BY week_key DESC LIMIT 1")
        if not last:
            return await msg.answer(f"{e('check')} Наград пока не было — первые итоги в понедельник в 00:00 МСК.")
        text, markup = rewards.payout_sheet(last[0])
        return await msg.answer(f"{e('check')} Невыданных наград нет. Последняя ведомость:\n\n" + text,
                                reply_markup=markup)
    for wk in weeks:
        text, markup = rewards.payout_sheet(wk)
        await msg.answer(text, reply_markup=markup)


async def _refresh_sheet(cq: CallbackQuery, reward_id: int):
    wk = db.val("SELECT week_key FROM rewards WHERE id = ?", (reward_id,), default=None)
    if wk:
        text, markup = rewards.payout_sheet(wk)
        try:
            await cq.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass


@router.callback_query(F.data.startswith("pdone:"))
async def cb_done(cq: CallbackQuery, bot: Bot):
    rid = int(cq.data.split(":", 1)[1])
    ok = await rewards.mark_paid(bot, rid, cq.from_user.id)
    await _refresh_sheet(cq, rid)
    await cq.answer("✅ Отмечено как выданное" if ok else "Уже отмечено другим админом", show_alert=not ok)


@router.callback_query(F.data.startswith("pvoid:"))
async def cb_void(cq: CallbackQuery):
    rid = int(cq.data.split(":", 1)[1])
    n = db.exe("UPDATE rewards SET status = 'void', note = ? WHERE id = ? AND status = 'todo'",
               (f"отменил {cq.from_user.id}", rid))
    if n:
        db.log(cq.from_user.id, "voidreward", f"#{rid}")
    await _refresh_sheet(cq, rid)
    await cq.answer("🚫 Награда отменена" if n else "Уже обработано")


@router.message(Command("done"))
async def cmd_done(msg: Message, command: CommandObject, bot: Bot):
    a = (command.args or "").strip().lstrip("#")
    if not a.isdigit():
        return await msg.answer("Формат: <code>/done ID</code> — или кнопка «✅ Выдал» в /pending")
    ok = await rewards.mark_paid(bot, int(a), msg.from_user.id)
    await msg.answer(f"{e('check')} Награда #{a} отмечена выданной." if ok else "Такой невыданной награды нет.")


@router.message(Command("voidreward"))
async def cmd_void(msg: Message, command: CommandObject):
    a = (command.args or "").strip().lstrip("#")
    if not a.isdigit():
        return await msg.answer("Формат: <code>/voidreward ID</code>")
    n = db.exe("UPDATE rewards SET status = 'void', note = 'отменено админом' WHERE id = ? AND status = 'todo'",
               (int(a),))
    db.log(msg.from_user.id, "voidreward", a)
    await msg.answer(f"{e('check')} Награда #{a} отменена." if n else "Такой невыданной награды нет.")


# ═══════════════ СИСТЕМА ═══════════════
@router.message(Command("pstatus"))
async def cmd_pstatus(msg: Message):
    COUNTER.flush()
    last = db.one("SELECT week_key, status FROM weeks ORDER BY week_key DESC LIMIT 1")
    pend = db.val("SELECT COUNT(*) FROM rewards WHERE status = 'todo'")
    users = db.val("SELECT COUNT(*) FROM users")
    total = stats.chat_totals("all")[0]
    lines = [
        f"{e('settings')} <b>СОСТОЯНИЕ</b>", LINE,
        f"💬 Чат: @{CHAT_USERNAME} <code>{CHAT_ID}</code>",
        f"👥 Игроков в базе: <b>{num(users)}</b> · сообщений: <b>{num(total)}</b>",
        f"🧮 В буфере: {sum(v[0] for v in COUNTER.buf.values())}",
        f"🏁 Последняя неделя: {last[0] + ' · ' + last[1] if last else '—'}",
        f"🎁 Ждут выдачи: <b>{pend}</b>" + (" → /pending" if pend else ""),
        f"📥 История импортирована: {db.get_meta('imported') or 'нет'}",
        f"💾 База: <code>{escape(DB_PATH)}</code>",
    ]
    await msg.answer("\n".join(lines))


@router.message(Command("plog"))
async def cmd_plog(msg: Message, command: CommandObject):
    n = int(command.args) if (command.args or "").strip().isdigit() else 25
    rows = db.q("SELECT admin_id, action, details, at FROM admin_log ORDER BY id DESC LIMIT ?", (min(n, 60),))
    if not rows:
        return await msg.answer("Журнал пуст.")
    lines = [f"{e('history')} <b>Журнал</b>", LINE]
    for aid, action, details, at in rows:
        lines.append(f"<code>{datetime.fromtimestamp(at, stats.TZ):%d.%m %H:%M}</code> <code>{aid}</code> "
                     f"<b>{action}</b> <i>{escape(details or '')[:100]}</i>")
    await msg.answer("\n".join(lines)[:4000])


@router.message(Command("pbackup"), F.chat.type == "private")
async def cmd_pbackup(msg: Message, bot: Bot):
    COUNTER.flush()
    path = os.path.join(tempfile.gettempdir(), f"patrol_{int(time.time())}.db")
    try:
        dst = sqlite3.connect(path)
        db.conn().backup(dst)
        dst.close()
        await bot.send_document(msg.chat.id, FSInputFile(path), caption="💾 Бэкап ManhwPatrol")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ═══════════════ ИМПОРТ ИСТОРИИ ═══════════════
def parse_export(raw: bytes, since: int):
    """Разбирает result.json из Telegram Desktop.
    → (агрегаты {(uid, day): [msgs, chars]}, имена {uid: name}, всего сообщений, засчитано)"""
    data = json.loads(raw.decode("utf-8"))
    msgs = data.get("messages", []) if isinstance(data, dict) else []
    tmp = Counter()
    agg = defaultdict(lambda: [0, 0])
    names = {}
    seen = counted = 0
    for m in msgs:
        if m.get("type") != "message" or "forwarded_from" in m:
            continue
        fid = str(m.get("from_id") or "")
        if not fid.startswith("user") or not fid[4:].isdigit():
            continue
        try:
            ts = int(m.get("date_unixtime") or 0)
        except (TypeError, ValueError):
            ts = 0
        if not ts or ts >= since:
            continue
        seen += 1
        uid = int(fid[4:])
        t = m.get("text", "")
        if isinstance(t, list):
            t = "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in t)
        t = str(t or "")
        if t.lstrip().startswith("/"):
            continue
        media = any(k in m for k in ("photo", "file", "sticker_emoji", "media_type"))
        ok, chars = tmp.judge(uid, t, media, ts)
        if not ok:
            continue
        counted += 1
        day = datetime.fromtimestamp(ts, stats.TZ).date().isoformat()
        a = agg[(uid, day)]
        a[0] += 1
        a[1] += chars
        if m.get("from"):
            names[uid] = str(m["from"])[:64]
    return agg, names, seen, counted


@router.message(Command("import"))
async def cmd_import(msg: Message, bot: Bot):
    doc = msg.document or (msg.reply_to_message.document if msg.reply_to_message else None)
    if not doc:
        return await msg.answer(
            f"{e('history')} <b>Импорт истории чата</b>\n\n"
            "1. Telegram Desktop → чат → ⋮ → «Экспорт истории чата»\n"
            "2. Снимите все галочки медиа, формат — <b>JSON</b>\n"
            "3. Пришлите сюда файл <code>result.json</code> с подписью /import "
            "(или ответьте /import на файл)\n\n"
            "<i>Учитываются только сообщения ДО начала подсчёта ботом — двойного счёта не будет. "
            "Повторный импорт заменяет прошлый. Лимит Telegram для ботов — 20 МБ "
            "(можно сжать в .json без медиа).</i>")
    if (doc.file_size or 0) > 20 * 1024 * 1024:
        return await msg.answer(f"{e('cross')} Файл больше 20 МБ — бот не может его скачать.")
    wait = await msg.answer(f"{e('hourglass')} Скачиваю и разбираю историю…")
    try:
        buf = io.BytesIO()
        await bot.download(doc, destination=buf)
        since = int(db.get_meta("tracking_since") or time.time())
        agg, names, seen, counted = await asyncio.to_thread(parse_export, buf.getvalue(), since)
    except Exception as ex:
        logging.exception("import")
        return await wait.edit_text(f"{e('cross')} Не получилось разобрать файл: {escape(str(ex))[:300]}")

    c = db.conn()
    c.execute("DELETE FROM hist_stats")
    c.executemany("INSERT INTO hist_stats (user_id, day, messages, chars) VALUES (?, ?, ?, ?)",
                  [(u, d, m, ch) for (u, d), (m, ch) in agg.items()])
    now = int(time.time())
    c.executemany("INSERT OR IGNORE INTO users (user_id, first_name, first_seen, last_active) VALUES (?, ?, ?, ?)",
                  [(u, n, now, now) for u, n in names.items()])
    c.commit()
    COUNTER.load_totals()
    stamp = f"{datetime.now(stats.TZ):%d.%m.%Y %H:%M} · {counted} сообщ."
    db.set_meta("imported", stamp)
    db.log(msg.from_user.id, "import", f"{seen} всего, {counted} засчитано, {len(names)} игроков")
    await wait.edit_text(
        f"{e('check')} <b>История загружена!</b>\n\n"
        f"Сообщений в файле (до старта бота): <b>{num(seen)}</b>\n"
        f"Засчитано с учётом антиспама: <b>{num(counted)}</b>\n"
        f"Игроков: <b>{num(len(names))}</b>\n\n"
        f"Топ «Всё время» и звания уже обновлены: /top all")
