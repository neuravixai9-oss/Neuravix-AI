import asyncio
import html
import io
import os
import zipfile
from datetime import date

from aiogram import Router, F
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.db import (
    get_or_create_user, get_all_users, get_admins, get_subscribed_users,
    get_stats, set_admin, update_user, get_user_by_username, backup_database,
    get_users_page, search_users, set_banned, get_user,
    get_shop_products, get_shop_product, create_shop_product, update_shop_product,
    delete_shop_product, move_shop_product,
)
from keyboards.menus import (
    admin_panel_kb, manage_admins_kb, admin_sub_type_kb, subscribed_users_kb,
    back_to_main_kb, users_list_kb, user_detail_kb, user_search_results_kb, USERS_PAGE_SIZE,
    DIVIDER,
)
from config import ADMIN_ID, SUPER_OWNER_ID, SUBSCRIPTION_LIMITS, VERSION

router = Router()


class AdminState(StatesGroup):
    waiting_user_id_for_sub = State()
    waiting_sub_type = State()
    waiting_user_id_for_elite = State()
    waiting_user_id_for_admin = State()
    waiting_broadcast = State()
    waiting_user_search = State()
    # Мастер добавления товара в магазин
    shop_add_name = State()
    shop_add_description = State()
    shop_add_price = State()
    shop_add_duration = State()
    shop_add_category = State()
    shop_add_image = State()
    # Редактирование одного поля существующего товара
    shop_edit_field = State()


def _is_protected(telegram_id: int, admin_ids: set) -> bool:
    """Владельца и админов нельзя заблокировать."""
    return telegram_id == SUPER_OWNER_ID or telegram_id in admin_ids


def _is_admin(user: dict) -> bool:
    return bool(user.get("is_admin") or user.get("telegram_id") == SUPER_OWNER_ID)


