"""
Neuravix AI — главный файл запуска бота.
"""
import asyncio
import logging
import sys
import os

# Добавляем директорию бота в путь Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Локально подхватываем .env, если он есть и установлен python-dotenv.
# На Railway переменные окружения задаются в настройках проекта — .env там не нужен.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

from config import BOT_TOKEN, SUPER_OWNER_ID, GAME_INVITE_TTL_MINUTES, validate_env
from database.db import init_db

# Роутеры
from handlers.start import router as start_router
from handlers.ai_chat import router as ai_chat_router
from handlers.image_gen import router as image_gen_router
from handlers.translator import router as translator_router
from handlers.text_writer import router as text_writer_router
from handlers.profile import router as profile_router
from handlers.shop import router as shop_router
from handlers.settings_handler import router as settings_router
from handlers.help_handler import router as help_router
from handlers.admin import router as admin_router
from handlers.games.menu import router as games_menu_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def cleanup_expired_invites(bot: Bot):
    """Периодически удаляет просроченные приглашения в игры."""
    from datetime import datetime, timedelta
    from database.db import get_waiting_sessions_older_than, delete_game_session

    while True:
        try:
            cutoff = (datetime.now() - timedelta(minutes=GAME_INVITE_TTL_MINUTES)).isoformat()
            expired = await get_waiting_sessions_older_than(cutoff)
            for session in expired:
                try:
                    await bot.send_message(
                        session["player1_id"],
                        f"⏰ Приглашение на игру <b>{session['game_type']}</b> истекло — никто не присоединился.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                await delete_game_session(session["game_id"])
        except Exception as e:
            logger.warning(f"Ошибка очистки инвайтов: {e}")
        await asyncio.sleep(60)


async def main():
    critical, warnings = validate_env()

    if critical:
        logger.error("❌ Бот не может запуститься — не хватает обязательных переменных окружения:")
        for msg in critical:
            logger.error(f"   • {msg}")
        logger.error(
            "Задай недостающие переменные окружения (в Railway: Project → Variables) "
            "и перезапусти бота."
        )
        sys.exit(1)

    for msg in warnings:
        logger.warning(f"⚠️ {msg}")

    logger.info("🚀 Neuravix AI запускается…")
    await init_db()
    logger.info("✅ База данных инициализирована")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Сохраняем bot id для движка игр
    import handlers.games.engine as engine_mod
    me = await bot.get_me()
    engine_mod.BOT_ID = 0  # player2_id=0 означает бот
    logger.info(f"🤖 Бот: @{me.username} (ID: {me.id})")

    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем роутеры в правильном порядке
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(ai_chat_router)
    dp.include_router(image_gen_router)
    dp.include_router(translator_router)
    dp.include_router(text_writer_router)
    dp.include_router(profile_router)
    dp.include_router(shop_router)
    dp.include_router(settings_router)
    dp.include_router(help_router)
    dp.include_router(games_menu_router)

    # Обработчик текстовых сообщений в игре "Угадай число"
    from handlers.games.guess import pending_guess
    from handlers.games.engine import process_move
    from database.db import get_game_session as _get_game_session_db
    from aiogram import F
    from aiogram.types import Message

    def _is_pending_guess_input(message: Message) -> bool:
        """
        ВАЖНО: этот фильтр должен совпадать ТОЛЬКО с сообщениями пользователей,
        реально ожидающих ввода числа в игре "Угадай число". Раньше фильтр был
        'F.text & ~F.text.startswith("/")' — то есть ЛЮБОЕ текстовое сообщение
        не-команда, включая обычный чат с нейросетью. Поскольку этот обработчик
        зарегистрирован напрямую на dp (а не через include_router), aiogram
        проверяет его РАНЬШЕ всех подключённых роутеров (ai_chat_router и др.),
        и совпадение фильтра полностью останавливает дальнейшую передачу
        сообщения — из-за этого нейросеть не получала вообще ни одного
        сообщения. Теперь фильтр пропускает только реальных участников игры.
        """
        return (
            message.text is not None
            and not message.text.startswith("/")
            and message.from_user is not None
            and message.from_user.id in pending_guess
        )

    @dp.message(_is_pending_guess_input)
    async def fallback_guess_handler(message: Message, state):
        uid = message.from_user.id
        game_id = pending_guess.pop(uid, None)
        if game_id:
            session = await _get_game_session_db(game_id)
            if session and session["status"] == "active":
                await process_move(session, message.text.strip(), uid, bot)

    # Обработчик "start" для reaction-игры (запускает таймер)
    from aiogram.types import CallbackQuery

    @dp.callback_query(F.data.startswith("g:reaction:") & F.data.endswith(":start"))
    async def reaction_start_round(callback: CallbackQuery):
        parts = callback.data.split(":")
        game_id = parts[2]
        from database.db import update_game_session, get_game_session as _gs
        from handlers.games.reaction import schedule_reaction_round

        session = await _gs(game_id)
        if not session or session["status"] != "active":
            await callback.answer("Игра не активна", show_alert=True)
            return
        state = session["state"]
        state["phase"] = "waiting"
        await update_game_session(game_id, state=state)
        await callback.answer("▶️ Раунд начинается! Жди кнопку…")
        asyncio.create_task(schedule_reaction_round(session, bot))

    # Middleware контроля доступа: обновляет last_seen и блокирует
    # пользователей, забаненных владельцем через админ-панель.
    from aiogram import BaseMiddleware
    from typing import Callable, Any

    class AccessControlMiddleware(BaseMiddleware):
        async def __call__(self, handler: Callable, event: Any, data: dict) -> Any:
            from database.db import get_or_create_user, update_last_seen, is_user_banned

            user_obj = getattr(event, "from_user", None)
            if user_obj and not user_obj.is_bot:
                try:
                    await get_or_create_user(user_obj.id, user_obj.username, user_obj.first_name)
                    if user_obj.id != SUPER_OWNER_ID and await is_user_banned(user_obj.id):
                        if isinstance(event, CallbackQuery):
                            await event.answer("🚫 Вы заблокированы в этом боте.", show_alert=True)
                        elif isinstance(event, Message):
                            await event.answer("🚫 Вы заблокированы в этом боте.")
                        return  # дальше обработчики не вызываются
                    await update_last_seen(user_obj.id)
                except Exception as e:
                    logger.warning(f"AccessControlMiddleware: {e}")
            return await handler(event, data)

    dp.message.middleware(AccessControlMiddleware())
    dp.callback_query.middleware(AccessControlMiddleware())

    # Middleware для передачи bot в хендлеры
    from aiogram import BaseMiddleware
    from typing import Callable, Any

    class BotMiddleware(BaseMiddleware):
        def __init__(self, bot: Bot):
            self._bot = bot

        async def __call__(self, handler: Callable, event: Any, data: dict) -> Any:
            data["bot"] = self._bot
            return await handler(event, data)

    dp.message.middleware(BotMiddleware(bot))
    dp.callback_query.middleware(BotMiddleware(bot))

    # Запускаем фоновые задачи
    asyncio.create_task(cleanup_expired_invites(bot))

    logger.info("✅ Neuravix AI готов к работе!")
    logger.info(f"👑 Владелец: ID {SUPER_OWNER_ID}")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "inline_query"],
            drop_pending_updates=True,
        )
    finally:
        await bot.session.close()
        logger.info("🔴 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
