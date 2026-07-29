from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from keyboards.menus import back_to_main_kb
from config import SUPPORT_USERNAME

router = Router()


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


HELP_SECTIONS = {
    "ai": (
        "🤖 <b>Нейросеть — подробнее</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Neuravix AI — универсальный ассистент. Всё работает прямо в одном "
        "чате, без отдельных кнопок и режимов — просто напиши, что нужно:\n\n"
        "• 💬 Отвечать на любые вопросы и переводить текст\n"
        "• 🪶 Писать статьи, посты, письма, сценарии\n"
        "• 📸 Анализировать и <b>редактировать</b> фото (удалить объект, заменить фон, стиль)\n"
        "• 🖼️ Генерировать новые изображения по описанию\n"
        "• 📄 Читать файлы: PDF, DOCX, XLSX, код, txt, ZIP-архивы\n"
        "• 🛠️ Находить и исправлять ошибки в коде, редактировать файлы и присылать готовый результат\n"
        "• 🌐 Искать актуальную информацию в интернете (Plus и выше)\n\n"
        "<b>Примеры запросов:</b>\n"
        "<i>«Переведи это на английский» • «Нарисуй красного дракона» • "
        "«Исправь ошибку в этом коде и пришли файл» • «Удали человека с фото» • "
        "«Создай презентацию про космос»</i>\n\n"
        "<b>Советы:</b>\n"
        "• Чем точнее запрос — тем лучше результат\n"
        "• Можно вести несколько диалогов на разные темы\n"
        "• Диалоги можно закрепить, переименовать или удалить\n"
        "• Лимиты сбрасываются каждую полночь\n\n"
        "<b>Контекст разговора:</b> сохраняются последние <b>40 сообщений</b>"
    ),
    "image": (
        "🖼️ <b>Изображения — подробнее</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Отдельной кнопки для изображений больше нет — просто попроси прямо "
        "в чате с нейросетью: «нарисуй...» или пришли фото с описанием, что "
        "изменить («убери фон», «сделай в стиле акварели» и т.д.).\n\n"
        "<b>Как написать хорошее описание для генерации:</b>\n"
        "• Укажи <b>что изображено</b>: объект, персонаж, сцена\n"
        "• Добавь <b>стиль</b>: реализм, аниме, акварель, 3D, масло\n"
        "• Опиши <b>освещение</b>: закат, студийный свет, ночь\n"
        "• Укажи <b>настроение</b>: мрачно, уютно, эпично\n\n"
        "<i>Пример: «Лиса в лесу осенью, студийное освещение, детализированный рисунок в стиле аниме»</i>\n\n"
        "<b>Редактирование фото:</b> пришли фото с подписью, что изменить — "
        "«удали человека справа», «замени фон на пляж», «сделай чёрно-белым».\n\n"
        "<b>Лимиты (генерация и редактирование вместе):</b>\n"
        "🌑 Free — 5 изображений/день\n"
        "🌗 Plus — 30 изображений/день\n"
        "🌕 Pro — 100 изображений/день\n"
        "🌟 Ultra — 200 изображений/день"
    ),
    "games": (
        "🎮 <b>Игры — подробнее</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Доступные игры:</b>\n"
        "❌ Крестики-нолики — классика 3×3\n"
        "🟡 Четыре в ряд — 6×7, умный бот\n"
        "🧠 Игра на память — 3 уровня сложности, бот запоминает карты!\n"
        "✊✋✌ Камень, ножницы, бумага — до 3 побед\n"
        "📚 Викторина — сотни вопросов, разные категории и уровни сложности\n"
        "🔢 Угадай число — 7 попыток, 1–100\n"
        "🪙 Орёл и решка — 5 раундов\n"
        "⚡ Кто быстрее — тест реакции\n\n"
        "<b>Режимы:</b>\n"
        "• 🤖 Против бота (в Викторине — «Играть одному») — сразу начинается\n"
        "• 👥 С другом — поделись ссылкой-приглашением\n\n"
        "<b>Приглашение</b> действует 5 минут"
    ),
    "subs": (
        "💎 <b>Тарифы — подробнее</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌑 <b>Free (бесплатно)</b>\n"
        "• 35 сообщений/день\n"
        "• 5 изображений/день\n"
        "• Модель: Gemini 2.0 Flash Lite\n"
        "• Анализ фото и файлов ✅\n\n"
        "🌗 <b>Plus — 299 ₽/мес</b>\n"
        "• 120 сообщений/день\n"
        "• 30 изображений/день\n"
        "• Модель: Gemini 2.0 Flash\n"
        "• Поиск в интернете ✅\n\n"
        "🌕 <b>Pro — 799 ₽/мес</b>\n"
        "• 350 сообщений/день\n"
        "• 100 изображений/день\n"
        "• Модель: Gemini 2.5 Flash\n"
        "• Поиск в интернете ✅\n\n"
        "🌟 <b>Ultra — 1499 ₽/мес</b>\n"
        "• 700 сообщений/день\n"
        "• 200 изображений/день\n"
        "• Модель: Gemini 2.5 Flash\n"
        "• Максимальная скорость ✅\n\n"
        + (f"Для оформления: @{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "Для оформления обратись к администратору бота.")
    ),
}

SECTION_TITLES = {
    "ai": "🤖 Нейросеть",
    "image": "🖼️ Изображения",
    "games": "🎮 Игры",
    "subs": "💎 Тарифы",
}


def _help_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🤖 Нейросеть", "help:ai"),       _btn("🖼️ Изображения", "help:image")],
        [_btn("🎮 Игры", "help:games"),           _btn("💎 Тарифы", "help:subs")],
        [_btn("📩 Написать в поддержку", "help:support")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


def _section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⬅️ Назад к помощи", "menu:help")],
    ])


_SUPPORT_LINE = f"💬 <b>Поддержка:</b> @{SUPPORT_USERNAME}\n" if SUPPORT_USERNAME else ""

MAIN_HELP_TEXT = (
    "❓ <b>Помощь — Neuravix AI</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Добро пожаловать! Выбери раздел, чтобы узнать подробнее:\n\n"
    "🤖 <b>Нейросеть</b> — общение, анализ файлов и фото\n"
    "🖼️ <b>Изображения</b> — как генерировать и советы\n"
    "🎮 <b>Игры</b> — список игр и режимы\n"
    "💎 <b>Тарифы</b> — сравнение планов и цены\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    f"{_SUPPORT_LINE}"
    "<i>Мы всегда на связи — пиши, если что-то не работает!</i>"
)


@router.callback_query(F.data == "menu:help")
async def open_help(callback: CallbackQuery):
    text = MAIN_HELP_TEXT
    try:
        await callback.message.edit_text(
            text, reply_markup=_help_main_kb(), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=_help_main_kb(), parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("help:"))
async def open_help_section(callback: CallbackQuery):
    section = callback.data.split(":", 1)[1]

    if section == "support":
        msg = f"Пиши нам: @{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "Администратор бота ещё не указал контакт поддержки."
        await callback.answer(msg, show_alert=True)
        return

    text = HELP_SECTIONS.get(section)
    if not text:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text, reply_markup=_section_kb(), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=_section_kb(), parse_mode="HTML"
        )
    await callback.answer()
