import aiosqlite
import json
import os
import shutil
import uuid
import asyncio
from datetime import datetime, date, timedelta
from config import DB_PATH, ADMIN_ID, BACKUP_DIR
from database.db_backend import (
    get_connection, IntegrityError, USE_POSTGRES, AUTOINCREMENT_PK,
    init_pg_pool, close_pg_pool,
)


async def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with get_connection(DB_PATH) as db:
        # WAL — позволяет читать и писать одновременно без блокировки всей БД,
        # это заметно ускоряет бота под конкурентной нагрузкой (несколько
        # пользователей пишут одновременно). synchronous=NORMAL — безопасный
        # компромисс скорость/надёжность при включённом WAL.
        # Актуально только для SQLite — у PostgreSQL своя, отдельная модель
        # конкурентного доступа, эти команды ему не нужны и не поддерживаются.
        if not USE_POSTGRES:
            try:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass  # на некоторых файловых системах (сетевые тома) WAL недоступен — не критично
        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {AUTOINCREMENT_PK},
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                subscription TEXT DEFAULT 'free',
                messages_today INTEGER DEFAULT 0,
                images_today INTEGER DEFAULT 0,
                last_reset TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                language TEXT DEFAULT 'ru',
                ai_enabled INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0,
                blocked_bot INTEGER DEFAULT 0,
                last_seen TEXT DEFAULT '',
                total_images INTEGER DEFAULT 0,
                total_files INTEGER DEFAULT 0,
                stars_spent INTEGER DEFAULT 0,
                subscription_expires_at TEXT DEFAULT '',
                response_style TEXT DEFAULT 'default',
                model_preference TEXT DEFAULT 'auto',
                expiry_notified INTEGER DEFAULT 0
            )
        """)
        # Миграции для старых баз
        for stmt in [
            "ALTER TABLE users ADD COLUMN images_today INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN blocked_bot INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_seen TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN total_images INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN total_files INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN stars_spent INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN subscription_expires_at TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN response_style TEXT DEFAULT 'default'",
            "ALTER TABLE users ADD COLUMN model_preference TEXT DEFAULT 'auto'",
            "ALTER TABLE users ADD COLUMN expiry_notified INTEGER DEFAULT 0",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass

        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT,
                pinned INTEGER DEFAULT 0,
                search_enabled INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
        """)
        try:
            await db.execute("ALTER TABLE chats ADD COLUMN search_enabled INTEGER DEFAULT 0")
        except Exception:
            pass

        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS messages (
                id {AUTOINCREMENT_PK},
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tg_message_id INTEGER,
                created_at TEXT DEFAULT ''
            )
        """)

        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS game_sessions (
                id {AUTOINCREMENT_PK},
                game_id TEXT UNIQUE NOT NULL,
                game_type TEXT NOT NULL,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER,
                mode TEXT DEFAULT 'friend',
                state TEXT DEFAULT '{{}}',
                current_turn INTEGER,
                status TEXT DEFAULT 'waiting',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
        """)
        for stmt in (
            "ALTER TABLE game_sessions ADD COLUMN mode TEXT DEFAULT 'friend'",
            "ALTER TABLE game_sessions ADD COLUMN updated_at TEXT DEFAULT ''",
        ):
            try:
                await db.execute(stmt)
            except Exception:
                pass

        # Секретные команды (пасхалки) — отдельная таблица "найдено кем и когда".
        # Отдельная таблица (а не поле в users) специально для лёгкого расширения:
        # добавление новой секретной команды в config.py не требует миграций схемы БД.
        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS secret_commands_found (
                id {AUTOINCREMENT_PK},
                telegram_id INTEGER NOT NULL,
                command_key TEXT NOT NULL,
                found_at TEXT NOT NULL,
                UNIQUE(telegram_id, command_key)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_secret_found_user "
            "ON secret_commands_found(telegram_id)"
        )

        # Товары магазина — полностью управляются из админ-панели, без правки
        # кода. product_type позволяет добавлять новые типы товаров в будущем
        # без изменения схемы: 'subscription' — грант тарифа из
        # SUBSCRIPTION_LIMITS (grants_subscription хранит его ключ),
        # остальные типы могут добавляться позже без миграции.
        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS shop_products (
                id {AUTOINCREMENT_PK},
                product_key TEXT UNIQUE NOT NULL,
                product_type TEXT DEFAULT 'subscription',
                grants_subscription TEXT DEFAULT '',
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                benefits TEXT DEFAULT '[]',
                price_stars INTEGER NOT NULL DEFAULT 0,
                duration_days INTEGER DEFAULT 0,
                image_file_id TEXT DEFAULT '',
                category TEXT DEFAULT 'Общее',
                is_visible INTEGER DEFAULT 1,
                is_permanent INTEGER DEFAULT 1,
                expires_at TEXT DEFAULT '',
                display_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_shop_products_visible "
            "ON shop_products(is_visible, display_order)"
        )

        await db.commit()

    await ensure_admin_user()


