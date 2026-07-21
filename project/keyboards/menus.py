import urllib.parse
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUBSCRIPTION_LIMITS, GAMES


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)

def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


# ── Main menu ─────────────────────────────────────────────────────────────────

def main_menu_kb(is_super_owner: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("✨ Нейросеть", "menu:ai")],
        [_btn("🎮 Игры", "menu:games"),      _btn("👤 Профиль", "menu:profile")],
        [_btn("💎 Подписка", "menu:shop"),   _btn("⚙️ Настройки", "menu:settings")],
        [_btn("❓ Помощь", "menu:help")],
    ]
    if is_super_owner:
        buttons.append([_btn("👑 Панель управления", "admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🏠 Главное меню", "menu:main")]
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✖️ Отмена", "menu:main")]
    ])


# ── AI chat: список чатов ───────────────────────────────────────────────────────

def chat_list_kb(chats: list[dict]) -> InlineKeyboardMarkup:
    buttons = [[_btn("➕ Новый диалог", "chat:new")]]
    for c in chats[:25]:
        title = c.get("title") or "Новый диалог"
        prefix = "📌 " if c.get("pinned") else "💬 "
        buttons.append([_btn(f"{prefix}{title}"[:64], f"chat:open:{c['id']}")])
    if len(chats) > 5:
        buttons.append([_btn("🔎 Поиск по диалогам", "chat:search")])
    buttons.append([_btn("🏠 Главное меню", "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def chat_actions_kb(chat_id: str, pinned: bool, search_on: bool) -> InlineKeyboardMarkup:
    pin_label = "📌 Открепить" if pinned else "📍 Закрепить"
    search_label = "🌐 Поиск: вкл ✅" if search_on else "🌐 Поиск: выкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(pin_label, f"chat:pin:{chat_id}"), _btn("✏️ Переименовать", f"chat:rename:{chat_id}")],
        [_btn(search_label, f"chat:togglesearch:{chat_id}")],
        [_btn("🗑️ Удалить диалог", f"chat:delete:{chat_id}")],
        [_btn("⬅️ Все диалоги", "chat:list"), _btn("🏠 Меню", "menu:main")],
    ])


def chat_delete_confirm_kb(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("✅ Да, удалить", f"chat:delete_confirm:{chat_id}"),
            _btn("✖️ Отмена", f"chat:open:{chat_id}"),
        ],
    ])


def stop_generation_kb(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏹ Остановить", f"ai:stop:{chat_id}")],
    ])


def after_response_kb(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⬅️ Все диалоги", "chat:list"), _btn("🏠 Меню", "menu:main")],
    ])


def back_to_chat_kb(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("↩️ Отмена", f"chat:open:{chat_id}")],
    ])


# ── Games ─────────────────────────────────────────────────────────────────────

