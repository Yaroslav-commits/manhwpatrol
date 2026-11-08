"""Тексты и клавиатуры ManhwPatrol."""
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
import stats
from config import CHAT_USERNAME, MANHWCARD_USERNAME
from counter import COUNTER
from emojis import e, eid, fb
from stats import num

LINE = "━━━━━━━━━━━━━━━━"
PAGE = 10
MAX_PAGES = 5
MEDALS = {1: "gold", 2: "silver", 3: "bronze"}


def btn(text, cb=None, url=None, icon=None, style=None):
    kw = {}
    if cb:
        kw["callback_data"] = cb
    if url:
        kw["url"] = url
    if icon and eid(icon):
        kw["icon_custom_emoji_id"] = eid(icon)
    if style:
        kw["style"] = style
    return InlineKeyboardButton(text=text, **kw)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def chat_url():
    return f"https://t.me/{CHAT_USERNAME}"


def mc_url():
    return f"https://t.me/{MANHWCARD_USERNAME}"


def prizes():
    return [tuple(p) for p in (db.setting("prizes") or []) if (p[0] or p[1])]


def prize_txt(place: int) -> str:
    p = prizes()
    if place > len(p):
        return ""
    dia, att = p[place - 1]
    parts = []
    if dia:
        parts.append(f"{num(dia)} {e('diamond')}")
    if att:
        parts.append(f"{num(att)} {e('attempts')}")
    return " + ".join(parts)


def medal(place: int) -> str:
    return e(MEDALS[place]) if place in MEDALS else f"<b>{place}.</b>"