async def ensure_admin_user():
    async with get_connection(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (ADMIN_ID,)) as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET subscription = 'creator_elite', is_admin = 1 WHERE telegram_id = ?",
                (ADMIN_ID,)
            )
            await db.commit()


async def _apply_subscription_expiry(db, user_row: dict) -> dict:
    """
    Если у платной подписки вышел срок (покупка через Stars на N дней) —
    автоматически понижает до free прямо здесь, при чтении пользователя.
    creator_elite (выданный владельцем/админом) сроков не имеет и не трогается.
    """
    sub = user_row.get("subscription")
    expires_at = user_row.get("subscription_expires_at")
    if sub and sub not in ("free", "creator_elite") and expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.now():
                await db.execute(
                    "UPDATE users SET subscription = 'free', subscription_expires_at = '' "
                    "WHERE telegram_id = ?",
                    (user_row["telegram_id"],)
                )
                await db.commit()
                user_row["subscription"] = "free"
                user_row["subscription_expires_at"] = ""
        except Exception:
            pass
    return user_row


async def set_subscription(telegram_id: int, plan: str, duration_days: int | None = None):
    """Активирует платный тариф. duration_days=None — бессрочно (выдано вручную владельцем)."""
    expires_at = ""
    if duration_days:
        expires_at = (datetime.now() + timedelta(days=duration_days)).isoformat()
    # Сбрасываем флаг напоминания об истечении — для нового периода подписки
    # уведомление должно сработать заново, когда он тоже подойдёт к концу.
    await update_user(telegram_id, subscription=plan, subscription_expires_at=expires_at, expiry_notified=0)


async def get_users_expiring_soon(days: int = 3) -> list:
    """
    Пользователи с платной подпиской, которая истекает в ближайшие N дней и
    ещё не получали об этом напоминание. Используется фоновой задачей
    уведомлений в main.py.
    """
    now = datetime.now()
    soon = (now + timedelta(days=days)).isoformat()
    now_iso = now.isoformat()
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE subscription NOT IN ('free', 'creator_elite') "
            "AND subscription_expires_at != '' "
            "AND subscription_expires_at > ? AND subscription_expires_at <= ? "
            "AND COALESCE(expiry_notified, 0) = 0",
            (now_iso, soon),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def mark_expiry_notified(telegram_id: int):
    await update_user(telegram_id, expiry_notified=1)


async def add_stars_spent(telegram_id: int, amount: int):
    async with get_connection(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET stars_spent = COALESCE(stars_spent, 0) + ? WHERE telegram_id = ?",
            (amount, telegram_id)
        )
        await db.commit()


