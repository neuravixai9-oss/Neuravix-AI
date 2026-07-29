from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_or_create_user, update_user, clear_all_chats
from keyboards.menus import settings_kb, settings_clear_confirm_kb, back_to_main_kb

router = Router()


@router.callback_query(F.data == "menu:settings")
async def open_settings(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    ai_on = bool(user.get("ai_enabled", 1))
    try:
        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Управляй параметрами бота:",
            reply_markup=settings_kb(ai_on),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "⚙️ <b>Настройки</b>\n\nУправляй параметрами бота:",
            reply_markup=settings_kb(ai_on),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "settings:toggle_ai")
async def toggle_ai(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    new_val = 0 if user.get("ai_enabled", 1) else 1
    await update_user(callback.from_user.id, ai_enabled=new_val)
    status = "включена ✅" if new_val else "отключена ⭕"
    try:
        await callback.message.edit_reply_markup(reply_markup=settings_kb(bool(new_val)))
    except Exception:
        pass
    await callback.answer(f"✨ Нейросеть {status}")


@router.callback_query(F.data == "settings:clear_history_confirm")
async def clear_history_confirm(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "🗑️ <b>Удалить все диалоги?</b>\n\n"
            "Это действие нельзя отменить — все твои чаты с нейросетью будут удалены навсегда.",
            reply_markup=settings_clear_confirm_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "settings:clear_history")
async def clear_history(callback: CallbackQuery):
    await clear_all_chats(callback.from_user.id)
    user = await get_or_create_user(callback.from_user.id)
    ai_on = bool(user.get("ai_enabled", 1))
    try:
        await callback.message.edit_text(
            "✅ <b>Все диалоги удалены.</b>\n\n⚙️ <b>Настройки</b>",
            reply_markup=settings_kb(ai_on),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("✅ Диалоги удалены")
