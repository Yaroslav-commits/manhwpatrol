"""Периоды, звания, запросы для топов и профилей."""
from datetime import date, datetime, timedelta, timezone
from html import escape

import db
from config import TZ_OFFSET_HOURS

TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))

# Источник данных: живой подсчёт + импортированная история
SRC = ("(SELECT user_id, day, messages, chars FROM msg_stats "
       "UNION ALL SELECT user_id, day, messages, chars FROM hist_stats)")

PERIODS = {
    "day":   "Сегодня",
    "week":  "Неделя",
    "month": "Месяц",
    "all":   "Всё время",
}

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]


# ═══════════════ время ═══════════════
def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def day_key(d) -> str:
    return d.isoformat()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_key(d: date) -> str:
    return week_start(d).isoformat()


def week_range(d: date):
    s = week_start(d)
    return s, s + timedelta(days=6)


def period_range(period: str, ref: date | None = None):
    """(с, по) включительно в виде строк 'YYYY-MM-DD' или (None, None) для «всё время»."""
    d = ref or today()
    if period == "day":
        return d.isoformat(), d.isoformat()
    if period == "week":
        s, e = week_range(d)
        return s.isoformat(), e.isoformat()
    if period == "month":
        s = d.replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return s.isoformat(), e.isoformat()
    return None, None


def week_end_dt(d: date | None = None) -> datetime:
    """Момент подведения итогов текущей недели (пн 00:00 следующей)."""
    s = week_start(d or today())
    return datetime.combine(s + timedelta(days=7), datetime.min.time(), TZ)


def fmt_left(dt: datetime) -> str:
    sec = int((dt - now()).total_seconds())
    if sec <= 0:
        return "совсем скоро"
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if not d:
        parts.append(f"{m}м")
    return " ".join(parts)


def fmt_day(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def fmt_range(a: str, b: str) -> str:
    da, dbb = date.fromisoformat(a), date.fromisoformat(b)
    if da.month == dbb.month:
        return f"{da.day}-{dbb.day} {MONTHS_GEN[dbb.month - 1]}"
    return f"{fmt_day(a)} - {fmt_day(b)}"


def num(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct * width)))
    return "▰" * filled + "▱" * (width - filled)


# ═══════════════ звания ═══════════════
RANKS = [
    (0,      "Новобранец"),
    (50,     "Стажёр"),
    (250,    "Патрульный"),
    (750,    "Сержант"),
    (2000,   "Лейтенант"),
    (5000,   "Капитан"),
    (10000,  "Майор"),
    (25000,  "Полковник"),
    (50000,  "Генерал"),
    (100000, "Легенда патруля"),
]


def rank_index(total: int) -> int:
    idx = 0
    for i, (need, _) in enumerate(RANKS):
        if total >= need:
            idx = i
    return idx


def rank_name(total: int) -> str:
    return RANKS[rank_index(total)][1]


# ═══════════════ запросы ═══════════════
def _where(period, ref=None, alias=""):
    a, b = period_range(period, ref)
    col = f"{alias}day" if alias else "day"
    if a is None:
        return "", ()
    return f" AND {col} BETWEEN ? AND ?", (a, b)


def _excl_sql():
    ids = db.excluded_ids()
    if not ids:
        return "", ()
    return f" AND user_id NOT IN ({','.join('?' * len(ids))})", tuple(ids)


def top(period: str, limit: int = 10, offset: int = 0, ref=None, include_excluded=False):
    """[(user_id, messages, chars), ...]"""
    w, wp = _where(period, ref)
    x, xp = ("", ()) if include_excluded else _excl_sql()
    return db.q(f"SELECT user_id, SUM(messages) m, SUM(chars) c FROM {SRC} "
                f"WHERE 1=1{w}{x} GROUP BY user_id HAVING m > 0 "
                f"ORDER BY m DESC, c DESC, user_id LIMIT ? OFFSET ?", wp + xp + (limit, offset))


def top_range(a: str, b: str, limit: int = 50):
    x, xp = _excl_sql()
    return db.q(f"SELECT user_id, SUM(messages) m, SUM(chars) c FROM {SRC} "
                f"WHERE day BETWEEN ? AND ?{x} GROUP BY user_id HAVING m > 0 "
                f"ORDER BY m DESC, c DESC, user_id LIMIT ?", (a, b) + xp + (limit,))


