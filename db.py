"""База ManhwPatrol (SQLite). Все вызовы — из одного потока event loop."""
import json
import sqlite3
import time

from config import DB_PATH, DEFAULTS

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, timeout=15)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def q(sql, params=()):
    return conn().execute(sql, params).fetchall()


def one(sql, params=()):
    return conn().execute(sql, params).fetchone()


def val(sql, params=(), default=0):
    r = one(sql, params)
    return r[0] if r and r[0] is not None else default


def exe(sql, params=()) -> int:
    c = conn()
    cur = c.execute(sql, params)
    c.commit()
    return cur.rowcount


def many(sql, seq):
    c = conn()
    c.executemany(sql, seq)
    c.commit()


def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
        first_seen INTEGER, last_active INTEGER);
    CREATE TABLE IF NOT EXISTS msg_stats (
        user_id INTEGER, day TEXT, messages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, day));
    CREATE TABLE IF NOT EXISTS hist_stats (
        user_id INTEGER, day TEXT, messages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, day));
    CREATE INDEX IF NOT EXISTS idx_msg_day ON msg_stats(day);
    CREATE INDEX IF NOT EXISTS idx_hist_day ON hist_stats(day);
    CREATE TABLE IF NOT EXISTS hour_stats (
        day TEXT, hour INTEGER, messages INTEGER DEFAULT 0, PRIMARY KEY (day, hour));
    CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY, title TEXT, added_by INTEGER, added_at INTEGER);
    CREATE TABLE IF NOT EXISTS excluded (
        user_id INTEGER PRIMARY KEY, reason TEXT, by_id INTEGER, at INTEGER);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS weeks (
        week_key TEXT PRIMARY KEY, status TEXT, finalized_at INTEGER,
        total_messages INTEGER, active_users INTEGER);
    CREATE TABLE IF NOT EXISTS rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT, week_key TEXT, place INTEGER, user_id INTEGER,
        messages INTEGER, diamonds INTEGER, attempts INTEGER, status TEXT, note TEXT,
        created_at INTEGER, paid_at INTEGER, UNIQUE (week_key, place));
    CREATE TABLE IF NOT EXISTS admin_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, details TEXT, at INTEGER);
    """)
    c.commit()
    if get_meta("installed_at") is None:
        set_meta("installed_at", str(int(time.time())))
    _load_settings()


# ─── настройки (кэш в памяти) ───
_settings: dict = {}


def _load_settings():
    _settings.clear()
    _settings.update(DEFAULTS)
    for k, v in q("SELECT key, value FROM settings WHERE key NOT LIKE 'meta:%'"):
        try:
            _settings[k] = json.loads(v)
        except Exception:
            pass


def setting(key):
    return _settings.get(key, DEFAULTS.get(key))


def set_setting(key, value):
    _settings[key] = value
    exe("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)))


def get_meta(key):
    r = one("SELECT value FROM settings WHERE key = ?", (f"meta:{key}",))
    return r[0] if r else None


def set_meta(key, value):
    exe("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"meta:{key}", str(value)))


def log(admin_id, action, details=""):
    exe("INSERT INTO admin_log (admin_id, action, details, at) VALUES (?, ?, ?, ?)",
        (admin_id, action, str(details)[:500], int(time.time())))


# ─── чаты ───
def tracked_chats() -> list[int]:
    return [r[0] for r in q("SELECT chat_id FROM chats")]


def is_tracked(chat_id) -> bool:
    return chat_id in _tracked_cache()


_TRACKED = {"ids": None}


def _tracked_cache():
    if _TRACKED["ids"] is None:
        _TRACKED["ids"] = set(tracked_chats())
    return _TRACKED["ids"]


def track(chat_id, title, by):
    exe("INSERT INTO chats (chat_id, title, added_by, added_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title", (chat_id, title, by, int(time.time())))
    if get_meta("tracking_since") is None:
        set_meta("tracking_since", str(int(time.time())))
    _TRACKED["ids"] = None


def untrack(chat_id) -> bool:
    n = exe("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
    _TRACKED["ids"] = None
    return n > 0


# ─── исключённые из топа ───
_EXCL = {"ids": None}


def excluded_ids() -> set:
    if _EXCL["ids"] is None:
        _EXCL["ids"] = {r[0] for r in q("SELECT user_id FROM excluded")}
    return _EXCL["ids"]


def exclude(uid, reason, by):
    exe("INSERT INTO excluded (user_id, reason, by_id, at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason", (uid, reason, by, int(time.time())))
    _EXCL["ids"] = None


def include(uid) -> bool:
    n = exe("DELETE FROM excluded WHERE user_id = ?", (uid,))
    _EXCL["ids"] = None
    return n > 0
