import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _ids(raw: str):
    return [int(x) for x in (raw or "").replace(" ", "").split(",") if x.lstrip("-").isdigit()]


# Токен ManhwPatrol (от @BotFather)
BOT_TOKEN = os.getenv("PATROL_BOT_TOKEN")

# Админы ManhwPatrol — те же ID, что в ManhwCard
ADMIN_IDS = _ids(os.getenv("PATROL_ADMIN_IDS", "")) or [
    6378471773,  # те же, что ADMIN_IDS в config.py ManhwCard
]

DB_PATH = os.getenv("PATROL_DB_PATH", os.path.join(HERE, "data", "patrol.db"))


MANHWCARD_USERNAME = os.getenv("MANHWCARD_USERNAME", "@manhwcardbot")

# Часовой пояс (МСК = +3). Неделя: понедельник 00:00 — воскресенье 23:59.
TZ_OFFSET_HOURS = 3

# Значения по умолчанию. После запуска меняются командами админа
# и хранятся в базе (/settings — посмотреть).
DEFAULTS = {
    # Призы за места: [алмазы, крутки]
    "prizes": [[200, 75], [100, 30], [50, 15]],
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