async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            is_admin = 1 if telegram_id == ADMIN_ID else 0
            subscription = "creator_elite" if telegram_id == ADMIN_ID else "free"
            now = datetime.now().isoformat()
            await db.execute(
                """INSERT INTO users
                   (telegram_id, username, first_name, subscription, is_admin, created_at, last_reset)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (telegram_id, username, first_name, subscription, is_admin, now, str(date.today()))
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
        else:
            if username is not None or first_name is not None:
                updates = {}
                if username is not None:
                    updates["username"] = username
                if first_name is not None:
                    updates["first_name"] = first_name
                if updates:
                    fields = ", ".join(f"{k} = ?" for k in updates)
                    values = list(updates.values()) + [telegram_id]
                    await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
                    await db.commit()
                    async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                        row = await cursor.fetchone()

        user = dict(row)
        user = await _apply_subscription_expiry(db, user)
        return user


async def update_user(telegram_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [telegram_id]
    async with get_connection(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
        await db.commit()


async def get_user(telegram_id: int) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        user = dict(row)
        return await _apply_subscription_expiry(db, user)


async def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").lower()
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE LOWER(username) = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


def _reset_today_if_needed(user: dict) -> tuple[bool, str]:
    """Возвращает (нужен_сброс, сегодняшняя_дата)."""
    today = str(date.today())
    return user.get("last_reset") != today, today


async def can_send_message(telegram_id: int) -> tuple[bool, int]:
    from config import SUBSCRIPTION_LIMITS
    user = await get_user(telegram_id)
    if not user:
        return False, 0

    sub = user["subscription"]
    limit = SUBSCRIPTION_LIMITS[sub]["messages_per_day"]
    if limit == -1:
        return True, -1

    today = str(date.today())
    if user.get("last_reset") != today:
        await update_user(telegram_id, messages_today=0, images_today=0, last_reset=today)
        return True, limit

    used = user.get("messages_today", 0)
    remaining = limit - used
    return remaining > 0, max(remaining, 0)


async def can_generate_image(telegram_id: int) -> tuple[bool, int]:
    from config import SUBSCRIPTION_LIMITS
    user = await get_user(telegram_id)
    if not user:
        return False, 0

    sub = user["subscription"]
    limit = SUBSCRIPTION_LIMITS[sub].get("images_per_day", 5)
    if limit == -1:
        return True, -1

    today = str(date.today())
    if user.get("last_reset") != today:
        await update_user(telegram_id, messages_today=0, images_today=0, last_reset=today)
        return True, limit

    used = user.get("images_today", 0)
    remaining = limit - used
    return remaining > 0, max(remaining, 0)


async def increment_message_count(telegram_id: int):
    today = str(date.today())
    async with get_connection(DB_PATH) as db:
        async with db.execute(
            "SELECT last_reset, messages_today FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            last_reset, count = row
            if last_reset != today:
                await db.execute(
                    "UPDATE users SET messages_today = 1, images_today = 0, last_reset = ? WHERE telegram_id = ?",
                    (today, telegram_id)
                )
            else:
                await db.execute(
                    "UPDATE users SET messages_today = ? WHERE telegram_id = ?",
                    (count + 1, telegram_id)
                )
        await db.commit()


async def increment_image_count(telegram_id: int):
    today = str(date.today())
    async with get_connection(DB_PATH) as db:
        async with db.execute(
            "SELECT last_reset, images_today FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            last_reset, count = row
            if last_reset != today:
                await db.execute(
                    "UPDATE users SET images_today = 1, messages_today = 0, last_reset = ? WHERE telegram_id = ?",
                    (today, telegram_id)
                )
            else:
                await db.execute(
                    "UPDATE users SET images_today = ? WHERE telegram_id = ?",
                    ((count or 0) + 1, telegram_id)
                )
            # Пожизненный счётчик — не сбрасывается ежедневно, для профиля
            await db.execute(
                "UPDATE users SET total_images = COALESCE(total_images, 0) + 1 WHERE telegram_id = ?",
                (telegram_id,)
            )
        await db.commit()


async def increment_file_count(telegram_id: int):
    """Пожизненный счётчик созданных/отредактированных нейросетью файлов — для профиля."""
    async with get_connection(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET total_files = COALESCE(total_files, 0) + 1 WHERE telegram_id = ?",
            (telegram_id,)
        )
        await db.commit()


async def count_total_messages(telegram_id: int) -> int:
    """Пожизненное количество сообщений пользователя нейросети (по всем чатам)."""
    async with get_connection(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM messages m "
            "JOIN chats c ON m.chat_id = c.id "
            "WHERE c.user_id = ? AND m.role = 'user'",
            (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


# ── Chats ───────────────────────────────────────────────────────────────────────

async def create_chat(user_id: int, title: str | None = None) -> str:
    chat_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    async with get_connection(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chats (id, user_id, title, pinned, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (chat_id, user_id, title, now, now),
        )
        await db.commit()
    return chat_id


async def get_chats(user_id: int, query: str | None = None) -> list[dict]:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query:
            like = f"%{query.lower()}%"
            # Ищем и по названию диалога, И по содержимому сообщений внутри
            # него — раньше поиск находил совпадение только в заголовке,
            # хотя пользователь чаще ищет что-то конкретное, что обсуждал,
            # а не помнит точное название чата.
            async with db.execute(
                "SELECT * FROM chats WHERE user_id = ? AND ("
                "  LOWER(COALESCE(title, '')) LIKE ? "
                "  OR id IN (SELECT DISTINCT chat_id FROM messages WHERE LOWER(content) LIKE ?)"
                ") ORDER BY pinned DESC, updated_at DESC",
                (user_id, like, like),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM chats WHERE user_id = ? ORDER BY pinned DESC, updated_at DESC",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_chat(chat_id: str) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def rename_chat(chat_id: str, title: str):
    async with get_connection(DB_PATH) as db:
        await db.execute("UPDATE chats SET title = ? WHERE id = ?", (title.strip()[:80], chat_id))
        await db.commit()


async def toggle_pin_chat(chat_id: str) -> bool:
    chat = await get_chat(chat_id)
    if not chat:
        return False
    new_val = 0 if chat["pinned"] else 1
    async with get_connection(DB_PATH) as db:
        await db.execute("UPDATE chats SET pinned = ? WHERE id = ?", (new_val, chat_id))
        await db.commit()
    return bool(new_val)


async def toggle_search_chat(chat_id: str) -> bool:
    chat = await get_chat(chat_id)
    if not chat:
        return False
    new_val = 0 if chat.get("search_enabled") else 1
    async with get_connection(DB_PATH) as db:
        await db.execute("UPDATE chats SET search_enabled = ? WHERE id = ?", (new_val, chat_id))
        await db.commit()
    return bool(new_val)


async def touch_chat(chat_id: str):
    now = datetime.now().isoformat()
    async with get_connection(DB_PATH) as db:
        await db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        await db.commit()


async def delete_chat(chat_id: str):
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def clear_all_chats(user_id: int):
    chats = await get_chats(user_id)
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE user_id = ?", (user_id,))
        for c in chats:
            await db.execute("DELETE FROM messages WHERE chat_id = ?", (c["id"],))
        await db.commit()


async def count_chats(user_id: int) -> int:
    async with get_connection(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM chats WHERE user_id = ?", (user_id,)) as cur:
            return (await cur.fetchone())[0]


# ── Messages ────────────────────────────────────────────────────────────────────

async def get_messages(chat_id: str) -> list[dict]:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def add_message(chat_id: str, role: str, content: str, tg_message_id: int | None = None) -> int:
    now = datetime.now().isoformat()
    async with get_connection(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO messages (chat_id, role, content, tg_message_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, role, content, tg_message_id, now),
        )
        await db.commit()
        msg_id = cur.lastrowid
    await touch_chat(chat_id)
    return msg_id


async def update_message_content(message_id: int, content: str):
    async with get_connection(DB_PATH) as db:
        await db.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
        await db.commit()


async def delete_message(message_id: int):
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await db.commit()


async def delete_messages_after(chat_id: str, after_id: int):
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE chat_id = ? AND id > ?", (chat_id, after_id))
        await db.commit()


async def get_last_message(chat_id: str) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


# ── Game sessions ──────────────────────────────────────────────────────────────

BOT_PLAYER_ID = 0


def _row_to_session(row) -> dict:
    d = dict(row)
    try:
        d["state"] = json.loads(d["state"]) if d.get("state") else {}
    except Exception:
        d["state"] = {}
    return d


async def create_game_session(
    game_id: str, game_type: str, player1_id: int, state: dict,
    player2_id: int | None = None, mode: str = "friend",
    status: str = "waiting", current_turn: int | None = None,
) -> dict:
    now = datetime.now().isoformat()
    async with get_connection(DB_PATH) as db:
        await db.execute(
            """INSERT INTO game_sessions
               (game_id, game_type, player1_id, player2_id, mode, state, current_turn, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, game_type, player1_id, player2_id, mode, json.dumps(state),
             current_turn if current_turn is not None else player1_id, status, now, now)
        )
        await db.commit()
    return await get_game_session(game_id)


