import html
from datetime import date, datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database.db import get_or_create_user, count_chats, count_total_messages, count_found_secret_commands
from keyboards.menus import DIVIDER
from config import SUBSCRIPTION_LIMITS, SECRET_ACHIEVEMENTS, SECRET_COMMANDS_TOTAL

router = Router()

SUB_ICONS = {
    "free": "🌑",
    "plus": "🌗",
    "pro": "🌕",
    "ultra": "🌟",
    "creator_elite": "👑",
}


def _secret_progress_bar(found: int, total: int, length: int = 10) -> str:
    if not total:
        return "░" * length
    filled = max(0, min(length, round(found / total * length)))
    return "█" * filled + "░" * (length - filled)


def _secret_current_title(found: int) -> str | None:
    title = None
    for threshold, name in SECRET_ACHIEVEMENTS:
        if found >= threshold:
            title = name
    return title


def _secret_next_reward(found: int) -> int | None:
    for threshold, _ in SECRET_ACHIEVEMENTS:
        if found < threshold:
            return threshold
    return None


def _activity_level(total_messages: int) -> str:
    """Простая наглядная шкала активности по общему числу сообщений нейросети."""
    if total_messages >= 300:
        return "💎 Мастер"
    if total_messages >= 100:
        return "⚡ Эксперт"
    if total_messages >= 25:
        return "🔥 Опытный"
    if total_messages >= 5:
        return "🔹 Активный"
    return "🌱 Новичок"


def _format_datetime(raw: str | None, fmt: str) -> str:
    if not raw:
        return "—"
    try:
        return datetime.fromisoformat(raw).strftime(fmt)
    except Exception:
        return "—"


def _bar(used: int, limit: int, length: int = 10) -> str:
    if limit == -1:
        return "♾️ Безлимитно"
    used_p = min(int(used / limit * length), length) if limit else 0
    bar = "▓" * used_p + "░" * (length - used_p)
    return f"{bar} <b>{used}/{limit}</b>"


async def _profile_kb(sub: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Подробная статистика", callback_data="profile:stats")],
        [InlineKeyboardButton(text="🥚 Секретные команды", callback_data="profile:secrets")],
    ]
    if sub == "free":
        buttons.append([InlineKeyboardButton(text="💎 Улучшить подписку", callback_data="menu:shop")])
    buttons.append([
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_profile_overview(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """
    Компактная карточка — то, что важно видеть сразу, без скролла:
    кто ты, какой тариф, сколько лимитов осталось сегодня. Всё остальное
    (полная статистика, секретные команды) — за отдельными кнопками, чтобы
    экран не превращался в длинную простыню текста.
    """
    user = await get_or_create_user(telegram_id)
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])

    msg_limit = info["messages_per_day"]
    img_limit = info.get("images_per_day", 5)
    msg_used = user.get("messages_today", 0)
    img_used = user.get("images_today", 0)
    if user.get("last_reset") != str(date.today()):
        msg_used = 0
        img_used = 0

    name = html.escape(user.get("first_name") or "Пользователь")
    uname = f"@{html.escape(user['username'])}" if user.get("username") else "не указан"
    sub_icon = SUB_ICONS.get(sub, "🌑")
    sub_expiry_line = ""
    expires = user.get("subscription_expires_at")
    if sub not in ("free", "creator_elite") and expires:
        sub_expiry_line = f" (до {_format_datetime(expires, '%d.%m.%Y')})"

    text = (
        f"👤 <b>{name}</b> · {uname}\n"
        f"{DIVIDER}\n\n"
        f"🆔 <code>{user['telegram_id']}</code>\n"
        f"{sub_icon} Тариф: <b>{info['label']}</b>{sub_expiry_line}\n\n"
        f"💬 <b>Сообщения сегодня</b>\n{_bar(msg_used, msg_limit)}\n\n"
        f"🖼️ <b>Изображения сегодня</b>\n{_bar(img_used, img_limit)}"
    )
    return text, await _profile_kb(sub)


@router.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery):
    text, kb = await _render_profile_overview(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:stats")
async def show_profile_stats(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])

    joined_str = _format_datetime(user.get("created_at"), "%d.%m.%Y")
    last_seen_str = _format_datetime(user.get("last_seen"), "%d.%m.%Y в %H:%M")
    total_chats = await count_chats(callback.from_user.id)
    total_messages = await count_total_messages(callback.from_user.id)
    total_images = user.get("total_images", 0) or 0
    total_files = user.get("total_files", 0) or 0
    stars_spent = user.get("stars_spent", 0) or 0
    activity = _activity_level(total_messages)
    model_name = info.get("model", "—")

    text = (
        f"📊 <b>Подробная статистика</b>\n"
        f"{DIVIDER}\n\n"
        f"📅 Регистрация: <b>{joined_str}</b>\n"
        f"🕒 Последняя активность: <b>{last_seen_str}</b>\n"
        f"📈 Уровень активности: <b>{activity}</b>\n\n"
        f"{DIVIDER}\n\n"
        f"💬 Сообщений всего: <b>{total_messages}</b>\n"
        f"💭 Диалогов: <b>{total_chats}</b>\n"
        f"🖼 Изображений сгенерировано: <b>{total_images}</b>\n"
        f"📂 Файлов создано: <b>{total_files}</b>\n"
        f"⭐ Telegram Stars потрачено: <b>{stars_spent}</b>\n\n"
        f"{DIVIDER}\n\n"
        f"🧠 Модель Gemini: <code>{model_name}</code>\n"
        f"⚡ Скорость: {info.get('speed', '—')}\n"
        f"🌐 Поиск в интернете: {'✅' if info.get('can_search') else '⭕'}\n"
        f"📎 Анализ файлов: {'✅' if info.get('can_analyze_files') else '⭕'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К профилю", callback_data="menu:profile")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:secrets")
async def show_profile_secrets(callback: CallbackQuery):
    secrets_found = await count_found_secret_commands(callback.from_user.id)
    secret_bar = _secret_progress_bar(secrets_found, SECRET_COMMANDS_TOTAL)
    secret_title = _secret_current_title(secrets_found)
    secret_next = _secret_next_reward(secrets_found)

    text = (
        f"🥚 <b>Секретные команды</b>{' — ' + secret_title if secret_title else ''}\n"
        f"{DIVIDER}\n\n"
        f"{secret_bar}\n"
        f"Найдено:\n<b>{secrets_found} / {SECRET_COMMANDS_TOTAL}</b>\n\n"
        + (f"Следующая награда:\n<b>{secret_next} команд</b>\n\n" if secret_next else "Все команды найдены! 👑\n\n")
        + "<i>Секреты бота спрятаны по всему боту — попробуй разные команды 🕵️</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К профилю", callback_data="menu:profile")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
