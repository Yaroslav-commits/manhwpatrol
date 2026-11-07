"""
⚙️ НАСТРОЙКИ ManhwPatrol

Всё, что нужно поменять перед запуском, — в этом файле.
Любое значение можно переопределить переменной окружения (удобно на сервере).
"""
import os


def _ids(raw: str):
    return [int(x) for x in (raw or "").replace(" ", "").split(",") if x.lstrip("-").isdigit()]


# Токен ManhwPatrol (от @BotFather)
BOT_TOKEN = os.getenv("PATROL_BOT_TOKEN", "ВСТАВЬТЕ_ТОКЕН_PATROL")

# Админы ManhwPatrol — те же ID, что в ManhwCard
ADMIN_IDS = _ids(os.getenv("PATROL_ADMIN_IDS", "")) or [
    123456789,  # ← замените на свои ID
]

# Своя база ManhwPatrol (создастся сама)
DB_PATH = os.getenv("PATROL_DB_PATH", "patrol.db")

# ─── СВЯЗЬ С ManhwCard ───
# Путь к базе ManhwCard (тот же файл, что DB_PATH в config.py ManhwCard).
# Оба бота должны работать на одном сервере.
MANHWCARD_DB_PATH = os.getenv("MANHWCARD_DB_PATH", "../ManhwCard/database.db")

# Токен ManhwCard — чтобы уведомление о награде пришло победителю ОТ ManhwCard.
# Можно оставить пустым — тогда о наградах будет только пост в чате.
MANHWCARD_BOT_TOKEN = os.getenv("MANHWCARD_BOT_TOKEN", "")

# Юзернейм ManhwCard без @ — для кнопок «Забрать в ManhwCard»
MANHWCARD_USERNAME = os.getenv("MANHWCARD_USERNAME", "ManhwCardBot")

# Показывать в топах игровые ники из ManhwCard (если игрок там зарегистрирован)
USE_MANHWCARD_NICKS = True

# Часовой пояс (МСК = +3). Неделя: понедельник 00:00 — воскресенье 23:59.
TZ_OFFSET_HOURS = 3

# Значения по умолчанию. После запуска меняются командами админа
# и хранятся в базе (/settings — посмотреть).
DEFAULTS = {
    # Призы за места: [алмазы, крутки]
    "prizes": [[150, 15], [100, 10], [50, 5]],
    # Минимум сообщений за неделю, чтобы претендовать на приз
    "min_messages": 100,
    # Антиспам: сообщение засчитывается не чаще, чем раз в N секунд
    "cooldown": 3,
    # Стикеры/GIF/медиа без подписи — не чаще, чем раз в N секунд
    "media_cooldown": 10,
    # Максимум засчитанных сообщений в минуту
    "per_minute": 15,
    # Переключатели (/toggle имя)
    "daily": True,       # итоги дня в 00:00
    "reminder": True,    # напоминание в воскресенье вечером
    "rankups": True,     # поздравлять с новым званием прямо в чате
    "pin": True,         # закреплять итоги недели
    "reminder_hour": 20,
}