async def get_game_session(game_id: str) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM game_sessions WHERE game_id = ?", (game_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_session(row) if row else None


async def update_game_session(game_id: str, **kwargs):
    if "state" in kwargs and isinstance(kwargs["state"], dict):
        kwargs["state"] = json.dumps(kwargs["state"])
    kwargs["updated_at"] = datetime.now().isoformat()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [game_id]
    async with get_connection(DB_PATH) as db:
        await db.execute(f"UPDATE game_sessions SET {fields} WHERE game_id = ?", values)
        await db.commit()


async def delete_game_session(game_id: str):
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM game_sessions WHERE game_id = ?", (game_id,))
        await db.commit()


async def get_active_session_for_user(user_id: int) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM game_sessions WHERE (player1_id = ? OR player2_id = ?) "
            "AND status IN ('active', 'waiting') ORDER BY updated_at DESC LIMIT 1",
            (user_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_session(row) if row else None


async def get_waiting_sessions_older_than(cutoff_iso: str) -> list[dict]:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM game_sessions WHERE status = 'waiting' AND created_at < ?",
            (cutoff_iso,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_session(r) for r in rows]


# ── Admin ────────────────────────────────────────────────────────────────────────

async def get_all_users() -> list:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_users_page(offset: int = 0, limit: int = 10, active_only: bool = False) -> tuple[list, int]:
    """Возвращает (страница пользователей, общее количество) для интерактивного списка.
    active_only=True — исключает пользователей, заблокировавших бота (blocked_bot=1)."""
    where = "WHERE blocked_bot = 0" if active_only else ""
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT COUNT(*) FROM users {where}") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows], total


async def search_users(query: str, limit: int = 10) -> list:
    """Ищет пользователей по username (частичное совпадение) или точному Telegram ID."""
    query = query.strip().lstrip("@")
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query.isdigit():
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ? OR CAST(telegram_id AS TEXT) LIKE ? LIMIT ?",
                (int(query), f"%{query}%", limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM users WHERE LOWER(username) LIKE ? OR LOWER(first_name) LIKE ? LIMIT ?",
                (f"%{query.lower()}%", f"%{query.lower()}%", limit),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_banned(telegram_id: int, banned: bool):
    await update_user(telegram_id, is_banned=1 if banned else 0)


async def is_user_banned(telegram_id: int) -> bool:
    user = await get_user(telegram_id)
    return bool(user and user.get("is_banned"))


async def mark_blocked_bot(telegram_id: int, blocked: bool = True):
    """Помечает, что пользователь заблокировал бота (или разблокировал, если написал снова)."""
    await update_user(telegram_id, blocked_bot=1 if blocked else 0)


async def update_last_seen(telegram_id: int):
    await update_user(telegram_id, last_seen=datetime.now().isoformat())


async def get_admins() -> list:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE is_admin = 1") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_admin(telegram_id: int, is_admin: bool):
    await update_user(telegram_id, is_admin=1 if is_admin else 0)


async def get_subscribed_users() -> list:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE subscription != 'free' ORDER BY subscription, first_name"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_stats() -> dict:
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    month_ago = (today - timedelta(days=30)).isoformat()

    async with get_connection(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT subscription, COUNT(*) FROM users GROUP BY subscription") as cur:
            sub_rows = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE last_reset = ?", (str(today),)
        ) as cur:
            active_today = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (str(today),)
        ) as cur:
            new_today = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (week_ago,)
        ) as cur:
            new_week = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (month_ago,)
        ) as cur:
            new_month = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE blocked_bot = 1"
        ) as cur:
            blocked_bot_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_banned = 1"
        ) as cur:
            banned_count = (await cur.fetchone())[0]

    subs = {row[0]: row[1] for row in sub_rows}
    return {
        "total": total,
        "active_today": active_today,
        "subscriptions": subs,
        "new_today": new_today,
        "new_week": new_week,
        "new_month": new_month,
        "blocked_bot": blocked_bot_count,
        "banned": banned_count,
    }


