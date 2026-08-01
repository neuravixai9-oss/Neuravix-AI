from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_or_create_user, update_user, clear_all_chats
from keyboards.menus import (
    settings_kb, settings_clear_confirm_kb, settings_language_kb,
    settings_style_kb, settings_model_kb, settings_reset_confirm_kb, DIVIDER,
)
from config import LANGUAGES, RESPONSE_STYLES

router = Router()


async def _settings_text_and_kb(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    ai_on = bool(user.get("ai_enabled", 1))
    language = user.get("language") or "ru"
    style = user.get("response_style") or "default"
    model_pref = user.get("model_preference") or "auto"
    text = (
        "⚙️ <b>Настройки</b>\n"
        f"{DIVIDER}\n\n"
        "Настрой бота под себя — язык, стиль общения, модель и хранение "
        "истории. Нажми на пункт, чтобы изменить:"
    )
    return text, settings_kb(ai_on, language, style, model_pref)


@router.callback_query(F.data == "menu:settings")
async def open_settings(callback: CallbackQuery):
    text, kb = await _settings_text_and_kb(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings:toggle_ai")
async def toggle_ai(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    new_val = 0 if user.get("ai_enabled", 1) else 1
    await update_user(callback.from_user.id, ai_enabled=new_val)
    status = "включена ✅" if new_val else "отключена ⭕"
    _, kb = await _settings_text_and_kb(callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer(f"✨ Нейросеть {status}")


# ── Язык ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:language")
async def open_language(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    current = user.get("language") or "ru"
    try:
        await callback.message.edit_text(
            "🌍 <b>Язык ответов нейросети</b>\n"
            f"{DIVIDER}\n\n"
            "Меню бота остаётся русским, но нейросеть будет стараться "
            "отвечать тебе на выбранном языке:",
            reply_markup=settings_language_kb(current),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("settings:language:"))
async def set_language(callback: CallbackQuery):
    code = callback.data.split(":", 2)[2]
    if code not in LANGUAGES:
        await callback.answer("❌ Неизвестный язык", show_alert=True)
        return
    await update_user(callback.from_user.id, language=code)
    try:
        await callback.message.edit_reply_markup(reply_markup=settings_language_kb(code))
    except Exception:
        pass
    await callback.answer(f"🌍 Язык изменён: {LANGUAGES[code]['label']}")


# ── Стиль ответов ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:style")
async def open_style(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    current = user.get("response_style") or "default"
    try:
        await callback.message.edit_text(
            "🎨 <b>Стиль ответов</b>\n"
            f"{DIVIDER}\n\n"
            "Выбери, в каком стиле нейросеть должна тебе отвечать:",
            reply_markup=settings_style_kb(current),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("settings:style:"))
async def set_style(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if key not in RESPONSE_STYLES:
        await callback.answer("❌ Неизвестный стиль", show_alert=True)
        return
    await update_user(callback.from_user.id, response_style=key)
    try:
        await callback.message.edit_reply_markup(reply_markup=settings_style_kb(key))
    except Exception:
        pass
    await callback.answer(f"🎨 Стиль изменён: {RESPONSE_STYLES[key]['label']}")


# ── Приоритет модели ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:model")
async def open_model(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    current = user.get("model_preference") or "auto"
    try:
        await callback.message.edit_text(
            "🧠 <b>Модель Gemini</b>\n"
            f"{DIVIDER}\n\n"
            "🎯 <b>Авто</b> — модель выбирается по твоему тарифу (лучшее качество, доступное тебе).\n"
            "⚡ <b>Всегда быстрая</b> — облегчённая модель для мгновенных, но более простых ответов.",
            reply_markup=settings_model_kb(current),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("settings:model:"))
async def set_model_pref(callback: CallbackQuery):
    pref = callback.data.split(":", 2)[2]
    if pref not in ("auto", "fast"):
        await callback.answer("❌ Неизвестный режим", show_alert=True)
        return
    await update_user(callback.from_user.id, model_preference=pref)
    try:
        await callback.message.edit_reply_markup(reply_markup=settings_model_kb(pref))
    except Exception:
        pass
    label = "⚡ Всегда быстрая" if pref == "fast" else "🎯 Авто (по тарифу)"
    await callback.answer(f"🧠 Модель: {label}")


# ── Очистка истории ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:clear_history_confirm")
async def clear_history_confirm(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "🧹 <b>Удалить все диалоги?</b>\n\n"
            "Это действие нельзя отменить — все твои чаты с нейросетью будут удалены навсегда. "
            "Подписка, статистика и настройки при этом сохранятся.",
            reply_markup=settings_clear_confirm_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "settings:clear_history")
async def clear_history(callback: CallbackQuery):
    await clear_all_chats(callback.from_user.id)
    text, kb = await _settings_text_and_kb(callback.from_user.id)
    try:
        await callback.message.edit_text(
            f"✅ <b>Все диалоги удалены.</b>\n\n{text}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("✅ Диалоги удалены")


# ── Сброс настроек ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:reset_confirm")
async def reset_confirm(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "♻️ <b>Сбросить настройки?</b>\n\n"
            "Язык, стиль ответов и приоритет модели вернутся к значениям по "
            "умолчанию. Диалоги, подписка и статистика профиля <b>не тронуты</b>.",
            reply_markup=settings_reset_confirm_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "settings:reset")
async def reset_settings(callback: CallbackQuery):
    await update_user(
        callback.from_user.id,
        ai_enabled=1,
        language="ru",
        response_style="default",
        model_preference="auto",
    )
    text, kb = await _settings_text_and_kb(callback.from_user.id)
    try:
        await callback.message.edit_text(
            f"✅ <b>Настройки сброшены.</b>\n\n{text}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("♻️ Настройки сброшены")
