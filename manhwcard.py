"""
🎴 СВЯЗЬ С ManhwCard ЧЕРЕЗ HTTP API

ManhwPatrol и ManhwCard — два независимых бота (можно на разных хостингах).
Патруль обращается к веб-серверу ManhwCard (тот же, что обслуживает Web App):

    GET  /api/patrol/ping    — проверка связи
    POST /api/patrol/users   — ники, регистрация и баны игроков
    POST /api/patrol/credit  — начислить алмазы и крутки

Каждый запрос подписан общим ключом PATROL_API_SECRET.
Выплата идемпотентна: у каждой награды свой reward_key, и ManhwCard
записывает его в одной транзакции с начислением — повтор запроса
(например, после обрыва связи) вернёт 'already', а не выдаст второй раз.

Ники/баны кэшируются в памяти и обновляются в фоне — топы не ждут сеть.
"""
import asyncio
import logging
import time

import aiohttp

import db
from config import MANHWCARD_API_URL, PATROL_API_SECRET

CACHE_TTL = 600
BATCH = 500

_cache: dict[int, tuple] = {}     # uid → (ник | None, зарегистрирован, забанен, когда обновлено)
_state = {"ok": None, "error": "", "users": 0, "checked": 0}
_session = {"s": None}


def configured() -> bool:
    return bool(MANHWCARD_API_URL and PATROL_API_SECRET)


async def _http():
    if _session["s"] is None or _session["s"].closed:
        _session["s"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    return _session["s"]


async def _req(method: str, path: str, payload=None) -> dict:
    if not configured():
        raise RuntimeError("не заданы MANHWCARD_API_URL и PATROL_API_SECRET")
    s = await _http()
    url = MANHWCARD_API_URL.rstrip("/") + path
    async with s.request(method, url, json=payload, headers={"X-Patrol-Secret": PATROL_API_SECRET}) as r:
        if r.status != 200:
            text = (await r.text())[:200]
            raise RuntimeError(f"HTTP {r.status}: {text}")
        return await r.json()


# ─── состояние связи ───
async def ping() -> dict:
    try:
        data = await _req("GET", "/api/patrol/ping")
        _state.update(ok=True, error="", users=int(data.get("users", 0)), checked=int(time.time()))
    except Exception as e:
        _state.update(ok=False, error=str(e)[:200], checked=int(time.time()))
    return dict(_state)


def available() -> bool:
    return bool(_state["ok"])


def state() -> dict:
    return dict(_state)


# ─── кэш игроков ───
async def refresh(uids, force: bool = False):
    """Подтягивает из ManhwCard ники/регистрацию/баны. Ошибки сети не роняют бота."""
    now = time.time()
    need = [u for u in dict.fromkeys(uids) if force or now - _cache.get(u, (None, False, False, 0))[3] > CACHE_TTL]
    for i in range(0, len(need), BATCH):
        part = need[i:i + BATCH]
        try:
            data = (await _req("POST", "/api/patrol/users", {"user_ids": part})).get("users", {})
        except Exception as e:
            _state.update(ok=False, error=str(e)[:200])
            logging.info(f"ManhwCard refresh: {e}")
            return
        _state["ok"] = True
        for u in part:
            info = data.get(str(u))
            _cache[u] = ((info.get("nickname"), True, bool(info.get("banned")), now) if info
                         else (None, False, False, now))


def nicknames(uids) -> dict:
    return {u: _cache[u][0] for u in uids if u in _cache and _cache[u][0]}


def user_exists(uid: int):
    """True / False / None (ещё не знаем)."""
    return _cache[uid][1] if uid in _cache else None


def is_banned(uid: int) -> bool:
    return bool(_cache.get(uid, (None, False, False, 0))[2])


# ─── выплата ───
async def credit(reward_key: str, uid: int, diamonds: int, attempts: int, note: str = "",
                 notify_text: str | None = None) -> str:
    """→ 'paid' | 'already' | 'no_user' | 'banned' | 'error:<текст>'
    notify_text — личное сообщение победителю от имени ManhwCard (только при 'paid')."""
    try:
        data = await _req("POST", "/api/patrol/credit", {
            "reward_key": reward_key, "user_id": uid, "diamonds": diamonds, "attempts": attempts,
            "note": note, "notify_text": notify_text})
        _state["ok"] = True
        status = str(data.get("status", "error:пустой ответ"))
        if status in ("paid", "already"):
            nick = _cache.get(uid, (None,))[0]
            _cache[uid] = (nick, True, False, time.time())
        return status
    except Exception as e:
        _state.update(ok=False, error=str(e)[:200])
        return f"error:{e}"


# ─── фон ───
async def refresher():
    """Каждые 3 минуты: проверка связи + ники активных игроков."""
    while True:
        try:
            await ping()
            if available():
                week_ago = int(time.time()) - 8 * 86400
                uids = [r[0] for r in db.q("SELECT user_id FROM users WHERE last_active > ?", (week_ago,))]
                await refresh(uids)
        except Exception:
            logging.exception("ManhwCard refresher")
        await asyncio.sleep(180)


async def close():
    if _session["s"] is not None and not _session["s"].closed:
        await _session["s"].close()