# ── Backups ──────────────────────────────────────────────────────────────────────

def backup_database(keep: int = 5) -> str | None:
    """
    Резервное копирование локального файла БД — актуально только для SQLite.
    Для PostgreSQL (Railway Managed Postgres) резервное копирование делает
    сам сервис БД (снапшоты/point-in-time recovery на стороне Railway) —
    копировать локальный файл здесь просто нечего, функция ничего не делает.
    """
    if USE_POSTGRES:
        return None
    if not os.path.exists(DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"neuravix_{stamp}.db")
    try:
        shutil.copy2(DB_PATH, dest)
    except Exception:
        return None

    backups = sorted(
        f for f in os.listdir(BACKUP_DIR) if f.startswith("neuravix_") and f.endswith(".db")
    )
    while len(backups) > keep:
        oldest = backups.pop(0)
        try:
            os.remove(os.path.join(BACKUP_DIR, oldest))
        except Exception:
            pass
    return dest


# ── Секретные команды (пасхалки) ────────────────────────────────────────────────

async def mark_secret_command_found(telegram_id: int, command_key: str) -> bool:
    """
    Засчитывает секретную команду пользователю. Возвращает True, если команда
    найдена ВПЕРВЫЕ (нужно показать уведомление), и False, если она уже была
    найдена раньше (повторное использование прогресс не увеличивает).
    """
    async with get_connection(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO secret_commands_found (telegram_id, command_key, found_at) "
                "VALUES (?, ?, ?)",
                (telegram_id, command_key, datetime.now().isoformat()),
            )
            await db.commit()
            return True
        except IntegrityError:
            # UNIQUE(telegram_id, command_key) — уже было найдено раньше
            return False


