import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from database.db import (
    get_or_create_user, set_subscription, add_stars_spent,
    get_shop_products, get_shop_product,
)
from keyboards.menus import DIVIDER
from config import SUBSCRIPTION_LIMITS, SUPPORT_USERNAME, SUPER_OWNER_ID

router = Router()
logger = logging.getLogger("shop")


def _is_admin_user(telegram_id: int, user: dict) -> bool:
    return telegram_id == SUPER_OWNER_ID or bool(user.get("is_admin"))


def _shop_list_kb(products: list, is_admin: bool) -> InlineKeyboardMarkup:
    rows = []
    last_category = None
    for p in products:
        cat = p.get("category") or "Общее"
        if cat != last_category:
            # Категория как отдельная некликабельная "шапка"-разделитель —
            # noop callback, просто для визуальной группировки в самой витрине.
            rows.append([InlineKeyboardButton(text=f"— {cat} —", callback_data="shop:noop")])
            last_category = cat
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} · {p['price_stars']} ⭐",
            callback_data=f"shop:view:{p['product_key']}",
        )])
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Управление магазином", callback_data="admin:shop:list:0")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _product_detail_kb(product_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Купить", callback_data=f"buy:{product_key}")],
        [InlineKeyboardButton(text="⬅️ К списку товаров", callback_data="menu:shop")],
    ])


@router.callback_query(F.data == "shop:noop")
async def shop_noop(callback: CallbackQuery):
    await callback.answer()  # заголовок категории — просто гасим "часики" на кнопке


async def _shop_list_text(telegram_id: int) -> tuple[str, list]:
    user = await get_or_create_user(telegram_id)
    sub = user.get("subscription", "free")
    info = SUBSCRIPTION_LIMITS.get(sub, SUBSCRIPTION_LIMITS["free"])

    expiry_line = ""
    expires = user.get("subscription_expires_at")
    if sub not in ("free", "creator_elite") and expires:
        try:
            expiry_line = f" (до {datetime.fromisoformat(expires).strftime('%d.%m.%Y')})"
        except Exception:
            pass

    products = await get_shop_products(visible_only=True)

    text = (
        "🛒 <b>Магазин</b>\n"
        f"{DIVIDER}\n\n"
        f"Твой тариф: <b>{info['label']}</b>{expiry_line}\n\n"
        + ("Выбери товар ниже — открою карточку с описанием и ценой:"
           if products else "Пока здесь пусто — загляни позже 👀") +
        f"\n\n{DIVIDER}\n"
        "⚡ Оплата мгновенно через <b>Telegram Stars</b>, активация автоматическая."
        + (f" Проблемы с оплатой — пиши @{SUPPORT_USERNAME}." if SUPPORT_USERNAME else "")
    )
    return text, products