# ═══════════════ ТОП ═══════════════
def top_view(period: str, page: int = 0):
    COUNTER.flush()
    if period not in stats.PERIODS:
        period = "week"
    total = stats.ranked_count(period)
    pages = max(1, min(MAX_PAGES, (total + PAGE - 1) // PAGE))
    page %= pages
    rows = stats.top(period, PAGE, page * PAGE)
    nm = stats.names([r[0] for r in rows])
    min_m = int(db.setting("min_messages") or 0)

    a, b = stats.period_range(period)
    if period == "day":
        sub = f"{e('calendar')} {stats.fmt_day(a)}"
    elif period == "week":
        sub = (f"{e('calendar')} {stats.fmt_range(a, b)} · {e('clock')} итоги через "
               f"<b>{stats.fmt_left(stats.week_end_dt())}</b>")
    elif period == "month":
        sub = f"{e('calendar')} {stats.fmt_range(a, b)}"
    else:
        sub = f"{e('history')} С первого дня патруля"

    lines = [f"{e('trophy')} <b>ТОП АКТИВНОСТИ · {stats.PERIODS[period].upper()}</b>", LINE, sub, ""]
    if not rows:
        lines.append(f"{e('moon')} <i>Пока пусто. Напиши что-нибудь в чат, и ты первый в топе.</i>")
    for i, (uid, m, _) in enumerate(rows, start=page * PAGE + 1):
        line = f"{medal(i)} {nm[uid]}: <b>{num(m)}</b> {e('chat')}"
        if period == "week" and i <= len(prizes()):
            line += f"\n      {e('gift')} {prize_txt(i)}" + ("" if m >= min_m else f" · <i>нужно {num(min_m)}</i>")
        lines.append(line)

    msgs, users = stats.chat_totals(period)
    lines += ["", LINE, f"{e('chat')} Сообщений: <b>{num(msgs)}</b> · {e('users')} Активных: <b>{num(users)}</b>"]
    if pages > 1:
        lines.append(f"<i>Стр. {page + 1} из {pages}</i>")

    tabs = [btn(("• " + n + " •") if p == period else n, f"ptop:{p}:0") for p, n in stats.PERIODS.items()]
    nav = [btn("◀️", f"ptop:{period}:{(page - 1) % pages}"), btn(f"{page + 1}/{pages}", "noop"),
           btn("▶️", f"ptop:{period}:{(page + 1) % pages}")] if pages > 1 else None
    markup = kb(tabs[:2], tabs[2:], nav, [btn(f"{fb('target')} Моё место", f"pmy:{period}", icon="target"),
                                          btn(f"{fb('gift')} Призы", "pprizes", icon="gift")])
    return "\n".join(lines), markup


def my_place_alert(uid: int, period: str) -> str:
    COUNTER.flush()
    m, _ = stats.user_period(uid, period)
    place = stats.place_of(uid, period)
    label = stats.PERIODS.get(period, "")
    if uid in db.excluded_ids():
        return "🔒 Вы исключены из топа администрацией."
    if not place:
        return f"{label}: у вас пока 0 сообщений."
    txt = f"{label}: место #{place} · {num(m)} сообщений"
    if place > 1:
        rows = stats.top(period, 1, place - 2)
        if rows:
            txt += f"\nДо #{place - 1}: ещё {num(rows[0][1] - m + 1)}"
    if period == "week":
        min_m = int(db.setting("min_messages") or 0)
        if m < min_m:
            txt += f"\nДо участия в призах: ещё {num(min_m - m)}"
    return txt


# ═══════════════ ПРОФИЛЬ ═══════════════
def profile_view(uid: int):
    COUNTER.flush()
    total = stats.user_period(uid, "all")[0]
    ri = stats.rank_index(total)
    rname = stats.RANKS[ri][1]
    if ri + 1 < len(stats.RANKS):
        lo, (hi, nxt) = stats.RANKS[ri][0], stats.RANKS[ri + 1]
        pct = (total - lo) / max(1, hi - lo)
        prog = f"{stats.bar(pct)} <b>{int(pct * 100)}%</b>\n{e('up')} До «{nxt}»: ещё <b>{num(hi - total)}</b>"
    else:
        prog = f"{stats.bar(1)} <b>MAX</b>\n{e('crown')} Это высшее звание."

    d = stats.user_period(uid, "day")[0]
    w = stats.user_period(uid, "week")[0]
    mo = stats.user_period(uid, "month")[0]
    wp = stats.place_of(uid, "week")
    ap = stats.place_of(uid, "all")
    st = stats.streak(uid)
    bd = stats.best_day(uid)
    days = stats.active_days(uid)
    wins = stats.week_wins(uid)

    lines = [
        f"{e('patrol')} <b>ПАТРУЛЬНЫЙ</b> {stats.mention(uid)}",
        LINE,
        f"{e('r' + str(ri))} Звание: <b>{rname}</b>",
        prog,
        "",
        f"{e('chat')} <b>Сообщения</b>",
        f"├ Сегодня: <b>{num(d)}</b>",
        f"├ Неделя: <b>{num(w)}</b>" + (f" · место <b>#{wp}</b>" if wp else ""),
        f"├ Месяц: <b>{num(mo)}</b>",
        f"└ Всё время: <b>{num(total)}</b>" + (f" · место <b>#{ap}</b>" if ap else ""),
        "",
        f"{e('fire')} Серия: <b>{st}</b> дн. подряд",
    ]
    if bd and bd[1]:
        lines.append(f"{e('zap')} Лучший день: <b>{num(bd[1])}</b> · {stats.fmt_day(bd[0])}")
    if days:
        lines.append(f"{e('calendar')} Активных дней: <b>{days}</b> · в среднем <b>{num(total // days)}</b>/день")
    if wins:
        medals = " ".join(f"{fb(MEDALS.get(p, 'medal'))}{n}" for p, n in sorted(wins.items()))
        lines.append(f"{e('trophy')} Призовых недель: <b>{sum(wins.values())}</b> · {medals}")
    if uid in db.excluded_ids():
        lines += ["", f"{e('lock')} <i>Исключён из топа администрацией</i>"]

    pend = db.val("SELECT COUNT(*) FROM rewards WHERE user_id = ? AND status = 'todo'", (uid,))
    if pend:
        lines += ["", f"{e('gift')} Скоро администрация выдаст вам награду в @{MANHWCARD_USERNAME}."]

    markup = kb([btn(f"{fb('trophy')} Топ недели", "ptop:week:0", icon="trophy"),
                 btn(f"{fb('gift')} Призы", "pprizes", icon="gift")])
    return "\n".join(lines), markup


# ═══════════════ ПРИЗЫ ═══════════════
def prizes_view():
    COUNTER.flush()
    min_m = int(db.setting("min_messages") or 0)
    p = prizes()
    lines = [f"{e('gift')} <b>ПРИЗЫ НЕДЕЛИ</b>", LINE]
    if not p:
        lines.append("<i>Призы на этой неделе не назначены.</i>")
    for i in range(1, len(p) + 1):
        lines.append(f"{medal(i)} <b>{i} место:</b> {prize_txt(i)}")
    lines += [
        "",
        f"{e('card')} Награды выдаёт администрация в @{MANHWCARD_USERNAME} после итогов",
        f"{e('target')} Нужно минимум <b>{num(min_m)}</b> сообщений за неделю",
        f"{e('shield')} Флуд, спам и повторы не засчитываются",
        f"{e('clock')} Итоги: понедельник 00:00 МСК · через <b>{stats.fmt_left(stats.week_end_dt())}</b>",
    ]
    leaders = stats.top("week", 3)
    if leaders:
        nm = stats.names([r[0] for r in leaders])
        lines += ["", f"{e('fire')} <b>Сейчас лидируют:</b>"]
        for i, (uid, m, _) in enumerate(leaders, 1):
            lines.append(f"{medal(i)} {nm[uid]}: {num(m)}")
    markup = kb([btn(f"{fb('trophy')} Топ недели", "ptop:week:0", icon="trophy"),
                 btn(f"{fb('card')} ManhwCard", url=mc_url(), icon="card")])
    return "\n".join(lines), markup


# ═══════════════ ПОБЕДИТЕЛИ ═══════════════
def winners_view(limit_weeks: int = 6):
    weeks = db.q("SELECT week_key, total_messages, active_users FROM weeks WHERE status = 'done' "
                 "ORDER BY week_key DESC LIMIT ?", (limit_weeks,))
    lines = [f"{e('history')} <b>ЗАЛ СЛАВЫ</b>", LINE]
    if not weeks:
        lines.append("<i>Первые итоги будут в понедельник.</i>")
    for wk, tm, au in weeks:
        s = date.fromisoformat(wk)
        lines.append(f"\n{e('calendar')} <b>{stats.fmt_range(wk, (s + timedelta(days=6)).isoformat())}</b>"
                     f" · {num(tm)} {e('chat')}")
        rows = db.q("SELECT place, user_id, messages, status FROM rewards WHERE week_key = ? AND status != 'void' "
                    "ORDER BY place", (wk,))
        if not rows:
            lines.append("   <i>никто не набрал минимум</i>")
        nm = stats.names([r[1] for r in rows])
        for place, uid, m, status in rows:
            mark = ""
            lines.append(f"{medal(place)} {nm[uid]}: {num(m)}{mark}")
    # Рекордсмены
    champs = db.q("SELECT user_id, COUNT(*) c FROM rewards WHERE place = 1 AND status != 'void' "
                  "GROUP BY user_id ORDER BY c DESC LIMIT 3")
    if champs:
        nm = stats.names([r[0] for r in champs])
        lines += ["", f"{e('crown')} <b>Чаще всех на первом месте:</b>"]
        lines += [f"• {nm[u]}: {c}× {fb('gold')}" for u, c in champs]
    return "\n".join(lines), kb([btn(f"{fb('trophy')} Топ недели", "ptop:week:0", icon="trophy")])


# ═══════════════ ЗВАНИЯ ═══════════════
def ranks_view(uid: int | None = None):
    total = stats.user_period(uid, "all")[0] if uid else -1
    cur = stats.rank_index(total) if uid else -1
    lines = [f"{e('medal')} <b>ЗВАНИЯ ПАТРУЛЯ</b>", LINE, "<i>Звание растёт от сообщений за всё время.</i>", ""]
    for i, (need, n) in enumerate(stats.RANKS):
        mark = f"  ← <b>вы здесь</b>" if i == cur else ""
        lines.append(f"{e('r' + str(i))} <b>{n}</b>: от {num(need)}{mark}")
    return "\n".join(lines)


# ═══════════════ СТАТИСТИКА ЧАТА ═══════════════
def chat_view():
    COUNTER.flush()
    d = stats.chat_totals("day")
    w = stats.chat_totals("week")
    a = stats.chat_totals("all")
    ph = stats.peak_hour("week")
    rd = stats.record_day()
    lines = [
        f"{e('chart')} <b>СТАТИСТИКА ЧАТА</b>", LINE,
        f"{e('calendar')} Сегодня: <b>{num(d[0])}</b> сообщ. · {num(d[1])} {e('users')}",
        f"{e('calendar')} Неделя: <b>{num(w[0])}</b> сообщ. · {num(w[1])} {e('users')}",
        f"{e('history')} Всё время: <b>{num(a[0])}</b> сообщ. · {num(a[1])} {e('users')}",
    ]
    if ph and ph[1]:
        lines.append(f"{e('zap')} Пик недели: <b>{ph[0]:02d}:00-{(ph[0] + 1) % 24:02d}:00</b> МСК")
    if rd and rd[1]:
        lines.append(f"{e('rocket')} Рекорд дня: <b>{num(rd[1])}</b> · {stats.fmt_day(rd[0])}")
    hours = stats.day_key(stats.today())
    rows = db.q("SELECT hour, messages FROM hour_stats WHERE day = ? ORDER BY hour", (hours,))
    if rows:
        mx = max(m for _, m in rows) or 1
        blocks = "▁▂▃▄▅▆▇█"
        byh = dict(rows)
        spark = "".join(blocks[min(7, int(byh.get(h, 0) / mx * 7.999))] if byh.get(h) else " " for h in range(24))
        lines += ["", f"<b>Сегодня по часам:</b>", f"<code>{spark}</code>", "<code>0     6     12    18   </code>"]
    return "\n".join(lines), kb([btn(f"{fb('trophy')} Топ", "ptop:week:0", icon="trophy")])


def help_view():
    return "\n".join([
        f"{e('patrol')} <b>ManhwPatrol</b>",
        LINE,
        f"Я считаю сообщения в @{CHAT_USERNAME}. Каждую неделю трое самых активных получают "
        f"<b>алмазы {e('diamond')} и крутки {e('attempts')}</b> в @{MANHWCARD_USERNAME}.",
        "",
        f"{e('star')} <b>Команды</b>",
        "/top - топ за день, неделю, месяц и всё время",
        "/me - твой профиль (ответом на сообщение покажет чужой)",
        "/prizes - призы и время до итогов",
        "/winners - победители прошлых недель",
        "/ranks - звания",
        "/chatstats - статистика чата",
        "",
        f"{e('shield')} <b>Что не считается</b>",
        "<blockquote>Флуд, повторы одного и того же, «ааааа», пересылки и команды. "
        "Накрутчиков убираем из топа.</blockquote>",
    ])