def ranked_count(period: str, ref=None) -> int:
    w, wp = _where(period, ref)
    x, xp = _excl_sql()
    return db.val(f"SELECT COUNT(*) FROM (SELECT user_id FROM {SRC} WHERE 1=1{w}{x} "
                  f"GROUP BY user_id HAVING SUM(messages) > 0)", wp + xp)


def user_period(uid: int, period: str, ref=None):
    w, wp = _where(period, ref)
    r = db.one(f"SELECT SUM(messages), SUM(chars) FROM {SRC} WHERE user_id = ?{w}", (uid,) + wp)
    return (r[0] or 0, r[1] or 0) if r else (0, 0)


def place_of(uid: int, period: str, ref=None):
    """Место игрока в топе периода или None."""
    if uid in db.excluded_ids():
        return None
    m, c = user_period(uid, period, ref)
    if m <= 0:
        return None
    w, wp = _where(period, ref)
    x, xp = _excl_sql()
    better = db.val(f"SELECT COUNT(*) FROM (SELECT user_id, SUM(messages) m, SUM(chars) c FROM {SRC} "
                    f"WHERE 1=1{w}{x} GROUP BY user_id) "
                    f"WHERE m > ? OR (m = ? AND c > ?) OR (m = ? AND c = ? AND user_id < ?)",
                    wp + xp + (m, m, c, m, c, uid))
    return better + 1


def chat_totals(period: str, ref=None):
    """(сообщений, активных игроков)"""
    w, wp = _where(period, ref)
    r = db.one(f"SELECT SUM(messages), COUNT(DISTINCT user_id) FROM {SRC} WHERE messages > 0{w}", wp)
    return (r[0] or 0, r[1] or 0) if r else (0, 0)


def streak(uid: int) -> int:
    days = [r[0] for r in db.q(f"SELECT DISTINCT day FROM {SRC} WHERE user_id = ? AND messages > 0 "
                               f"ORDER BY day DESC LIMIT 400", (uid,))]
    if not days:
        return 0
    cur = today()
    if days[0] != cur.isoformat():
        cur -= timedelta(days=1)          # сегодня ещё не писал, но серия не сгорела
        if days[0] != cur.isoformat():
            return 0
    n = 0
    for d in days:
        if d == cur.isoformat():
            n += 1
            cur -= timedelta(days=1)
        else:
            break
    return n


def best_day(uid: int):
    return db.one(f"SELECT day, SUM(messages) m FROM {SRC} WHERE user_id = ? GROUP BY day "
                  f"ORDER BY m DESC LIMIT 1", (uid,))


def active_days(uid: int) -> int:
    return db.val(f"SELECT COUNT(DISTINCT day) FROM {SRC} WHERE user_id = ? AND messages > 0", (uid,))


def record_day():
    return db.one(f"SELECT day, SUM(messages) m FROM {SRC} GROUP BY day ORDER BY m DESC LIMIT 1")


def peak_hour(period: str, ref=None):
    w, wp = _where(period, ref)
    return db.one(f"SELECT hour, SUM(messages) m FROM hour_stats WHERE 1=1{w} GROUP BY hour "
                  f"ORDER BY m DESC LIMIT 1", wp)


def week_wins(uid: int) -> dict:
    rows = db.q("SELECT place, COUNT(*) FROM rewards WHERE user_id = ? AND status != 'void' GROUP BY place", (uid,))
    return {p: n for p, n in rows}


# ═══════════════ имена ═══════════════
def names(uids) -> dict:
    """{uid: имя (уже экранировано для HTML)}"""
    uids = list(dict.fromkeys(uids))
    if not uids:
        return {}
    ph = ",".join("?" * len(uids))
    rows = {r[0]: r for r in db.q(f"SELECT user_id, first_name, username FROM users WHERE user_id IN ({ph})",
                                  tuple(uids))}
    out = {}
    for u in uids:
        r = rows.get(u)
        raw = (r[1] if r and r[1] else None) or (f"@{r[2]}" if r and r[2] else None) or f"Игрок {u}"
        raw = str(raw).strip()[:28] or f"Игрок {u}"
        out[u] = escape(raw)
    return out


def name(uid) -> str:
    return names([uid])[uid]


def mention(uid) -> str:
    return f'<a href="tg://user?id={uid}">{name(uid)}</a>'


def find_user(token: str):
    """@username или ID → user_id."""
    token = (token or "").strip()
    if token.startswith("@"):
        r = db.one("SELECT user_id FROM users WHERE LOWER(username) = ?", (token[1:].lower(),))
        return r[0] if r else None
    if token.lstrip("-").isdigit():
        return int(token)
    return None
