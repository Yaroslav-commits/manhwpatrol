"""
⚙️ НАСТРОЙКИ ManhwPatrol

Всё, что нужно поменять перед запуском, — в этом файле.
Любое значение можно переопределить переменной окружения (удобно на сервере).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _ids(raw: str):
    return [int(x) for x in (raw or "").replace(" ", "").split(",") if x.lstrip("-").isdigit()]


# Токен ManhwPatrol (от @BotFather)
BOT_TOKEN = os.getenv("PATROL_BOT_TOKEN", "ВСТАВЬТЕ_ТОКЕН_PATROL")

# Админы ManhwPatrol — те же ID, что в ManhwCard
ADMIN_IDS = _ids(os.getenv("PATROL_ADMIN_IDS", "")) or [
    6378471773,  # те же, что ADMIN_IDS в config.py ManhwCard
]

# Своя база ManhwPatrol (создастся сама рядом с ботом).
# На bothost лучше положить её в постоянную папку — см. README.
DB_PATH = os.getenv("PATROL_DB_PATH", os.path.join(HERE, "data", "patrol.db"))

# ─── ЧАТ ───
# Бот работает ТОЛЬКО в этом чате (и в личке). Из любых других групп
# он сразу выходит, сообщения там не считаются.
CHAT_ID = int(os.getenv("PATROL_CHAT_ID", "-1003961076337"))
CHAT_USERNAME = os.getenv("PATROL_CHAT_USERNAME", "chatmanhwcard")

# ─── ManhwCard ───
# Патруль с ManhwCard никак не связан: награды выдаёт админ вручную
# командами ManhwCard (бот присылает готовые команды для копирования).
# Юзернейм ManhwCard без @ — для кнопок и текстов.
MANHWCARD_USERNAME = os.getenv("MANHWCARD_USERNAME", "ManhwCardBot")

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