@router.callback_query(F.data == "menu:shop")
async def open_shop(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    text, products = await _shop_list_text(callback.from_user.id)
    kb = _shop_list_kb(products, _is_admin_user(callback.from_user.id, user))

    # Список товаров всегда текстовый — если пришли из карточки товара с
    # фото (другой тип сообщения), редактирование невозможно, тогда
    # отправляем новое сообщение и убираем старое.
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


def _product_card_text(p: dict) -> str:
    benefits = "\n".join(f"✅ {b}" for b in (p.get("benefits") or []))
    days = p.get("duration_days") or 0
    duration_line = f"⏳ Срок: <b>{days} дней</b>\n" if days else ""
    return (
        f"🛍 <b>{p['name']}</b>\n"
        f"{DIVIDER}\n\n"
        f"💰 <b>{p['price_stars']} ⭐</b>\n"
        f"{duration_line}"
        f"{('<i>' + p['description'] + '</i>' + chr(10) + chr(10)) if p.get('description') else ''}"
        f"{benefits}"
    )


@router.callback_query(F.data.startswith("shop:view:"))
async def view_product(callback: CallbackQuery):
    product_key = callback.data.split(":", 2)[2]
    product = await get_shop_product(product_key)
    if not product or not product.get("is_visible"):
        await callback.answer("❌ Товар больше не доступен", show_alert=True)
        return

    text = _product_card_text(product)
    kb = _product_detail_kb(product_key)
    image = product.get("image_file_id")

    try:
        if image:
            # Нельзя отредактировать текстовое сообщение в фото — отправляем
            # новую карточку товара и убираем предыдущее сообщение списка.
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer_photo(photo=image, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error("Ошибка показа карточки товара '%s': %r", product_key, e, exc_info=True)
        await callback.answer("❌ Не удалось открыть товар, попробуй ещё раз", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery, bot=None):
    product_key = callback.data.split(":", 1)[1]
    product = await get_shop_product(product_key)

    if not product or not product.get("is_visible"):
        await callback.answer("❌ Товар больше не доступен", show_alert=True)
        return

    stars = product["price_stars"]
    if stars <= 0:
        await callback.answer("❌ У этого товара не задана цена", show_alert=True)
        return

    try:
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=f"Neuravix AI — {product['name']}",
            description=(product.get("description") or product["name"])[:255],
            payload=f"product:{product_key}:{callback.from_user.id}",
            provider_token="",  # ОБЯЗАТЕЛЬНО пусто для платежей в Telegram Stars
            currency="XTR",
            prices=[LabeledPrice(label=product["name"], amount=stars)],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ Оплатить {stars}", pay=True)],
            ]),
        )
        await callback.answer()
    except Exception as e:
        logger.error("Ошибка отправки счёта Telegram Stars (%s): %r", product_key, e, exc_info=True)
        contact = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "администратору бота"
        await callback.answer(
            f"❌ Не удалось создать счёт на оплату. Попробуй ещё раз или напиши {contact}.",
            show_alert=True,
        )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Отвечать нужно в течение 10 секунд, иначе оплата у пользователя сорвётся."""
    product_key = None
    if query.invoice_payload.startswith("product:"):
        parts = query.invoice_payload.split(":")
        if len(parts) == 3:
            product_key = parts[1]

    product = await get_shop_product(product_key) if product_key else None
    if product and product.get("is_visible"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Этот товар больше недоступен — оплата отменена.")


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    """Деньги уже списаны — выполняем то, что покупал пользователь, и подтверждаем."""
    payment = message.successful_payment
    parts = (payment.invoice_payload or "").split(":")
    if len(parts) != 3 or parts[0] != "product":
        logger.warning("Неожиданный payload успешного платежа: %r", payment.invoice_payload)
        return

    product_key = parts[1]
    product = await get_shop_product(product_key)
    if not product:
        logger.error("Оплачен несуществующий товар '%s' — ничего не активировано!", product_key)
        await message.answer(
            "⚠️ Оплата прошла, но товар не найден. Напиши в поддержку — "
            f"{('@' + SUPPORT_USERNAME) if SUPPORT_USERNAME else 'администратору бота'}, "
            "мы всё исправим вручную."
        )
        return

    await add_stars_spent(message.from_user.id, payment.total_amount)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
    ])

    # Выдача покупки в зависимости от её типа. Новые типы товаров можно
    # добавлять сюда по мере необходимости — каталог (название/цена/картинка/
    # видимость/порядок) уже полностью управляется из админки без правки кода,
    # а вот ЧТО именно выдаётся при оплате — требует кода для каждого нового
    # вида выдачи (это неизбежно: код должен знать, что делать с покупкой).
    if product.get("product_type") == "subscription" and product.get("grants_subscription"):
        plan_key = product["grants_subscription"]
        days = product.get("duration_days") or None
        await set_subscription(message.from_user.id, plan_key, days)
        limits = SUBSCRIPTION_LIMITS.get(plan_key, {})
        await message.answer(
            f"✅ <b>Оплата прошла успешно!</b>\n"
            f"{DIVIDER}\n\n"
            f"Тариф <b>{limits.get('label', plan_key)}</b> активирован"
            + (f" на <b>{days}</b> дней.\n" if days else " бессрочно.\n") +
            f"Спасибо за поддержку Neuravix AI! ⭐",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Куплено: <b>{product['name']}</b>\n\n"
            f"Если ожидал(а) что-то другое — напиши в поддержку "
            f"{('@' + SUPPORT_USERNAME) if SUPPORT_USERNAME else 'администратору бота'}.",
            reply_markup=kb,
            parse_mode="HTML",
        )
