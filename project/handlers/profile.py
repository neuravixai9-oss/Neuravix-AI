import html
from datetime import date, datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_or_create_user, count_chats
from keyboards.menus import back_to_main_kb
from config import SUBSCRIPTION_LIMITS

router = Router()

SUB_ICONS = {
    "free": "🌑",
    "plus": "🌗",
    "pro": "🌕",
    "ultra": "🌟",
    "creator_elite": "👑",
}


@router.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])

    msg_limit = info["messages_per_day"]
    img_limit = info.get("images_per_day", 5)
    msg_used = user.get("messages_today", 0)
    img_used = user.get("images_today", 0)

    # Сброс если другой день
    if user.get("last_reset") != str(date.today()):
        msg_used = 0
        img_used = 0

    # Прогресс-бар сообщений
    if msg_limit == -1:
        msg_bar = "♾️ Безлимитно"
    else:
        used_p = min(int(msg_used / msg_limit * 10), 10) if msg_limit else 0
        free_p = 10 - used_p
        bar = "▓" * used_p + "░" * free_p
        msg_bar = f"{bar} <b>{msg_used}/{msg_limit}</b>"

    # Прогресс-бар изображений
    if img_limit == -1:
        img_bar = "♾️ Безлимитно"
    else:
        used_p2 = min(int(img_used / img_limit * 10), 10) if img_limit else 0
        free_p2 = 10 - used_p2
        bar2 = "▓" * used_p2 + "░" * free_p2
        img_bar = f"{bar2} <b>{img_used}/{img_limit}</b>"

    # Дата регистрации
    created_raw = user.get("created_at", "")
    if created_raw:
        try:
            dt = datetime.fromisoformat(created_raw)
            joined_str = dt.strftime("%d.%m.%Y")
        except Exception:
            joined_str = "—"
    else:
        joined_str = "—"

    # Количество диалогов
    total_chats = await count_chats(callback.from_user.id)

    name = html.escape(user.get("first_name") or "Пользователь")
    uname = f"@{html.escape(user['username'])}" if user.get("username") else "Не указан"
    model_name = info.get("model", "—")
    sub_icon = SUB_ICONS.get(sub, "🌑")

    text = (
        f"👤 <b>Профиль</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 <b>{name}</b> ({uname})\n"
        f"🆔 ID: <code>{user['telegram_id']}</code>\n"
        f"📅 Зарегистрирован: <b>{joined_str}</b>\n"
        f"💬 Диалогов: <b>{total_chats}</b>\n\n"
        f"{'━' * 20}\n\n"
        f"{sub_icon} <b>Тариф:</b> {info['label']}\n"
        f"🤖 <b>Модель ИИ:</b> <code>{model_name}</code>\n"
        f"⚡ <b>Скорость:</b> {info.get('speed', '—')}\n"
        f"🌐 <b>Поиск в интернете:</b> {'✅' if info.get('can_search') else '⭕'}\n"
        f"📎 <b>Анализ файлов:</b> {'✅' if info.get('can_analyze_files') else '⭕'}\n\n"
        f"{'━' * 20}\n\n"
        f"💬 <b>Сообщения сегодня:</b>\n{msg_bar}\n\n"
        f"🖼️ <b>Изображений сегодня:</b>\n{img_bar}"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    if sub == "free":
        buttons.append([InlineKeyboardButton(text="💎 Улучшить подписку", callback_data="menu:shop")])
    buttons.append([
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main"),
    ])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML",
        )
    await callback.answer()