# ── Панель ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:panel")
async def admin_panel(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    stats = await get_stats()
    total = stats["total"]
    active_today = stats["active_today"]
    subs = stats.get("subscriptions", {})

    paying = sum(v for k, v in subs.items() if k != "free")
    free_count = subs.get("free", 0)

    text = (
        "👑 <b>Панель управления Neuravix AI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"⚡ Активны сегодня: <b>{active_today}</b>\n"
        f"🆕 Новых: сегодня <b>{stats.get('new_today', 0)}</b> / "
        f"неделя <b>{stats.get('new_week', 0)}</b> / месяц <b>{stats.get('new_month', 0)}</b>\n"
        f"💤 Заблокировали бота: <b>{stats.get('blocked_bot', 0)}</b>\n"
        f"🚫 Забанено владельцем: <b>{stats.get('banned', 0)}</b>\n"
        f"💎 Платных подписок: <b>{paying}</b>\n"
        f"🌑 Бесплатных: <b>{free_count}</b>\n"
    )

    if subs:
        text += "\n📊 <b>По тарифам:</b>\n"
        labels = {
            "free": "🌑 Free",
            "plus": "🌗 Plus",
            "pro": "🌕 Pro",
            "ultra": "🌟 Ultra",
            "creator_elite": "👑 Creator Elite",
        }
        for sub_key in ["creator_elite", "ultra", "pro", "plus", "free"]:
            cnt = subs.get(sub_key, 0)
            if cnt:
                text += f"  • {labels.get(sub_key, sub_key)}: <b>{cnt}</b>\n"

    text += f"\n{'━' * 20}\n<i>Neuravix AI v{VERSION} • {date.today().strftime('%d.%m.%Y')}</i>"

    try:
        await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def show_stats(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await admin_panel(callback)


# ── Список пользователей (интерактивный, с блокировкой) ───────────────────────

async def _admin_ids_set() -> set:
    admins = await get_admins()
    return {a["telegram_id"] for a in admins} | {SUPER_OWNER_ID}


@router.callback_query(F.data.startswith("admin:users:page:"))
async def users_page(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.clear()
    offset = int(callback.data.split(":")[3])
    users, total = await get_users_page(offset=offset, limit=USERS_PAGE_SIZE)
    admin_ids = await _admin_ids_set()

    text = (
        f"👥 <b>Пользователи</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Всего: <b>{total}</b> · Показаны {offset + 1}–{min(offset + USERS_PAGE_SIZE, total)}\n\n"
        f"👑 — владелец  🛡️ — админ  🚫 — забанен  💤 — заблокировал бота"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=users_list_kb(users, offset, total, SUPER_OWNER_ID, admin_ids),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=users_list_kb(users, offset, total, SUPER_OWNER_ID, admin_ids),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "admin:users:search")
async def users_search_start(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_user_search)
    try:
        await callback.message.edit_text(
            "🔍 <b>Поиск пользователя</b>\n\n"
            "Введи username (@user), часть имени или Telegram ID:",
            reply_markup=back_to_main_kb(), parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminState.waiting_user_search, F.text)
async def users_search_process(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    if not _is_admin(user):
        await state.clear()
        return
    await state.clear()
    query = message.text.strip()
    results = await search_users(query)
    admin_ids = await _admin_ids_set()
    text = (
        f"🔍 <b>Результаты поиска:</b> «{query}»\n\n"
        f"Найдено: <b>{len(results)}</b>"
    )
    await message.answer(
        text, reply_markup=user_search_results_kb(results, SUPER_OWNER_ID, admin_ids),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:users:view:"))
async def user_view(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":", 3)[3])
    target = await get_user(target_id)
    if not target:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    admin_ids = await _admin_ids_set()
    is_protected = _is_protected(target_id, admin_ids)

    uname = f"@{html.escape(target['username'])}" if target.get("username") else "—"
    name = html.escape(target.get("first_name") or "—")
    sub = SUBSCRIPTION_LIMITS.get(target.get("subscription", "free"), {}).get("label", "free")
    joined = (target.get("created_at") or "—")[:10]
    last_seen = (target.get("last_seen") or "")[:16].replace("T", " ") or "нет данных"
    status_bits = []
    if target_id == SUPER_OWNER_ID:
        status_bits.append("👑 Владелец")
    elif target_id in admin_ids:
        status_bits.append("🛡️ Администратор")
    if target.get("is_banned"):
        status_bits.append("🚫 Заблокирован владельцем")
    if target.get("blocked_bot"):
        status_bits.append("💤 Заблокировал бота")
    status = " · ".join(status_bits) if status_bits else "✅ Активен"

    text = (
        f"👤 <b>{name}</b> ({uname})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"💎 Тариф: <b>{sub}</b>\n"
        f"📅 Регистрация: <b>{joined}</b>\n"
        f"🕐 Последняя активность: <b>{last_seen}</b>\n"
        f"📊 Статус: {status}"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=user_detail_kb(target, is_protected), parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=user_detail_kb(target, is_protected), parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:users:block:"))
async def user_block(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":", 3)[3])
    admin_ids = await _admin_ids_set()
    if _is_protected(target_id, admin_ids):
        await callback.answer("❌ Нельзя заблокировать владельца или администратора", show_alert=True)
        return
    await set_banned(target_id, True)
    await callback.answer("🚫 Пользователь заблокирован")
    try:
        await callback.bot.send_message(
            target_id,
            "🚫 Вы были заблокированы в Neuravix AI администрацией бота.",
        )
    except Exception:
        pass
    await user_view(callback)


@router.callback_query(F.data.startswith("admin:users:unblock:"))
async def user_unblock(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":", 3)[3])
    await set_banned(target_id, False)
    await callback.answer("✅ Пользователь разблокирован")
    try:
        await callback.bot.send_message(
            target_id,
            "✅ Вы снова можете пользоваться Neuravix AI — блокировка снята.",
        )
    except Exception:
        pass
    await user_view(callback)


# ── Список пользователей (файл-экспорт) ───────────────────────────────────────

@router.callback_query(F.data == "admin:user_list")
async def send_user_list(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer("📋 Формирую список…")

    all_users = await get_all_users()
    lines = ["ID | Username | Имя | Тариф | Регистрация | Посл. активность | Статус", "─" * 70]
    for u in all_users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        name = u.get("first_name") or "—"
        sub = u.get("subscription", "free")
        joined = (u.get("created_at") or "—")[:10]
        last_seen = (u.get("last_seen") or "—")[:16]
        status = "banned" if u.get("is_banned") else ("blocked_bot" if u.get("blocked_bot") else "active")
        lines.append(f"{u['telegram_id']} | {uname} | {name} | {sub} | {joined} | {last_seen} | {status}")

    content = "\n".join(lines).encode("utf-8")
    doc = BufferedInputFile(content, filename=f"users_{date.today()}.txt")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel")]
    ])
    await callback.message.answer_document(
        document=doc,
        caption=f"📋 Пользователи Neuravix AI\nВсего: <b>{len(all_users)}</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


# ── Подписки ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:give_sub")
async def give_sub_start(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_user_id_for_sub)
    try:
        await callback.message.edit_text(
            "👤 <b>Выдать подписку</b>\n\n"
            "Введи <b>username</b> (@user) или числовой <b>ID</b> пользователя:",
            reply_markup=back_to_main_kb(), parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "👤 Введи username или ID:", reply_markup=back_to_main_kb(),
        )
    await callback.answer()


@router.message(AdminState.waiting_user_id_for_sub, F.text)
async def give_sub_get_user(message: Message, state: FSMContext):
    raw = message.text.strip()
    target = await _resolve_user(raw)
    if not target:
        await message.answer("❌ Пользователь не найден. Попробуй снова.", reply_markup=back_to_main_kb())
        await state.clear()
        return
    await state.update_data(target_id=target["telegram_id"], target_name=target.get("first_name") or raw)
    await state.set_state(AdminState.waiting_sub_type)

    cur_sub = SUBSCRIPTION_LIMITS.get(target.get("subscription", "free"), {}).get("label", "—")
    await message.answer(
        f"✅ Пользователь: <b>{html.escape(target.get('first_name') or '—')}</b> "
        f"(<code>{target['telegram_id']}</code>)\n"
        f"Текущий тариф: {cur_sub}\n\n"
        f"Выбери новый тариф:",
        reply_markup=admin_sub_type_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:set_sub:"), AdminState.waiting_sub_type)
async def give_sub_confirm(callback: CallbackQuery, state: FSMContext):
    sub = callback.data.split(":", 2)[2]
    data = await state.get_data()
    target_id = data.get("target_id")
    target_name = data.get("target_name", str(target_id))
    await state.clear()
    if not target_id or sub not in SUBSCRIPTION_LIMITS:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    await update_user(target_id, subscription=sub, subscription_expires_at="")  # ручная выдача — бессрочно
    info = SUBSCRIPTION_LIMITS[sub]

    # Уведомляем пользователя
    try:
        await callback.bot.send_message(
            target_id,
            f"🎉 <b>Твой тариф изменён!</b>\n\n"
            f"Новый тариф: {info['label']}\n"
            f"Приятного пользования Neuravix AI! 🚀",
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            f"✅ Подписка <b>{info['label']}</b> выдана\n"
            f"Пользователь: <b>{target_name}</b> (<code>{target_id}</code>)",
            reply_markup=admin_panel_kb(), parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("✅ Готово")


@router.callback_query(F.data == "admin:take_sub_list")
async def take_sub_list(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.clear()
    subs = await get_subscribed_users()
    if not subs:
        await callback.answer("Нет пользователей с платной подпиской", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "🗑️ <b>Удалить подписку</b>\n\nВыбери пользователя:",
            reply_markup=subscribed_users_kb(subs),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin:rm_sub:"))
async def remove_sub(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":", 2)[2])
    await update_user(target_id, subscription="free", subscription_expires_at="")
    await callback.answer("✅ Подписка удалена — выставлен Free")

    # Уведомляем пользователя
    try:
        await callback.bot.send_message(
            target_id,
            "ℹ️ Ваша подписка была отменена. Ваш тариф изменён на Free.\n\n"
            "По вопросам обратитесь в поддержку.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    subs = await get_subscribed_users()
    try:
        await callback.message.edit_reply_markup(reply_markup=subscribed_users_kb(subs))
    except Exception:
        pass


# ── Creator Elite ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:give_elite")
async def give_elite_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_OWNER_ID:
        await callback.answer("❌ Только создатель может выдавать Creator Elite", show_alert=True)
        return
    await state.set_state(AdminState.waiting_user_id_for_elite)
    try:
        await callback.message.edit_text(
            "👑 <b>Выдать Creator Elite</b>\n\n"
            "Введи username или ID пользователя:",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminState.waiting_user_id_for_elite, F.text)
async def give_elite_confirm(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_OWNER_ID:
        await state.clear()
        return
    raw = message.text.strip()
    target = await _resolve_user(raw)
    await state.clear()
    if not target:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb())
        return
    await update_user(target["telegram_id"], subscription="creator_elite", subscription_expires_at="")
    try:
        await message.bot.send_message(
            target["telegram_id"],
            "👑 <b>Поздравляем!</b>\n\nВам выдан тариф <b>Creator Elite</b>.\n"
            "Безлимитный доступ ко всем функциям Neuravix AI! 🚀",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await message.answer(
        f"👑 Creator Elite выдан: <b>{html.escape(target.get('first_name') or raw)}</b> (<code>{target['telegram_id']}</code>)",
        reply_markup=admin_panel_kb(), parse_mode="HTML",
    )


# ── Управление админами ───────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:manage_admins")
async def manage_admins(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if callback.from_user.id != SUPER_OWNER_ID:
        await callback.answer("❌ Только создатель", show_alert=True)
        return
    admins = await get_admins()
    try:
        await callback.message.edit_text(
            f"🛡️ <b>Управление администраторами</b>\n\n"
            f"Администраторов: <b>{len(admins)}</b>\n\n"
            "Нажми на имя для удаления из админов:",
            reply_markup=manage_admins_kb(admins),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "admin:add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_OWNER_ID:
        await callback.answer("❌ Только создатель", show_alert=True)
        return
    await state.set_state(AdminState.waiting_user_id_for_admin)
    try:
        await callback.message.edit_text(
            "👤 <b>Назначить администратора</b>\n\n"
            "Введи username или ID пользователя:",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminState.waiting_user_id_for_admin, F.text)
async def add_admin_confirm(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_OWNER_ID:
        await state.clear()
        return
    raw = message.text.strip()
    target = await _resolve_user(raw)
    await state.clear()
    if not target:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb())
        return
    await set_admin(target["telegram_id"], True)
    try:
        await message.bot.send_message(
            target["telegram_id"],
            "🛡️ <b>Вы назначены администратором Neuravix AI!</b>\n\n"
            "Теперь у вас есть доступ к панели управления.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await message.answer(
        f"✅ <b>{html.escape(target.get('first_name') or raw)}</b> назначен администратором.",
        reply_markup=admin_panel_kb(), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:rm_admin:"))
async def remove_admin(callback: CallbackQuery):
    if callback.from_user.id != SUPER_OWNER_ID:
        await callback.answer("❌ Только создатель", show_alert=True)
        return
    target_id = int(callback.data.split(":", 2)[2])
    if target_id == SUPER_OWNER_ID:
        await callback.answer("❌ Нельзя снять права у создателя", show_alert=True)
        return
    await set_admin(target_id, False)
    admins = await get_admins()
    await callback.answer("✅ Администратор удалён")
    try:
        await callback.message.edit_reply_markup(reply_markup=manage_admins_kb(admins))
    except Exception:
        pass


# ── Рассылка ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    all_users = await get_all_users()
    await state.set_state(AdminState.waiting_broadcast)
    try:
        await callback.message.edit_text(
            f"📢 <b>Рассылка</b>\n\n"
            f"Получателей: <b>{len(all_users)}</b> пользователей\n\n"
            "Напиши сообщение для отправки всем. Поддерживается HTML-форматирование.\n\n"
            "<i>Отправь сообщение прямо сейчас:</i>",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminState.waiting_broadcast, F.text)
async def broadcast_send(message: Message, state: FSMContext, bot=None):
    user = await get_or_create_user(message.from_user.id)
    if not _is_admin(user):
        await state.clear()
        return
    await state.clear()
    all_users = await get_all_users()
    recipients = [u for u in all_users if not u.get("blocked_bot")]
    text = message.text

    status = await message.answer(
        f"📢 Начинаю рассылку для <b>{len(recipients)}</b> пользователей…",
        parse_mode="HTML",
    )
    ok = 0
    fail = 0
    for u in recipients:
        try:
            await bot.send_message(u["telegram_id"], text, parse_mode="HTML")
            ok += 1
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — отмечаем, чтобы больше не слать и убрать из активных
            await update_user(u["telegram_id"], blocked_bot=1)
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # бережём лимиты Telegram при массовой рассылке

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Панель", callback_data="admin:panel")]
    ])
    try:
        await status.edit_text(
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"✔️ Доставлено: <b>{ok}</b>\n"
            f"❌ Недоставлено (заблокировали бота): <b>{fail}</b>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass


# ── Архив проекта ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:get_project")
async def send_project_archive(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if callback.from_user.id != SUPER_OWNER_ID:
        await callback.answer("❌ Только создатель", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.answer("📦 Создаю архив проекта…")

    backup_path = backup_database()

    buf = io.BytesIO()
    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    skip_dirs = {"__pycache__", ".git", "backups", "venv", ".venv", "node_modules"}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(bot_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, bot_dir)
                if fname.endswith((".py", ".txt", ".md", ".toml", ".cfg", ".ini", ".json", ".yml", ".yaml")):
                    zf.write(fpath, arcname)
        if backup_path and os.path.exists(backup_path):
            zf.write(backup_path, os.path.basename(backup_path))

    buf.seek(0)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Панель", callback_data="admin:panel")]
    ])
    await callback.message.answer_document(
        document=BufferedInputFile(buf.read(), filename=f"neuravix_v{VERSION}.zip"),
        caption=f"📦 <b>Neuravix AI v{VERSION}</b>\nАрхив кода + резервная копия БД",
        reply_markup=kb,
        parse_mode="HTML",
    )
    try:
        await status.delete()
    except Exception:
        pass


# ── Вспомогательные ───────────────────────────────────────────────────────────

async def _resolve_user(raw: str) -> dict | None:
    from database.db import get_user
    raw = raw.strip()
    if raw.startswith("@"):
        return await get_user_by_username(raw[1:])
    try:
        uid = int(raw)
        return await get_user(uid)
    except ValueError:
        return await get_user_by_username(raw)


# ── Управление магазином ──────────────────────────────────────────────────────
# Полный CRUD товаров прямо из Telegram, без единой правки кода. Новые типы
# товаров (не только подписки) можно добавлять — просто при создании выбрать
# "Не выдаёт подписку", и товар будет продаваться как есть (с автосообщением
# после оплаты); чтобы товар что-то ВЫДАВАЛ автоматически, нужно добавить
# соответствующую логику в handlers/shop.py:successful_payment — это
# единственное, что неизбежно требует кода (сам каталог полностью в БД).

SHOP_PAGE_SIZE = 8


def _shop_admin_list_kb(products: list, offset: int, total: int) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for p in products[offset:offset + SHOP_PAGE_SIZE]:
        mark = "✅" if p["is_visible"] else "🙈"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p['name']} — {p['price_stars']}⭐",
            callback_data=f"admin:shop:view:{p['product_key']}",
        )])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin:shop:list:{max(0, offset - SHOP_PAGE_SIZE)}"))
    if offset + SHOP_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="След. ➡️", callback_data=f"admin:shop:list:{offset + SHOP_PAGE_SIZE}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin:shop:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("admin:shop:list:"))
async def shop_admin_list(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.clear()
    offset = int(callback.data.split(":")[3])
    products = await get_shop_products(visible_only=False)

    text = (
        f"🛠 <b>Управление магазином</b>\n{DIVIDER}\n\n"
        f"Всего товаров: <b>{len(products)}</b>\n"
        f"✅ — видимый · 🙈 — скрытый\n\n"
        f"Нажми на товар, чтобы отредактировать."
    )
    kb = _shop_admin_list_kb(products, offset, len(products))
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


def _shop_admin_detail_kb(p: dict) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    key = p["product_key"]
    vis_text = "🙈 Скрыть" if p["is_visible"] else "✅ Показать"
    perm_text = "⏳ Сделать временным" if p["is_permanent"] else "♾️ Сделать постоянным"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"admin:shop:edit:name:{key}"),
         InlineKeyboardButton(text="✏️ Описание", callback_data=f"admin:shop:edit:description:{key}")],
        [InlineKeyboardButton(text="✏️ Цена (⭐)", callback_data=f"admin:shop:edit:price_stars:{key}"),
         InlineKeyboardButton(text="✏️ Категория", callback_data=f"admin:shop:edit:category:{key}")],
        [InlineKeyboardButton(text="🖼 Изображение", callback_data=f"admin:shop:edit:image:{key}")],
        [InlineKeyboardButton(text=vis_text, callback_data=f"admin:shop:toggle_visible:{key}"),
         InlineKeyboardButton(text=perm_text, callback_data=f"admin:shop:toggle_permanent:{key}")],
        [InlineKeyboardButton(text="⬆️ Выше", callback_data=f"admin:shop:move:up:{key}"),
         InlineKeyboardButton(text="⬇️ Ниже", callback_data=f"admin:shop:move:down:{key}")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"admin:shop:delete_confirm:{key}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:shop:list:0")],
    ])


def _shop_admin_detail_text(p: dict) -> str:
    benefits = "\n".join(f"  • {b}" for b in (p.get("benefits") or []))
    grants = f"подписка «{p['grants_subscription']}»" if p.get("grants_subscription") else "ничего автоматически (обычный товар)"
    expiry = f"\n⏰ Действует до: <b>{p['expires_at'][:10]}</b>" if (not p["is_permanent"] and p.get("expires_at")) else ""
    return (
        f"🛍 <b>{p['name']}</b>\n{DIVIDER}\n\n"
        f"🔑 Ключ: <code>{p['product_key']}</code>\n"
        f"💰 Цена: <b>{p['price_stars']} ⭐</b>\n"
        f"📁 Категория: <b>{p.get('category') or '—'}</b>\n"
        f"👁 Видимость: {'✅ Видим покупателям' if p['is_visible'] else '🙈 Скрыт'}\n"
        f"⏳ Тип: {'♾️ Постоянный' if p['is_permanent'] else '⏳ Временный'}{expiry}\n"
        f"🎁 При покупке выдаёт: {grants}\n"
        f"🖼 Изображение: {'есть' if p.get('image_file_id') else 'нет'}\n\n"
        f"<i>{p.get('description') or 'без описания'}</i>\n"
        f"{benefits}"
    )


@router.callback_query(F.data.startswith("admin:shop:view:"))
async def shop_admin_view(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    product_key = callback.data.split(":", 3)[3]
    p = await get_shop_product(product_key)
    if not p:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            _shop_admin_detail_text(p), reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            _shop_admin_detail_text(p), reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:shop:toggle_visible:"))
async def shop_toggle_visible(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    product_key = callback.data.split(":", 3)[3]
    p = await get_shop_product(product_key)
    if not p:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return
    await update_shop_product(product_key, is_visible=0 if p["is_visible"] else 1)
    await callback.answer("✅ Изменено")
    await shop_admin_view(callback)


@router.callback_query(F.data.startswith("admin:shop:toggle_permanent:"))
async def shop_toggle_permanent(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    product_key = callback.data.split(":", 3)[3]
    p = await get_shop_product(product_key)
    if not p:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return
    new_permanent = 0 if p["is_permanent"] else 1
    fields = {"is_permanent": new_permanent}
    if new_permanent:
        fields["expires_at"] = ""  # снова постоянный — срок действия снимается
    await update_shop_product(product_key, **fields)
    await callback.answer("✅ Изменено. Дату окончания можно задать через 'Описание' при необходимости.")
    await shop_admin_view(callback)


@router.callback_query(F.data.startswith("admin:shop:move:"))
async def shop_move(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    _, _, _, direction, product_key = callback.data.split(":", 4)
    moved = await move_shop_product(product_key, direction)
    await callback.answer("✅ Перемещено" if moved else "Уже крайний в списке")
    await shop_admin_view(callback)


@router.callback_query(F.data.startswith("admin:shop:delete_confirm:"))
async def shop_delete_confirm(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    product_key = callback.data.split(":", 3)[3]
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin:shop:delete:{product_key}"),
         InlineKeyboardButton(text="✖️ Отмена", callback_data=f"admin:shop:view:{product_key}")],
    ])
    try:
        await callback.message.edit_text(
            "🗑 <b>Удалить товар безвозвратно?</b>\n\nЭто не затронет уже купивших его пользователей.",
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin:shop:delete:"))
async def shop_delete(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    product_key = callback.data.split(":", 3)[3]
    await delete_shop_product(product_key)
    await callback.answer("🗑 Товар удалён")

    products = await get_shop_products(visible_only=False)
    text = (
        f"🛠 <b>Управление магазином</b>\n{DIVIDER}\n\n"
        f"Всего товаров: <b>{len(products)}</b>\n"
        f"✅ — видимый · 🙈 — скрытый\n\n"
        f"Нажми на товар, чтобы отредактировать."
    )
    kb = _shop_admin_list_kb(products, 0, len(products))
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


_SHOP_FIELD_PROMPTS = {
    "name": "✏️ Введи новое <b>название</b> товара:",
    "description": "✏️ Введи новое <b>описание</b> товара:",
    "price_stars": "✏️ Введи новую <b>цену в Telegram Stars</b> (целое число):",
    "category": "✏️ Введи новую <b>категорию</b> (например: Подписки, Бонусы):",
    "image": "🖼 Пришли новое <b>изображение</b> товара (просто отправь фото в этот чат):",
}


@router.callback_query(F.data.startswith("admin:shop:edit:"))
async def shop_edit_start(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    _, _, _, field, product_key = callback.data.split(":", 4)
    if field not in _SHOP_FIELD_PROMPTS:
        await callback.answer("❌ Неизвестное поле", show_alert=True)
        return

    await state.update_data(shop_edit_field=field, shop_edit_key=product_key)
    await state.set_state(AdminState.shop_edit_field)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖️ Отмена", callback_data=f"admin:shop:view:{product_key}")],
    ])
    try:
        await callback.message.edit_text(_SHOP_FIELD_PROMPTS[field], reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(_SHOP_FIELD_PROMPTS[field], reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(AdminState.shop_edit_field)
async def shop_edit_process(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    if not _is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    field = data.get("shop_edit_field")
    product_key = data.get("shop_edit_key")
    if not field or not product_key:
        await state.clear()
        return

    if field == "image":
        if not message.photo:
            await message.answer("⚠️ Это должно быть фото. Пришли изображение или нажми «Отмена» в сообщении выше.")
            return
        file_id = message.photo[-1].file_id
        await update_shop_product(product_key, image_file_id=file_id)
    elif field == "price_stars":
        try:
            value = int(message.text.strip())
            if value <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer("⚠️ Нужно целое положительное число. Попробуй ещё раз:")
            return
        await update_shop_product(product_key, price_stars=value)
    else:
        value = (message.text or "").strip()
        if not value:
            await message.answer("⚠️ Значение не может быть пустым. Попробуй ещё раз:")
            return
        await update_shop_product(product_key, **{field: value})

    await state.clear()
    p = await get_shop_product(product_key)
    if not p:
        await message.answer("❌ Товар не найден (возможно, был удалён).", reply_markup=admin_panel_kb())
        return
    await message.answer(
        f"✅ Обновлено!\n\n{_shop_admin_detail_text(p)}",
        reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
    )


# ── Мастер добавления товара ────────────────────────────────────────────────

@router.callback_query(F.data == "admin:shop:add")
async def shop_add_start(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id)
    if not _is_admin(user):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminState.shop_add_name)
    await state.update_data(shop_new={})

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="admin:shop:list:0")],
    ])
    try:
        await callback.message.edit_text(
            f"➕ <b>Новый товар</b> (шаг 1/5)\n{DIVIDER}\n\nВведи <b>название</b> товара:",
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"➕ <b>Новый товар</b> (шаг 1/5)\n{DIVIDER}\n\nВведи <b>название</b> товара:",
            reply_markup=kb, parse_mode="HTML",
        )
    await callback.answer()


@router.message(AdminState.shop_add_name, F.text)
async def shop_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("⚠️ Название не может быть пустым. Попробуй ещё раз:")
        return
    data = await state.get_data()
    new = data.get("shop_new", {})
    new["name"] = name
    await state.update_data(shop_new=new)
    await state.set_state(AdminState.shop_add_description)
    await message.answer(
        f"➕ <b>Новый товар</b> (шаг 2/5)\n{DIVIDER}\n\n"
        f"Введи <b>описание</b> товара (или отправь «-», чтобы оставить пустым):",
        parse_mode="HTML",
    )


@router.message(AdminState.shop_add_description, F.text)
async def shop_add_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    data = await state.get_data()
    new = data.get("shop_new", {})
    new["description"] = "" if desc == "-" else desc
    await state.update_data(shop_new=new)
    await state.set_state(AdminState.shop_add_price)
    await message.answer(
        f"➕ <b>Новый товар</b> (шаг 3/5)\n{DIVIDER}\n\n"
        f"Введи <b>цену в Telegram Stars</b> (целое число, например 150):",
        parse_mode="HTML",
    )


@router.message(AdminState.shop_add_price, F.text)
async def shop_add_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Нужно целое положительное число. Попробуй ещё раз:")
        return
    data = await state.get_data()
    new = data.get("shop_new", {})
    new["price_stars"] = price
    await state.update_data(shop_new=new)
    await state.set_state(AdminState.shop_add_category)
    await message.answer(
        f"➕ <b>Новый товар</b> (шаг 4/5)\n{DIVIDER}\n\n"
        f"Введи <b>категорию</b> (например: Подписки, Бонусы, Разное):",
        parse_mode="HTML",
    )


@router.message(AdminState.shop_add_category, F.text)
async def shop_add_category(message: Message, state: FSMContext):
    category = message.text.strip() or "Общее"
    data = await state.get_data()
    new = data.get("shop_new", {})
    new["category"] = category
    await state.update_data(shop_new=new)
    await state.set_state(AdminState.shop_add_image)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить (без изображения)", callback_data="admin:shop:add:skip_image")],
    ])
    await message.answer(
        f"➕ <b>Новый товар</b> (шаг 5/5)\n{DIVIDER}\n\n"
        f"Пришли <b>изображение</b> товара или нажми «Пропустить»:",
        reply_markup=kb, parse_mode="HTML",
    )


async def _finish_shop_add(state: FSMContext, image_file_id: str = "") -> dict:
    """Создаёт товар в БД из накопленных данных мастера и возвращает его."""
    import re
    import uuid as _uuid
    data = await state.get_data()
    new = data.get("shop_new", {})

    slug = re.sub(r"[^a-z0-9]+", "_", new.get("name", "product").lower()).strip("_") or "product"
    product_key = f"{slug}_{_uuid.uuid4().hex[:6]}"

    products = await get_shop_products(visible_only=False)
    max_order = max((p["display_order"] for p in products), default=0)

    await create_shop_product(
        product_key,
        product_type="custom",
        grants_subscription="",
        name=new.get("name", "Товар"),
        description=new.get("description", ""),
        benefits="[]",
        price_stars=new.get("price_stars", 1),
        duration_days=0,
        image_file_id=image_file_id,
        category=new.get("category", "Общее"),
        is_visible=1,
        is_permanent=1,
        expires_at="",
        display_order=max_order + 10,
    )
    await state.clear()
    return await get_shop_product(product_key)


@router.callback_query(F.data == "admin:shop:add:skip_image", AdminState.shop_add_image)
async def shop_add_skip_image(callback: CallbackQuery, state: FSMContext):
    p = await _finish_shop_add(state)
    await callback.answer("✅ Товар создан!")
    try:
        await callback.message.edit_text(
            f"✅ <b>Товар создан!</b>\n\n{_shop_admin_detail_text(p)}\n\n"
            f"💡 По умолчанию товар не выдаёт подписку автоматически — он "
            f"продаётся как обычный товар. Если это подписка, обратись за "
            f"доработкой логики выдачи.",
            reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"✅ <b>Товар создан!</b>\n\n{_shop_admin_detail_text(p)}",
            reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
        )


@router.message(AdminState.shop_add_image, F.photo)
async def shop_add_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    p = await _finish_shop_add(state, image_file_id=file_id)
    await message.answer(
        f"✅ <b>Товар создан!</b>\n\n{_shop_admin_detail_text(p)}",
        reply_markup=_shop_admin_detail_kb(p), parse_mode="HTML",
    )


@router.message(AdminState.shop_add_image)
async def shop_add_image_wrong_type(message: Message, state: FSMContext):
    await message.answer("⚠️ Пришли именно фото, либо нажми «Пропустить» в сообщении выше.")
