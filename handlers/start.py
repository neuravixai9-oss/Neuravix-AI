from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.db import get_or_create_user
from keyboards.menus import main_menu_kb, back_to_main_kb
from config import SUPER_OWNER_ID

router = Router()


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


WELCOME_TEXT = (
    "✨ <b>Neuravix AI</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Привет, <b>{name}</b>! 👋\n\n"
    "Твой персональный ИИ-ассистент готов к работе.\n\n"
    "🤖 <b>Нейросеть</b> — отвечу на любые вопросы\n"
    "🖼️ <b>Изображения</b> — генерация по описанию\n"
    "🎮 <b>Игры</b> — 8 мини-игр с другом или ботом\n"
    "🌐 <b>Переводчик</b> — мгновенный перевод\n"
    "🪶 <b>Тексты</b> — статьи, посты, письма\n\n"
    "👇 Выбери раздел:"
)

OWNER_WELCOME_TEXT = (
    "👑 <b>Добро пожаловать, создатель!</b>\n\n"
    "Neuravix AI готов к работе.\n\n"
    "👇 Выбери раздел:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot=None):
    await state.clear()
    await get_or_create_user(
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

    if is_owner:
        text = OWNER_WELCOME_TEXT
    else:
        text = WELCOME_TEXT.format(name=html_escape(name))

    await message.answer(
        text,
        reply_markup=main_menu_kb(is_super_owner=is_owner),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await get_or_create_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name or "Пользователь",
    )
    is_owner = (callback.from_user.id == SUPER_OWNER_ID)

    if is_owner:
        text = OWNER_WELCOME_TEXT
    else:
        name = html_escape(callback.from_user.first_name or "Пользователь")
        text = (
            "🏠 <b>Главное меню</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Привет, <b>{name}</b>! Чем могу помочь?\n\n"
            "👇 Выбери раздел:"
        )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=main_menu_kb(is_super_owner=is_owner),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=main_menu_kb(is_super_owner=is_owner),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name or "Пользователь",
    )
    is_owner = (message.from_user.id == SUPER_OWNER_ID)
    if is_owner:
        text = OWNER_WELCOME_TEXT
    else:
        name = html_escape(message.from_user.first_name or "Пользователь")
        text = (
            "🏠 <b>Главное меню</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Привет, <b>{name}</b>! Чем могу помочь?\n\n"
            "👇 Выбери раздел:"
        )
    await message.answer(
        text,
        reply_markup=main_menu_kb(is_super_owner=is_owner),
        parse_mode="HTML",
    )