async def get_found_secret_commands(telegram_id: int) -> set[str]:
    async with get_connection(DB_PATH) as db:
        async with db.execute(
            "SELECT command_key FROM secret_commands_found WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            rows = await cur.fetchall()
        return {r[0] for r in rows}


async def count_found_secret_commands(telegram_id: int) -> int:
    async with get_connection(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM secret_commands_found WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


# ── Магазин: товары ──────────────────────────────────────────────────────────

async def seed_default_shop_products():
    """
    Разовая миграция: если таблица товаров пуста (например, при первом
    запуске этой версии), переносит в неё текущие тарифы Plus/Pro/Ultra из
    config.py — чтобы существующий магазин продолжил работать без единого
    изменения для пользователя. При повторных запусках ничего не делает
    (таблица уже не пуста) — данные не теряются и не дублируются.
    """
    import json as _json
    from config import SUBSCRIPTION_LIMITS, SUBSCRIPTION_PLANS

    async with get_connection(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM shop_products") as cur:
            count = (await cur.fetchone())[0]
        if count > 0:
            return

        now = datetime.now().isoformat()
        order = 0
        for plan_key in ("plus", "pro", "ultra"):
            limits = SUBSCRIPTION_LIMITS.get(plan_key, {})
            plan = SUBSCRIPTION_PLANS.get(plan_key, {})
            if not limits or not plan:
                continue
            order += 10
            try:
                await db.execute(
                    "INSERT INTO shop_products "
                    "(product_key, product_type, grants_subscription, name, description, "
                    " benefits, price_stars, duration_days, image_file_id, category, "
                    " is_visible, is_permanent, expires_at, display_order, created_at, updated_at) "
                    "VALUES (?, 'subscription', ?, ?, ?, ?, ?, ?, '', 'Подписки', 1, 1, '', ?, ?, ?)",
                    (
                        plan_key, plan_key, limits.get("label", plan_key),
                        plan.get("description", ""), _json.dumps(plan.get("benefits", []), ensure_ascii=False),
                        plan.get("stars", 0), plan.get("duration_days", 30),
                        order, now, now,
                    )
                )
            except IntegrityError:
                pass  # такой товар уже есть — пропускаем, ничего не теряем
        await db.commit()


def _row_to_product(row: dict) -> dict:
    import json as _json
    row = dict(row)
    try:
        row["benefits"] = _json.loads(row.get("benefits") or "[]")
    except Exception:
        row["benefits"] = []
    return row


async def get_shop_products(visible_only: bool = True) -> list:
    """Список товаров, отсортированный по порядку отображения. Просроченные
    временные товары автоматически исключаются (и лениво скрываются)."""
    now = datetime.now().isoformat()
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Лениво скрываем просроченные временные товары/акции
        await db.execute(
            "UPDATE shop_products SET is_visible = 0 "
            "WHERE is_permanent = 0 AND expires_at != '' AND expires_at < ? AND is_visible = 1",
            (now,)
        )
        await db.commit()

        where = "WHERE is_visible = 1" if visible_only else ""
        async with db.execute(
            f"SELECT * FROM shop_products {where} ORDER BY display_order ASC, id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_product(dict(r)) for r in rows]


async def get_shop_product(product_key: str) -> dict | None:
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM shop_products WHERE product_key = ?", (product_key,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_product(dict(row)) if row else None


async def create_shop_product(product_key: str, **fields) -> bool:
    import json as _json
    if "benefits" in fields and isinstance(fields["benefits"], list):
        fields["benefits"] = _json.dumps(fields["benefits"], ensure_ascii=False)
    now = datetime.now().isoformat()
    fields.setdefault("created_at", now)
    fields["updated_at"] = now

    cols = ["product_key"] + list(fields.keys())
    placeholders = ["?"] * len(cols)
    values = [product_key] + list(fields.values())
    async with get_connection(DB_PATH) as db:
        try:
            await db.execute(
                f"INSERT INTO shop_products ({', '.join(cols)}) VALUES ({', '.join(placeholders)})",
                values,
            )
            await db.commit()
            return True
        except IntegrityError:
            return False  # такой product_key уже существует


async def update_shop_product(product_key: str, **fields) -> bool:
    if not fields:
        return False
    import json as _json
    if "benefits" in fields and isinstance(fields["benefits"], list):
        fields["benefits"] = _json.dumps(fields["benefits"], ensure_ascii=False)
    fields["updated_at"] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [product_key]
    async with get_connection(DB_PATH) as db:
        await db.execute(
            f"UPDATE shop_products SET {set_clause} WHERE product_key = ?", values
        )
        await db.commit()
        return True


async def delete_shop_product(product_key: str) -> bool:
    """Удаление товара — явное действие администратора (разрешено правилами:
    запрещены только автоматические/массовые удаления пользовательских данных,
    это не пользовательские данные и не автоматическое действие)."""
    async with get_connection(DB_PATH) as db:
        await db.execute("DELETE FROM shop_products WHERE product_key = ?", (product_key,))
        await db.commit()
        return True


async def move_shop_product(product_key: str, direction: str) -> bool:
    """direction: 'up' | 'down' — меняет местами display_order с соседним товаром."""
    async with get_connection(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, display_order FROM shop_products WHERE product_key = ?", (product_key,)
        ) as cur:
            current = await cur.fetchone()
        if not current:
            return False

        if direction == "up":
            async with db.execute(
                "SELECT id, product_key, display_order FROM shop_products "
                "WHERE display_order < ? ORDER BY display_order DESC LIMIT 1",
                (current["display_order"],)
            ) as cur:
                neighbor = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT id, product_key, display_order FROM shop_products "
                "WHERE display_order > ? ORDER BY display_order ASC LIMIT 1",
                (current["display_order"],)
            ) as cur:
                neighbor = await cur.fetchone()

        if not neighbor:
            return False  # уже крайний

        await db.execute(
            "UPDATE shop_products SET display_order = ? WHERE product_key = ?",
            (neighbor["display_order"], product_key),
        )
        await db.execute(
            "UPDATE shop_products SET display_order = ? WHERE product_key = ?",
            (current["display_order"], neighbor["product_key"]),
        )
        await db.commit()
        return True
