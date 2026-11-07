"""
🎴 МОСТ В ManhwCard

ManhwPatrol начисляет награды прямо в базу ManhwCard (таблица users:
diamond и attempts). Каждая выплата записывается в таблицу patrol_payouts
в той же транзакции — поэтому награда не может прийти дважды, даже если
бот перезапустится посреди выплаты.

Если ManhwCard использует admin_log (новая админ-панель) — выплата
появится и там, в /adminlog.
"""
import logging
import os
import sqlite3
import time

from config import MANHWCARD_BOT_TOKEN, MANHWCARD_DB_PATH


def available() -> bool:
    return os.path.exists(MANHWCARD_DB_PATH)


def _connect():
    if not available():
        raise FileNotFoundError(f"База ManhwCard не найдена: {MANHWCARD_DB_PATH}")
    return sqlite3.connect(MANHWCARD_DB_PATH, timeout=15)


def user_exists(uid: int) -> bool:
    try:
        c = _connect()
        try:
            return c.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is not None
        finally:
            c.close()
    except Exception:
        return False


def is_banned(uid: int) -> bool:
    """Забанен ли игрок в ManhwCard (таблица user_bans из админ-панели)."""
    try:
        c = _connect()
        try:
            r = c.execute("SELECT 1 FROM user_bans WHERE user_id = ? AND (until IS NULL OR until > ?)",
                          (uid, int(time.time()))).fetchone()
            return r is not None
        finally:
            c.close()
    except Exception:
        return False


def nicknames(uids) -> dict:
    """{uid: ник в ManhwCard} — для красивых топов."""
    uids = list(uids)
    if not uids or not available():
        return {}
    try:
        c = _connect()
        try:
            ph = ",".join("?" * len(uids))
            rows = c.execute(f"SELECT id, nickname FROM users WHERE id IN ({ph})", tuple(uids)).fetchall()
            return {u: n for u, n in rows if n}
        finally:
            c.close()
    except Exception:
        return {}


def credit(reward_key: str, uid: int, diamonds: int, attempts: int, note: str = "") -> str:
    """Начисляет награду ровно один раз.
    → 'paid' | 'already' | 'no_user' | 'banned' | 'error:<текст>'"""
    try:
        c = _connect()
    except Exception as e:
        return f"error:{e}"
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS patrol_payouts (
            reward_key TEXT PRIMARY KEY, user_id INTEGER, diamonds INTEGER, attempts INTEGER,
            note TEXT, paid_at INTEGER)""")
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM patrol_payouts WHERE reward_key = ?", (reward_key,)).fetchone():
            c.rollback()
            return "already"
        if not c.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
            c.rollback()
            return "no_user"
        try:
            if c.execute("SELECT 1 FROM user_bans WHERE user_id = ? AND (until IS NULL OR until > ?)",
                         (uid, int(time.time()))).fetchone():
                c.rollback()
                return "banned"
        except sqlite3.OperationalError:
            pass  # таблицы банов нет — старая версия ManhwCard
        c.execute("INSERT INTO patrol_payouts (reward_key, user_id, diamonds, attempts, note, paid_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (reward_key, uid, diamonds, attempts, note, int(time.time())))
        c.execute("UPDATE users SET diamond = COALESCE(diamond, 0) + ?, attempts = COALESCE(attempts, 0) + ? "
                  "WHERE id = ?", (diamonds, attempts, uid))
        try:
            c.execute("INSERT INTO admin_log (admin_id, action, target_id, details, created_at) "
                      "VALUES (0, 'patrol_reward', ?, ?, ?)",
                      (uid, f"{note} · +{diamonds}💎 +{attempts}💳", int(time.time())))
        except sqlite3.OperationalError:
            pass
        c.commit()
        return "paid"
    except Exception as e:
        logging.exception("ManhwCard credit")
        try:
            c.rollback()
        except Exception:
            pass
        return f"error:{e}"
    finally:
        c.close()


# ─── уведомления от имени ManhwCard ───
_mc_bot = {"bot": None}


def mc_bot():
    if not MANHWCARD_BOT_TOKEN:
        return None
    if _mc_bot["bot"] is None:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        _mc_bot["bot"] = Bot(MANHWCARD_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    return _mc_bot["bot"]


async def notify(uid: int, text: str) -> bool:
    bot = mc_bot()
    if not bot:
        return False
    try:
        await bot.send_message(uid, text)
        return True
    except Exception as e:
        logging.info(f"ManhwCard notify {uid}: {e}")
        return False


async def close():
    if _mc_bot["bot"] is not None:
        await _mc_bot["bot"].session.close()
