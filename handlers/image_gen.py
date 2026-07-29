import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.db import get_or_create_user, can_generate_image, increment_image_count
from keyboards.menus import back_to_main_kb
from config import SUBSCRIPTION_LIMITS

router = Router()


class ImageGenState(StatesGroup):
    waiting_prompt = State()


SECTION_TEXT = (
    "🖼️ <b>Генерация изображений</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Опиши изображение, которое хочешь создать.\n\n"
    "<b>Советы для лучшего результата:</b>\n"
    "• Описывай подробно: стиль, цвета, настроение\n"
    "• Указывай художественный стиль: <i>«в стиле аниме», «акварель», «3D-рендер»</i>\n"
    "• Добавляй детали освещения и ракурса\n\n"
    "<i>Например: «Закат над горным озером, тёплые оранжевые тона, фотореализм»</i>\n\n"
    "💬 Напиши описание картинки:"
)


@router.callback_query(F.data == "menu:image")
async def open_image_gen(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(callback.from_user.id)
    sub = user.get("subscription", "free")
    limit = SUBSCRIPTION_LIMITS[sub].get("images_per_day", 5)

    can_gen, remaining = await can_generate_image(callback.from_user.id)
    if not can_gen:
        await callback.message.edit_text(
            f"⛔ <b>Дневной лимит изображений исчерпан</b>\n\n"
            f"Ты использовал все <b>{limit}</b> генерации на сегодня.\n"
            f"🕛 Лимит обновится в полночь.\n\n"
            f"Для увеличения лимита оформи подписку в магазине 💎",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    limit_text = "безлимитно" if limit == -1 else f"осталось <b>{remaining}</b> из <b>{limit}</b>"
    text = SECTION_TEXT + f"\n\n<i>📊 Сегодня {limit_text} генераций</i>"

    await state.set_state(ImageGenState.waiting_prompt)
    try:
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=back_to_main_kb(), parse_mode="HTML")
    await callback.answer()


@router.message(ImageGenState.waiting_prompt, F.text)
async def generate_image_handler(message: Message, state: FSMContext, bot=None):
    await state.clear()

    user = await get_or_create_user(message.from_user.id)
    can_gen, remaining = await can_generate_image(message.from_user.id)
    if not can_gen:
        sub = user.get("subscription", "free")
        limit = SUBSCRIPTION_LIMITS[sub].get("images_per_day", 5)
        await message.answer(
            f"⛔ <b>Дневной лимит изображений исчерпан</b>\n\n"
            f"Использовано <b>{limit}</b> из <b>{limit}</b> генераций сегодня.\n"
            f"🕛 Лимит обновится в полночь.",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    prompt = message.text.strip()
    if len(prompt) < 3:
        await message.answer("⚠️ Описание слишком короткое. Напиши подробнее.")
        await state.set_state(ImageGenState.waiting_prompt)
        return

    if len(prompt) > 1000:
        prompt = prompt[:1000]

    status = await message.answer("🎨 <i>Генерирую изображение… Это займёт 10–30 секунд.</i>", parse_mode="HTML")

    try:
        from services.ai_service import generate_image, AIError
        img_bytes = await generate_image(prompt)

        await increment_image_count(message.from_user.id)

        sub = user.get("subscription", "free")
        limit = SUBSCRIPTION_LIMITS[sub].get("images_per_day", 5)
        can_gen2, remaining2 = await can_generate_image(message.from_user.id)
        limit_note = "безлимитно" if limit == -1 else f"осталось <b>{remaining2}</b> из <b>{limit}</b>"

        caption = (
            f"🖼️ <b>Готово!</b>\n\n"
            f"📝 <i>{html.escape(prompt[:200])}</i>\n\n"
            f"<i>📊 Сегодня {limit_note} генераций</i>"
        )

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё изображение", callback_data="menu:image")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ])

        try:
            await status.delete()
        except Exception:
            pass

        await message.answer_photo(
            photo=BufferedInputFile(img_bytes, filename="neuravix_image.png"),
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML",
        )

    except Exception as e:
        from services.ai_service import AIError
        if isinstance(e, AIError) and e.args:
            err_msg = e.args[0]
        else:
            err_msg = "❌ <b>Ошибка при генерации изображения.</b>\n\nПопробуй ещё раз или измени описание."
        try:
            await status.edit_text(
                err_msg + "\n\n<i>Нажми кнопку ниже, чтобы попробовать снова.</i>",
                reply_markup=back_to_main_kb(),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await message.answer(
                    "❌ Ошибка при генерации изображения. Попробуй ещё раз.",
                    reply_markup=back_to_main_kb(),
                )
            except Exception:
                pass