def games_menu_kb(has_active: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_active:
        rows.append([_btn("▶️ Продолжить текущую игру", "game:reconnect")])
    items = list(GAMES.items())
    for i in range(0, len(items), 2):
        pair = items[i:i + 2]
        rows.append([_btn(f"{g['emoji']} {g['title']}", f"game:open:{key}") for key, g in pair])
    rows.append([_btn("🏠 Главное меню", "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def game_mode_kb(game_type: str, extra: str | None = None) -> InlineKeyboardMarkup:
    suffix = f":{extra}" if extra else ""
    bot_label = "🙋 Играть одному" if game_type == "quiz" else "🤖 Против бота"
    friend_label = "👥 Играть с друзьями" if game_type == "quiz" else "👥 Пригласить друга"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(bot_label, f"gm:bot:{game_type}{suffix}")],
        [_btn(friend_label, f"gm:friend:{game_type}{suffix}")],
        [_btn("⬅️ К играм", "menu:games")],
    ])


def difficulty_kb(game_type: str) -> InlineKeyboardMarkup:
    """Выбор уровня сложности перед стартом (сейчас используется для 'Памяти')."""
    from handlers.games.memory import DIFFICULTY
    rows = []
    for key, cfg in DIFFICULTY.items():
        rows.append([_btn(cfg["label"], f"game:diff:{game_type}:{key}")])
    rows.append([_btn("⬅️ К играм", "menu:games")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def invite_friend_kb(game_id: str, bot_username: str) -> InlineKeyboardMarkup:
    invite_link = f"https://t.me/{bot_username}?start=game_{game_id}"
    share_text = urllib.parse.quote("Сыграем вместе в Neuravix AI! 🎮")
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(invite_link)}&text={share_text}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_url_btn("📤 Поделиться приглашением", share_url)],
        [_btn("✖️ Отменить приглашение", f"game:cancel_invite:{game_id}")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


def after_game_kb(game_type: str, room_id: str, creator_id: int, opponent_id: int, is_creator: bool) -> InlineKeyboardMarkup:
    buttons = [[_btn("🔄 Играть снова", f"game:rematch:{room_id}")]]
    if is_creator:
        buttons.append([_btn("🎮 Сменить игру", f"game:reswitch:{room_id}")])
    buttons.append([_btn("📋 Все игры", "menu:games"), _btn("🏠 Меню", "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def switch_game_kb(room_id: str) -> InlineKeyboardMarkup:
    buttons = []
    items = list(GAMES.items())
    for i in range(0, len(items), 2):
        pair = items[i:i + 2]
        buttons.append([_btn(f"{g['emoji']} {g['title']}", f"game:switchto:{room_id}:{key}") for key, g in pair])
    buttons.append([_btn("🏠 Главное меню", "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Shop ──────────────────────────────────────────────────────────────────────

def shop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🌗 Plus — 120 сообщ/день · 299 ₽/мес", "buy:plus")],
        [_btn("🌕 Pro — 350 сообщ/день · 799 ₽/мес", "buy:pro")],
        [_btn("🌟 Ultra — 700 сообщ/день · 1499 ₽/мес", "buy:ultra")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


# ── Admin panel ───────────────────────────────────────────────────────────────

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("👥 Пользователи", "admin:users:page:0")],
        [_btn("➕ Выдать подписку", "admin:give_sub"), _btn("➖ Удалить подписку", "admin:take_sub_list")],
        [_btn("👑 Creator Elite", "admin:give_elite"), _btn("🛡️ Управление админами", "admin:manage_admins")],
        [_btn("📢 Рассылка", "admin:broadcast"), _btn("📤 Экспорт польз.", "admin:user_list")],
        [_btn("📊 Статистика", "admin:stats"), _btn("📦 Архив проекта", "admin:get_project")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


USERS_PAGE_SIZE = 8


def users_list_kb(users: list, offset: int, total: int, owner_id: int, admin_ids: set) -> InlineKeyboardMarkup:
    rows = [[_btn("🔍 Поиск по username/ID", "admin:users:search")]]
    for u in users:
        uid = u["telegram_id"]
        name = u.get("first_name") or "Без имени"
        uname = f"@{u['username']}" if u.get("username") else ""
        badge = ""
        if uid == owner_id:
            badge = "👑 "
        elif uid in admin_ids:
            badge = "🛡️ "
        elif u.get("is_banned"):
            badge = "🚫 "
        elif u.get("blocked_bot"):
            badge = "💤 "
        label = f"{badge}{name} {uname}".strip()
        rows.append([_btn(label[:64], f"admin:users:view:{uid}")])

    nav = []
    if offset > 0:
        nav.append(_btn("⬅️ Пред.", f"admin:users:page:{max(0, offset - USERS_PAGE_SIZE)}"))
    if offset + USERS_PAGE_SIZE < total:
        nav.append(_btn("След. ➡️", f"admin:users:page:{offset + USERS_PAGE_SIZE}"))
    if nav:
        rows.append(nav)

    rows.append([_btn("📤 Экспорт списка", "admin:user_list")])
    rows.append([_btn("⬅️ Панель", "admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_detail_kb(user: dict, is_protected: bool) -> InlineKeyboardMarkup:
    uid = user["telegram_id"]
    rows = []
    if is_protected:
        pass  # владельца/админов нельзя блокировать — кнопка не показывается
    elif user.get("is_banned"):
        rows.append([_btn("✅ Разблокировать", f"admin:users:unblock:{uid}")])
    else:
        rows.append([_btn("🚫 Заблокировать", f"admin:users:block:{uid}")])
    rows.append([_btn("⬅️ К списку", "admin:users:page:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_search_results_kb(users: list, owner_id: int, admin_ids: set) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        uid = u["telegram_id"]
        name = u.get("first_name") or "Без имени"
        uname = f"@{u['username']}" if u.get("username") else ""
        badge = "👑 " if uid == owner_id else ("🛡️ " if uid in admin_ids else ("🚫 " if u.get("is_banned") else ""))
        rows.append([_btn(f"{badge}{name} {uname}".strip()[:64], f"admin:users:view:{uid}")])
    if not rows:
        rows.append([_btn("Ничего не найдено", "admin:users:search")])
    rows.append([_btn("⬅️ К списку", "admin:users:page:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_admins_kb(admins: list) -> InlineKeyboardMarkup:
    buttons = [[_btn("➕ Назначить админа", "admin:add_admin")]]
    for a in admins[:30]:
        name = a.get("first_name") or "Без имени"
        uname = f" @{a['username']}" if a.get("username") else ""
        buttons.append([_btn(f"✖️ {name}{uname}", f"admin:rm_admin:{a['telegram_id']}")])
    buttons.append([_btn("⬅️ Назад", "admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_sub_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🌗 Plus", "admin:set_sub:plus"), _btn("🌕 Pro", "admin:set_sub:pro")],
        [_btn("🌟 Ultra", "admin:set_sub:ultra"), _btn("👑 Creator Elite", "admin:set_sub:creator_elite")],
        [_btn("⬅️ Назад", "admin:panel")],
    ])


def subscribed_users_kb(users: list) -> InlineKeyboardMarkup:
    SUB_ICONS = {"plus": "🌗", "pro": "🌕", "ultra": "🌟", "creator_elite": "👑"}
    buttons = []
    for u in users[:30]:
        name = u.get("first_name") or "Без имени"
        uname = f" @{u['username']}" if u.get("username") else ""
        sub = u.get("subscription", "free")
        icon = SUB_ICONS.get(sub, "")
        buttons.append([_btn(f"{icon} {name}{uname}", f"admin:rm_sub:{u['telegram_id']}")])
    buttons.append([_btn("⬅️ Назад", "admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Text writer ───────────────────────────────────────────────────────────────

def text_writer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📰 Статья", "tw:article"), _btn("📱 Пост", "tw:post")],
        [_btn("🎉 Поздравление", "tw:congrats"), _btn("✉️ Письмо", "tw:letter")],
        [_btn("📦 Описание товара", "tw:description"), _btn("🎬 Сценарий", "tw:scenario")],
        [_btn("🪶 Свободный текст", "tw:free")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


# ── Settings ──────────────────────────────────────────────────────────────────

def settings_kb(ai_enabled: bool = True) -> InlineKeyboardMarkup:
    ai_status = "✅ Включена" if ai_enabled else "⭕ Отключена"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"✨ Нейросеть: {ai_status}", "settings:toggle_ai")],
        [_btn("🗑️ Удалить все диалоги", "settings:clear_history_confirm")],
        [_btn("🏠 Главное меню", "menu:main")],
    ])


def settings_clear_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Да, удалить всё", "settings:clear_history"), _btn("✖️ Отмена", "menu:settings")],
    ])
