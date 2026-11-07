"""
💬 СЧЁТЧИК СООБЩЕНИЙ С АНТИСПАМОМ

Засчитывается:
  • текст / подпись, в которой минимум 2 разных символа (не «ааааа», не «)))»);
  • медиа без подписи (стикер, GIF, фото, голосовое, кружок) — реже, раз в media_cooldown;
Не засчитывается:
  • команды, пересланные сообщения, сообщения от каналов и ботов;
  • повтор того же текста подряд;
  • сообщения чаще, чем раз в cooldown секунд, и сверх per_minute в минуту.

Счётчики копятся в памяти и сбрасываются в базу раз в несколько секунд.
"""
import hashlib
import re
import time
from collections import defaultdict, deque
from datetime import datetime

import db
import stats

_SPACE_RE = re.compile(r"\s+")


class Counter:
    def __init__(self):
        self.buf = defaultdict(lambda: [0, 0])   # (uid, day) → [сообщений, символов]
        self.hours = defaultdict(int)            # (day, hour) → сообщений
        self.profiles: dict[int, tuple] = {}     # uid → (first_name, username, ts)
        self.last_ts: dict[int, float] = {}
        self.last_media_ts: dict[int, float] = {}
        self.last_hash: dict[int, str] = {}
        self.minute: dict[int, deque] = defaultdict(deque)
        self.totals: dict[int, int] = {}         # всё время — для званий

    # ─── загрузка ───
    def load_totals(self):
        self.totals = {u: m for u, m in db.q(f"SELECT user_id, SUM(messages) FROM {stats.SRC} GROUP BY user_id")}

    # ─── решение: засчитать или нет ───
    def judge(self, uid: int, text: str | None, has_media: bool, ts: float | None = None):
        """→ (засчитано: bool, символов: int)"""
        ts = ts or time.time()
        text = _SPACE_RE.sub(" ", (text or "")).strip()
        cd = float(db.setting("cooldown") or 0)
        mcd = float(db.setting("media_cooldown") or 0)
        per_min = int(db.setting("per_minute") or 0)

        is_text = len(set(text.lower().replace(" ", ""))) >= 2
        if not is_text and not has_media:
            return False, 0

        if ts - self.last_ts.get(uid, 0) < cd:
            return False, 0
        if not is_text and ts - self.last_media_ts.get(uid, 0) < mcd:
            return False, 0

        if is_text:
            h = hashlib.md5(text.lower().encode()).hexdigest()
            if self.last_hash.get(uid) == h:
                return False, 0
            self.last_hash[uid] = h
        else:
            self.last_media_ts[uid] = ts

        if per_min:
            win = self.minute[uid]
            while win and ts - win[0] > 60:
                win.popleft()
            if len(win) >= per_min:
                return False, 0
            win.append(ts)

        self.last_ts[uid] = ts
        return True, len(text)

    # ─── учёт ───
    def add(self, uid: int, chars: int, first_name=None, username=None, ts: float | None = None, n: int = 1):
        """Записывает сообщение. Возвращает индекс нового звания, если игрок его только что получил."""
        ts = ts or time.time()
        dt = datetime.fromtimestamp(ts, stats.TZ)
        day = dt.date().isoformat()
        b = self.buf[(uid, day)]
        b[0] += n
        b[1] += chars
        self.hours[(day, dt.hour)] += n
        self.profiles[uid] = (first_name, username, int(ts))

        before = self.totals.get(uid, 0)
        after = before + n
        self.totals[uid] = after
        old_r, new_r = stats.rank_index(before), stats.rank_index(after)
        return new_r if new_r > old_r else None

    def flush(self):
        if not (self.buf or self.hours or self.profiles):
            return
        buf, hours, profiles = self.buf, self.hours, self.profiles
        self.buf, self.hours, self.profiles = defaultdict(lambda: [0, 0]), defaultdict(int), {}
        c = db.conn()
        c.executemany(
            "INSERT INTO msg_stats (user_id, day, messages, chars) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET messages = messages + excluded.messages, "
            "chars = chars + excluded.chars",
            [(u, d, m, ch) for (u, d), (m, ch) in buf.items()])
        c.executemany(
            "INSERT INTO hour_stats (day, hour, messages) VALUES (?, ?, ?) "
            "ON CONFLICT(day, hour) DO UPDATE SET messages = messages + excluded.messages",
            [(d, h, m) for (d, h), m in hours.items()])
        c.executemany(
            "INSERT INTO users (user_id, first_name, username, first_seen, last_active) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET first_name = COALESCE(excluded.first_name, first_name), "
            "username = excluded.username, last_active = excluded.last_active",
            [(u, f, un, ts, ts) for u, (f, un, ts) in profiles.items()])
        c.commit()


COUNTER = Counter()
