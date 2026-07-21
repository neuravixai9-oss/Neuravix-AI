import asyncio
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
)
from keyboards.menus import (
    admin_panel_kb, manage_admins_kb, admin_sub_type_kb, subscribed_users_kb,
    back_to_main_kb, users_list_kb, user_detail_kb, user_search_results_kb, USERS_PAGE_SIZE,
)
from config import ADMIN_ID, SUPER_OWNER_ID, SUBSCRIPTION_LIMITS, VERSION, CHANGELOG

router = Router()


class AdminState(StatesGroup):
    waiting_user_id_for_sub = State()
    waiting_sub_type = State()
    waiting_user_id_for_elite = State()
    waiting_user_id_for_admin = State()
    waiting_broadcast = State()
    waiting_user_search = State()


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

    last = CHANGELOG[0] if CHANGELOG else None
    text += f"\n{'━' * 20}\n<i>Neuravix AI v{VERSION} • {date.today().strftime('%d.%m.%Y')}</i>"
    if last:
        changes = "\n".join(f"  • {c}" for c in last["changes"][:6])
        text += f"\n\n📝 <b>Что нового в v{last['version']}:</b>\n{changes}"

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

    uname = f"@{target['username']}" if target.get("username") else "—"
    name = target.get("first_name") or "—"
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
        f"✅ Пользователь: <b>{target.get('first_name', '—')}</b> "
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
    await update_user(target_id, subscription=sub)
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
    await update_user(target_id, subscription="free")
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
    await update_user(target["telegram_id"], subscription="creator_elite")
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
        f"👑 Creator Elite выдан: <b>{target.get('first_name', raw)}</b> (<code>{target['telegram_id']}</code>)",
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
        f"✅ <b>{target.get('first_name', raw)}</b> назначен администратором.",
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
