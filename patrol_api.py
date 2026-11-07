"""
🚓 API для ManhwPatrol (отдельного бота-патруля активности чата)

ManhwPatrol живёт на другом хостинге/в другом контейнере и не видит базу
ManhwCard, поэтому награды он выдаёт через эти маршруты:

    GET  /api/patrol/ping     — проверка связи
    POST /api/patrol/users    — ники/регистрация/баны игроков (для топов)
    POST /api/patrol/credit   — начислить алмазы и крутки (ровно один раз)

Защита: секретный ключ в заголовке X-Patrol-Secret. Ключ задаётся
переменной окружения PATROL_API_SECRET — одинаковой у ManhwCard и ManhwPatrol.
Пока переменная не задана, API выключен (отвечает 503).

Подключение в main.py (рядом с register_workshop_api):
    from patrol_api import register_patrol_api
    register_patrol_api(app, lambda: BOT_INSTANCE)
"""
import asyncio
import hmac
import logging
import os
import sqlite3
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from config import DB_PATH

PATROL_API_SECRET = os.getenv("PATROL_API_SECRET", "")
MAX_DIAMONDS = 100_000      # предохранитель: больше за одну выплату нельзя
MAX_ATTEMPTS = 10_000
MAX_USERS_PER_CALL = 500


class CreditReq(BaseModel):
    reward_key: str
    user_id: int
    diamonds: int = 0
    attempts: int = 0
    note: str = ""
    notify_text: str | None = None


class UsersReq(BaseModel):
    user_ids: list[int]


def _check(secret: str | None):
    if not PATROL_API_SECRET:
        raise HTTPException(status_code=503, detail="Patrol API выключен: не задан PATROL_API_SECRET")
    if not secret or not hmac.compare_digest(secret, PATROL_API_SECRET):
        raise HTTPException(status_code=403, detail="Неверный ключ")


def _connect():
    return sqlite3.connect(DB_PATH, timeout=15)


def credit_sync(reward_key: str, uid: int, diamonds: int, attempts: int, note: str = "") -> str:
    """Начисляет награду ровно один раз.
    → 'paid' | 'already' | 'no_user' | 'banned'"""
    c = _connect()
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
            pass
        c.execute("INSERT INTO patrol_payouts (reward_key, user_id, diamonds, attempts, note, paid_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (reward_key, uid, diamonds, attempts, note[:200], int(time.time())))
        c.execute("UPDATE users SET diamond = COALESCE(diamond, 0) + ?, attempts = COALESCE(attempts, 0) + ? "
                  "WHERE id = ?", (diamonds, attempts, uid))
        try:
            c.execute("INSERT INTO admin_log (admin_id, action, target_id, details, created_at) "
                      "VALUES (0, 'patrol_reward', ?, ?, ?)",
                      (uid, f"{note[:150]} · +{diamonds}💎 +{attempts}💳", int(time.time())))
        except sqlite3.OperationalError:
            pass
        c.commit()
        return "paid"
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def users_sync(uids: list[int]) -> dict:
    uids = list(dict.fromkeys(uids))[:MAX_USERS_PER_CALL]
    if not uids:
        return {}
    c = _connect()
    try:
        ph = ",".join("?" * len(uids))
        rows = c.execute(f"SELECT id, nickname FROM users WHERE id IN ({ph})", tuple(uids)).fetchall()
        banned = set()
        try:
            banned = {r[0] for r in c.execute(
                f"SELECT user_id FROM user_bans WHERE user_id IN ({ph}) AND (until IS NULL OR until > ?)",
                tuple(uids) + (int(time.time()),)).fetchall()}
        except sqlite3.OperationalError:
            pass
        return {str(u): {"nickname": n, "banned": u in banned} for u, n in rows}
    finally:
        c.close()


def register_patrol_api(app: FastAPI, get_bot):
    @app.get("/api/patrol/ping")
    async def patrol_ping(x_patrol_secret: str | None = Header(default=None)):
        _check(x_patrol_secret)

        def _count():
            c = _connect()
            try:
                return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                c.close()
        return {"ok": True, "users": await asyncio.to_thread(_count), "time": int(time.time())}

    @app.post("/api/patrol/users")
    async def patrol_users(req: UsersReq, x_patrol_secret: str | None = Header(default=None)):
        _check(x_patrol_secret)
        return {"users": await asyncio.to_thread(users_sync, req.user_ids)}

    @app.post("/api/patrol/credit")
    async def patrol_credit(req: CreditReq, x_patrol_secret: str | None = Header(default=None)):
        _check(x_patrol_secret)
        if not (0 <= req.diamonds <= MAX_DIAMONDS and 0 <= req.attempts <= MAX_ATTEMPTS):
            raise HTTPException(status_code=400, detail="Слишком большая награда")
        if not req.reward_key or len(req.reward_key) > 120:
            raise HTTPException(status_code=400, detail="Плохой reward_key")
        status = await asyncio.to_thread(credit_sync, req.reward_key, req.user_id,
                                         req.diamonds, req.attempts, req.note)
        notified = False
        if status == "paid" and req.notify_text:
            bot = get_bot()
            if bot is not None:
                try:
                    await bot.send_message(req.user_id, req.notify_text[:4000], parse_mode="HTML")
                    notified = True
                except Exception as e:
                    logging.info(f"patrol notify {req.user_id}: {e}")
        return {"status": status, "notified": notified}
