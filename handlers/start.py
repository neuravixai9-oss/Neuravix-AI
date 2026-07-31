from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.db import get_or_create_user
from keyboards.menus import main_menu_kb, back_to_main_kb, DIVIDER
from config import SUPER_OWNER_ID, SUBSCRIPTION_LIMITS

router = Router()

_SUB_ICONS = {
    "free": "🌑", "plus": "🌗", "pro": "🌕", "ultra": "🌟", "creator_elite": "👑",
}


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _status_line(user: dict) -> str:
    """Короткая персонализированная строка статуса — тариф и остаток лимита
    на сегодня. Делает приветствие похожим на персональную панель, а не на
    статичный текст, одинаковый для всех."""
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])
    icon = _SUB_ICONS.get(sub, "🌑")
    limit = info.get("messages_per_day", 0)
    used = user.get("messages_today", 0) or 0
    if limit == -1:
        quota = "сообщения без лимита"
    else:
        left = max(0, limit - used)
        quota = f"осталось {left} из {limit} сообщений сегодня"
    return f"{icon} <b>{info.get('label', sub)}</b> · {quota}"


def main_menu_text(name: str, is_owner: bool, user: dict | None = None) -> str:
    """
    Единственный источник текста главного меню — используется и в /start,
    и в /menu, и в кнопке «⬅️ В меню» откуда угодно. Так меню гарантированно
    выглядит одинаково независимо от того, как в него попал пользователь.
    """
    status = f"\n{_status_line(user)}\n" if user else ""

    if is_owner:
        return (
            "👑 <b>Neuravix AI</b>\n"
            f"{DIVIDER}\n\n"
            f"Добро пожаловать, создатель, <b>{html_escape(name)}</b>! 👋\n"
            f"{status}\n"
            "👇 Выбери раздел:"
        )
    return (
        "✨ <b>Neuravix AI</b>\n"
        f"{DIVIDER}\n\n"
        f"Привет, <b>{html_escape(name)}</b>! 👋\n"
        f"{status}\n"
        "Просто напиши, что нужно — сам разберусь:\n"
        "🎨 <i>«нарисуй…»</i> · 🌐 <i>«переведи…»</i> · "
        "💻 <i>«исправь код…»</i> · 📝 <i>«напиши текст…»</i>\n\n"
        "👇 Выбери раздел:"
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot=None):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name or "Пользователь",
    )

    # Обработка deep-link для игр
    args = message.text.split(" ", 1)
    if len(args) > 1 and args[1].startswith("game_"):
        room_id = args[1][5:]
        from handlers.games import handle_join_game
        await handle_join_game(message, room_id, bot=bot, state=state)
        return

    is_owner = (message.from_user.id == SUPER_OWNER_ID)
    name = message.from_user.first_name or "Пользователь"

    await message.answer(
        main_menu_text(name, is_owner, user),
        reply_markup=main_menu_kb(is_super_owner=is_owner),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name or "Пользователь",
    )
    is_owner = (callback.from_user.id == SUPER_OWNER_ID)
    name = callback.from_user.first_name or "Пользователь"
    text = main_menu_text(name, is_owner, user)

    # Меню всегда РЕДАКТИРУЕТСЯ на месте — новое сообщение отправляется только
    # если редактирование в принципе невозможно (например, исходное сообщение
    # было фото/файлом без текста, или удалено).
    try:
        await callback.message.edit_text(
            text,
            reply_markup=main_menu_kb(is_super_owner=is_owner),
            parse_mode="HTML",
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=main_menu_kb(is_super_owner=is_owner),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name or "Пользователь",
    )
    is_owner = (message.from_user.id == SUPER_OWNER_ID)
    name = message.from_user.first_name or "Пользователь"
    await message.answer(
        main_menu_text(name, is_owner, user),
        reply_markup=main_menu_kb(is_super_owner=is_owner),
        parse_mode="HTML",
    )
