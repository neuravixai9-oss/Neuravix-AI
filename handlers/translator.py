from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from keyboards.menus import back_to_main_kb

router = Router()

LANGUAGES = {
    "🇺🇸 Английский": "английский", "🇷🇺 Русский": "русский",
    "🇩🇪 Немецкий": "немецкий", "🇫🇷 Французский": "французский",
    "🇪🇸 Испанский": "испанский", "🇮🇹 Итальянский": "итальянский",
    "🇯🇵 Японский": "японский", "🇰🇷 Корейский": "корейский",
    "🇨🇳 Китайский": "китайский", "🇸🇦 Арабский": "арабский",
    "🇵🇹 Португальский": "португальский", "🇵🇱 Польский": "польский",
    "🇳🇱 Нидерландский": "нидерландский", "🇹🇷 Турецкий": "турецкий",
    "🇸🇪 Шведский": "шведский", "🇺🇦 Украинский": "украинский",
}


class TranslatorState(StatesGroup):
    choosing_lang = State()
    waiting_text = State()


def _lang_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    items = list(LANGUAGES.items())
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(text=label, callback_data=f"tr:lang:{code}")
            for label, code in items[i:i+2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "menu:translator")
async def open_translator(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TranslatorState.choosing_lang)
    try:
        await callback.message.edit_text(
            "🌐 <b>Переводчик</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выбери язык, на который нужно перевести текст:",
            reply_markup=_lang_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🌐 <b>Переводчик</b>\n\nВыбери язык перевода:",
            reply_markup=_lang_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tr:lang:"), TranslatorState.choosing_lang)
async def choose_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":", 2)[2]
    await state.set_state(TranslatorState.waiting_text)
    await state.update_data(lang=lang)
    label = next((k for k, v in LANGUAGES.items() if v == lang), lang.capitalize())
    try:
        await callback.message.edit_text(
            f"🌐 <b>Перевод на {label}</b>\n\n"
            "Напиши или перешли текст, который нужно перевести:",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"Напиши текст для перевода на {label}:",
            reply_markup=back_to_main_kb(),
        )
    await callback.answer()


@router.message(TranslatorState.waiting_text, F.text)
async def translate_text_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "английский")
    await state.clear()

    text = message.text.strip()
    if not text or len(text) < 2:
        await message.answer("⚠️ Текст слишком короткий.")
        return

    from services.ai_service import detect_language
    status = await message.answer("🌐 <i>Переводю…</i>", parse_mode="HTML")

    from services.ai_service import translate_text
    result = await translate_text(text[:3000], lang)
    src_lang = await detect_language(text[:200])

    label = next((k for k, v in LANGUAGES.items() if v == lang), lang.capitalize())

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перевести ещё", callback_data="menu:translator")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
    ])

    try:
        await status.edit_text(
            f"🌐 <b>Перевод на {label}</b>\n"
            f"<i>Исходный язык: {src_lang}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{result[:3800]}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(result[:4000], reply_markup=kb)
