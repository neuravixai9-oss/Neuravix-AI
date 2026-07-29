"""
Конфигурация Neuravix AI.

Все секреты и параметры окружения читаются ТОЛЬКО из переменных окружения —
никаких токенов, ключей или личных данных в коде нет. Для локального запуска
скопируй .env.example в .env и заполни значения (main.py сам подхватит .env,
если установлен python-dotenv; на Railway переменные задаются в настройках
проекта — Variables).
"""
import os
import pathlib

BASE_DIR = pathlib.Path(__file__).parent

# ── Bot ──────────────────────────────────────────────────────────────────────
# Поддерживаем оба имени переменной: BOT_TOKEN (основное) и TELEGRAM_BOT_TOKEN
# (старое имя, оставлено для обратной совместимости с прошлыми деплоями).
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_NAME = os.getenv("BOT_NAME", "Neuravix AI")

# ── Google AI Studio (Gemini) ─────────────────────────────────────────────────
# .strip() — защита от частой причины "тихого" отказа ИИ: лишние пробелы или
# перенос строки, случайно попавшие в переменную окружения при вставке ключа.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ── Access control ────────────────────────────────────────────────────────────
# OWNER_ID обязателен: без него никто не сможет попасть в админ-панель бота.
def _parse_owner_id(raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0

SUPER_OWNER_ID = _parse_owner_id(os.getenv("OWNER_ID", ""))
SUPER_OWNER_USERNAME = os.getenv("OWNER_USERNAME", "")   # без @, может быть пустым
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")     # без @, может быть пустым

# Backward-compat alias (используется в database/db.py)
ADMIN_ID = SUPER_OWNER_ID

# ── Version ───────────────────────────────────────────────────────────────────
# Версия отображается ТОЛЬКО в админ-панели (владельцу/админам), не пользователям.
# При каждой правке проекта версию нужно увеличивать и добавлять запись в CHANGELOG.
VERSION = "3.4.1"

CHANGELOG = [
    {
        "version": "3.4.1",
        "date": "2026-07-21",
        "changes": [
            "КРИТИЧЕСКИЙ ФИКС: бот не отвечал вообще ни на одно сообщение. Причина — "
            "обработчик игры 'Угадай число' был зарегистрирован напрямую на "
            "Dispatcher с фильтром 'любой текст, не команда', из-за чего aiogram "
            "перехватывал ЛЮБОЕ сообщение до того, как оно доходило до "
            "ai_chat_router, и просто ничего не делал. Теперь фильтр пропускает "
            "только пользователей в активной игре.",
            "Усилено логирование: непредвиденные ошибки (ИИ, инструменты, генерация) "
            "теперь пишутся в Railway Logs с полным traceback (exc_info=True).",
        ],
    },
    {
        "version": "3.4.0",
        "date": "2026-07-20",
        "changes": [
            "Исправлено форматирование ответов ИИ (жирный текст/код не показывались буквально тегами)",
            "GEMINI_API_KEY теперь очищается от случайных пробелов — частая причина 'молчаливого' отказа ИИ",
            "Добавлено логирование реальных ошибок Gemini на сервере (для диагностики владельцем)",
            "КНБ: кнопки после игры приведены к виду 'Играть ещё' / 'В меню'",
            "Игра с другом теперь целиком в одном сообщении — исправлена утечка лишнего сообщения при приглашении",
            "Новая админ-панель: раздел 'Пользователи' — список, поиск, блокировка/разблокировка",
            "Добавлена массовая рассылка с учётом заблокировавших бота пользователей",
            "Добавлена расширенная статистика (новые пользователи за день/неделю/месяц, последняя активность)",
            "Добавлен экспорт пользователей в файл",
            "Версия и changelog проекта убраны из всех пользовательских экранов — видны только владельцу в админ-панели",
        ],
    },
    {
        "version": "3.3.0",
        "date": "2026-07-18",
        "changes": [
            "Проект подготовлен к деплою на Railway",
            "Все секреты и токены убраны из кода — только переменные окружения",
            "Добавлена проверка обязательных переменных окружения при запуске",
            "Путь к базе данных и бэкапам теперь настраивается через переменные окружения",
            "Обновлены и вычищены зависимости в requirements.txt",
        ],
    },
    {
        "version": "3.2.0",
        "date": "2026-07-17",
        "changes": [
            "Новые игры: Камень-ножницы-бумага и Викторина с сотнями вопросов",
            "Полный редизайн Игры на память: 3 уровня сложности, умный бот",
            "Исправлены все ошибки в играх: карточки, ходы бота, зависания",
            "Удалены нестабильные игры: Шашки, Морской бой, Точки и коробочки",
            "Оптимизирована скорость и стабильность бота",
        ],
    },
    {
        "version": "3.1.0",
        "date": "2026-07-16",
        "changes": [
            "Полный редизайн интерфейса: убраны лишние кнопки после ответов нейросети",
            "Общение с ИИ теперь простое как в ChatGPT — пишешь и получаешь ответ",
            "Исправлена генерация изображений — работает стабильно",
            "Ускорена потоковая генерация ответов ИИ",
        ],
    },
]

# ── Модели Gemini по тарифам ───────────────────────────────────────────────────
SUBSCRIPTION_LIMITS = {
    "free": {
        "messages_per_day": 35,
        "images_per_day": 5,
        "model": "gemini-2.0-flash-lite",
        "max_tokens": 1500,
        "label": "🌑 Starter",
        "speed": "стандартная",
        "can_analyze_files": True,
        "can_search": False,
    },
    "plus": {
        "messages_per_day": 120,
        "images_per_day": 30,
        "model": "gemini-2.0-flash",
        "max_tokens": 4096,
        "label": "🌗 Plus",
        "speed": "высокая",
        "can_analyze_files": True,
        "can_search": True,
    },
    "pro": {
        "messages_per_day": 350,
        "images_per_day": 100,
        "model": "gemini-2.5-flash",
        "max_tokens": 8192,
        "label": "🌕 Pro",
        "speed": "очень высокая",
        "can_analyze_files": True,
        "can_search": True,
    },
    "ultra": {
        "messages_per_day": 700,
        "images_per_day": 200,
        "model": "gemini-2.5-flash",
        "max_tokens": 8192,
        "label": "🌟 Ultra",
        "speed": "максимальная",
        "can_analyze_files": True,
        "can_search": True,
    },
    "creator_elite": {
        "messages_per_day": -1,
        "images_per_day": -1,
        "model": "gemini-2.5-flash",
        "max_tokens": 8192,
        "label": "👑 Creator Elite",
        "speed": "приоритетная",
        "can_analyze_files": True,
        "can_search": True,
    },
}

SUBSCRIPTION_PRICES = {
    "plus": "299 ₽/мес",
    "pro": "799 ₽/мес",
    "ultra": "1499 ₽/мес",
}

# Резервная модель для чата
CHAT_FALLBACK_MODEL = "gemini-2.0-flash-lite"

# Модели для генерации и редактирования изображений (Nano Banana).
# Порядок — от максимального качества к более доступным (fallback,
# если модель недоступна на конкретном API-ключе/аккаунте).
# ВАЖНО: "gemini-2.5-flash-preview-05-20" (старое значение) — это ТЕКСТОВАЯ
# модель без поддержки изображений, из-за чего генерация могла тихо не работать.
IMAGE_GEN_MODELS = [
    "gemini-3-pro-image",                          # Nano Banana Pro — макс. качество
    "gemini-3.1-flash-image",                      # Nano Banana 2 — быстро и качественно
    "gemini-2.5-flash-image",                      # проверенная стабильная модель
    "gemini-2.0-flash-preview-image-generation",   # последний резерв на старых ключах
]

# Модель для утилитарных задач
UTILITY_MODEL = "gemini-2.0-flash-lite"

# ── Игры ─────────────────────────────────────────────────────────────────────
GAMES = {
    "tictactoe": {"title": "Крестики-нолики", "emoji": "❌"},
    "connect4":  {"title": "Четыре в ряд",    "emoji": "🟡"},
    "memory":    {"title": "Игра на память",   "emoji": "🧠"},
    "rps":       {"title": "Камень-ножницы-бумага", "emoji": "✊"},
    "quiz":      {"title": "Викторина",        "emoji": "📚"},
    "guess":     {"title": "Угадай число",     "emoji": "🔢"},
    "coinflip":  {"title": "Орёл и решка",     "emoji": "🪙"},
    "reaction":  {"title": "Кто быстрее",      "emoji": "⚡"},
}

GAME_INVITE_TTL_MINUTES = 5

# ── Database ──────────────────────────────────────────────────────────────────
# DB_PATH можно переопределить переменной окружения — например, чтобы указать
# на постоянный диск (Railway Volume), т.к. без него файловая система Railway
# не сохраняется между деплоями.
#
# DATABASE_URL поддерживается как алиас для совместимости с типовыми PaaS-
# конвенциями: если задан и указывает на локальный файл (например
# "sqlite:////data/neuravix.db" или просто путь к файлу), он используется как
# DB_PATH. Полноценной СУБД (Postgres/MySQL) проект сейчас не поддерживает —
# вся логика написана под aiosqlite; это осознанное ограничение текущей
# подготовки к Railway, а не забытая доработка.
def _resolve_db_path() -> str:
    explicit = os.getenv("DB_PATH")
    if explicit:
        return explicit

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("sqlite:////"):
            return "/" + database_url[len("sqlite:////"):]
        if database_url.startswith("sqlite:///"):
            return database_url[len("sqlite:///"):]
        if database_url.startswith(("postgres://", "postgresql://", "mysql://")):
            # Не поддерживается текущей версией — явно предупредим при старте,
            # но не роняем импорт конфига (main.py покажет понятное сообщение).
            os.environ["_NEURAVIX_UNSUPPORTED_DATABASE_URL"] = database_url
        else:
            return database_url

    volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if volume_path:
        return str(pathlib.Path(volume_path) / "neuravix.db")

    return str(BASE_DIR / "neuravix.db")


DB_PATH = _resolve_db_path()
BACKUP_DIR = os.getenv("BACKUP_DIR", str(BASE_DIR / "backups"))


# ── Проверка обязательных переменных окружения ─────────────────────────────────
def validate_env() -> tuple[list[str], list[str]]:
    """
    Возвращает (critical, warnings) — списки понятных сообщений.
    critical: без этого бот не может стартовать вообще (main.py завершит работу).
    warnings: бот запустится, но соответствующая функциональность не будет работать.
    """
    critical = []
    warnings = []

    if not BOT_TOKEN:
        critical.append(
            "BOT_TOKEN не задан — укажи токен бота от @BotFather "
            "в переменной окружения BOT_TOKEN (или TELEGRAM_BOT_TOKEN)."
        )

    if not SUPER_OWNER_ID:
        critical.append(
            "OWNER_ID не задан или некорректен — укажи свой числовой "
            "Telegram ID в переменной окружения OWNER_ID (например: 123456789). "
            "Без него никто не получит доступ к админ-панели."
        )

    if not GEMINI_API_KEY:
        warnings.append(
            "GEMINI_API_KEY не задан — нейросеть, генерация изображений, перевод "
            "и другие ИИ-функции работать не будут (остальной бот запустится). "
            "Укажи ключ от Google AI Studio в переменной окружения GEMINI_API_KEY."
        )

    if os.environ.get("_NEURAVIX_UNSUPPORTED_DATABASE_URL"):
        warnings.append(
            "DATABASE_URL указывает на Postgres/MySQL "
            f"({os.environ['_NEURAVIX_UNSUPPORTED_DATABASE_URL']}) — "
            "текущая версия бота работает только с SQLite, эта переменная "
            "игнорируется. Убери DATABASE_URL или укажи путь к SQLite-файлу "
            "(например sqlite:////data/neuravix.db), либо задай DB_PATH напрямую."
        )

    if not SUPER_OWNER_USERNAME:
        warnings.append(
            "OWNER_USERNAME не задан — некоторые сообщения ИИ будут использовать "
            "общую формулировку вместо упоминания владельца по имени. Не критично."
        )

    if not SUPPORT_USERNAME:
        warnings.append(
            "SUPPORT_USERNAME не задан — кнопки и тексты поддержки/оплаты подписки "
            "скроют ссылку на аккаунт поддержки. Не критично, но стоит задать."
        )

    return critical, warnings
