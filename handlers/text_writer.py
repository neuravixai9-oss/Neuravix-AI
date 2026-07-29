from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.db import get_or_create_user
from keyboards.menus import text_writer_kb, back_to_main_kb
from config import SUBSCRIPTION_LIMITS

router = Router()

TEXT_TYPES = {
    "article": ("📰 Статья", "Напиши тему статьи:"),
    "post": ("📱 Пост", "Напиши тему поста:"),
    "congrats": ("🎉 Поздравление", "Напиши повод (например: «день рождения Анны»):"),
    "letter": ("✉️ Письмо", "Напиши тему письма (кому и зачем):"),
    "description": ("📦 Описание товара", "Напиши название и характеристики товара:"),
    "scenario": ("🎬 Сценарий", "Напиши жанр и тему сценария:"),
    "free": ("🪶 Текст", "Напиши, что именно написать:"),
}


class TextWriterState(StatesGroup):
    choosing_type = State()
    waiting_topic = State()


@router.callback_query(F.data == "menu:text_writer")
async def open_text_writer(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TextWriterState.choosing_type)
    try:
        await callback.message.edit_text(
            "🪶 <b>Генератор текстов</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выбери тип текста:",
            reply_markup=text_writer_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🪶 <b>Генератор текстов</b>\n\nВыбери тип текста:",
            reply_markup=text_writer_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tw:"), TextWriterState.choosing_type)
async def choose_text_type(callback: CallbackQuery, state: FSMContext):
    text_type = callback.data.split(":", 1)[1]
    if text_type not in TEXT_TYPES:
        await callback.answer()
        return
    label, prompt = TEXT_TYPES[text_type]
    await state.set_state(TextWriterState.waiting_topic)
    await state.update_data(text_type=text_type, label=label)
    try:
        await callback.message.edit_text(
            f"🪶 <b>{label}</b>\n\n{prompt}",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(f"🪶 {label}\n\n{prompt}", reply_markup=back_to_main_kb())
    await callback.answer()


@router.message(TextWriterState.waiting_topic, F.text)
async def generate_text_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    text_type = data.get("text_type", "free")
    label = data.get("label", "Текст")
    await state.clear()

    topic = message.text.strip()
    if len(topic) < 3:
        await message.answer("⚠️ Тема слишком короткая. Опиши подробнее.")
        await state.set_state(TextWriterState.waiting_topic)
        return

    user = await get_or_create_user(message.from_user.id)
    sub = user.get("subscription", "free")
    model = SUBSCRIPTION_LIMITS[sub]["model"]
    max_tokens = min(SUBSCRIPTION_LIMITS[sub]["max_tokens"], 3000)

    status = await message.answer("🪶 <i>Генерирую текст…</i>", parse_mode="HTML")

    from services.ai_service import write_text
    result = await write_text(text_type, topic, model=model, max_tokens=max_tokens)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Написать ещё", callback_data="menu:text_writer")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
    ])

    try:
        await status.edit_text(
            f"🪶 <b>{label}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{result[:4000]}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        try:
            await status.edit_text(result[:4000], reply_markup=kb)
        except Exception:
            await message.answer(result[:4000], reply_markup=kb)
