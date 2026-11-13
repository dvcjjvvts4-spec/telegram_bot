import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Проверь файл .env")

# Бот личный: данные о здоровье видит только владелец.
# Без этой настройки бот не стартует, чтобы случайно не оказаться открытым для всех.
_allowed = os.getenv("ALLOWED_USER_ID", "").strip()
if not _allowed.isdigit():
    raise RuntimeError(
        "Не найден ALLOWED_USER_ID. Узнай свой Telegram ID у @userinfobot "
        "и добавь в .env строку ALLOWED_USER_ID=123456789"
    )
ALLOWED_USER_ID = int(_allowed)

TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
DB_PATH = os.getenv("DB_PATH", "data/tracker.sqlite3")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_PROXY = os.getenv("GEMINI_PROXY", "") or None

PILL_REPEAT_MINUTES = 30  # пауза между повторами напоминания о таблетке
PILL_MAX_PINGS = 3  # сколько раз напомнить, прежде чем считать приём пропущенным
LOW_STOCK_DAYS = 5  # за сколько дней предупреждать, что таблетки заканчиваются


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()
