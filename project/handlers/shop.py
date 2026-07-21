from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_or_create_user
from keyboards.menus import shop_kb, back_to_main_kb
from config import SUBSCRIPTION_LIMITS, SUBSCRIPTION_PRICES, SUPPORT_USERNAME

router = Router()


@router.callback_query(F.data == "menu:shop")
async def open_shop(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])

    support_line = (
        f"Для покупки обратись к администратору: @{SUPPORT_USERNAME}"
        if SUPPORT_USERNAME else
        "Для покупки обратись к администратору бота."
    )
    text = (
        "💎 <b>Магазин подписок</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Твой текущий тариф:</b> {info['label']}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌗 <b>Plus</b> — 299 ₽/мес\n"
        "• 120 сообщений в день\n"
        "• 30 изображений в день\n"
        "• Модель <code>gemini-2.0-flash</code>\n"
        "• Поиск в интернете ✅\n\n"
        "🌕 <b>Pro</b> — 799 ₽/мес\n"
        "• 350 сообщений в день\n"
        "• 100 изображений в день\n"
        "• Модель <code>gemini-2.5-flash</code>\n"
        "• Поиск в интернете ✅\n"
        "• Приоритетная скорость ✅\n\n"
        "🌟 <b>Ultra</b> — 1499 ₽/мес\n"
        "• 700 сообщений в день\n"
        "• 200 изображений в день\n"
        "• Модель <code>gemini-2.5-flash</code>\n"
        "• Поиск в интернете ✅\n"
        "• Максимальная скорость ✅\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{support_line}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=shop_kb(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=shop_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy_subscription(callback: CallbackQuery):
    plan = callback.data.split(":", 1)[1]
    info = SUBSCRIPTION_LIMITS.get(plan)
    price = SUBSCRIPTION_PRICES.get(plan, "—")

    if not info:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    contact_line = f"👤 @{SUPPORT_USERNAME}\n\n" if SUPPORT_USERNAME else "👤 у администратора бота\n\n"
    text = (
        f"💳 <b>Оформление {info['label']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Стоимость:</b> {price}\n\n"
        "Для оформления подписки напиши администратору:\n"
        f"{contact_line}"
        "Укажи в сообщении:\n"
        f"• Желаемый тариф: <b>{info['label']}</b>\n"
        f"• Свой Telegram ID: <code>{callback.from_user.id}</code>\n\n"
        "<i>После оплаты подписка будет активирована в течение нескольких минут.</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    if SUPPORT_USERNAME:
        rows.append([InlineKeyboardButton(text=f"📩 Написать @{SUPPORT_USERNAME}", url=f"https://t.me/{SUPPORT_USERNAME}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:shop")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
