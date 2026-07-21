import aiosqlite
import json
import os
import shutil
import uuid
import asyncio
from datetime import datetime, date, timedelta
from config import DB_PATH, ADMIN_ID, BACKUP_DIR


async def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                last_seen TEXT DEFAULT ''
            )
        """)
        # Миграции для старых баз
        for stmt in [
            "ALTER TABLE users ADD COLUMN images_today INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN blocked_bot INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_seen TEXT DEFAULT ''",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass

        await db.execute("""
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tg_message_id INTEGER,
                created_at TEXT DEFAULT ''
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE NOT NULL,
                game_type TEXT NOT NULL,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER,
                mode TEXT DEFAULT 'friend',
                state TEXT DEFAULT '{}',
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
        await db.commit()

    await ensure_admin_user()


async def ensure_admin_user():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (ADMIN_ID,)) as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET subscription = 'creator_elite', is_admin = 1 WHERE telegram_id = ?",
                (ADMIN_ID,)
            )
            await db.commit()


async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
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

        return dict(row)


async def update_user(telegram_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [telegram_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
        await db.commit()


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.commit()


# ── Chats ───────────────────────────────────────────────────────────────────────

async def create_chat(user_id: int, title: str | None = None) -> str:
    chat_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chats (id, user_id, title, pinned, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (chat_id, user_id, title, now, now),
        )
        await db.commit()
    return chat_id


async def get_chats(user_id: int, query: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query:
            like = f"%{query.lower()}%"
            async with db.execute(
                "SELECT * FROM chats WHERE user_id = ? AND LOWER(COALESCE(title, '')) LIKE ? "
                "ORDER BY pinned DESC, updated_at DESC",
                (user_id, like),
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def rename_chat(chat_id: str, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chats SET title = ? WHERE id = ?", (title.strip()[:80], chat_id))
        await db.commit()


async def toggle_pin_chat(chat_id: str) -> bool:
    chat = await get_chat(chat_id)
    if not chat:
        return False
    new_val = 0 if chat["pinned"] else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chats SET pinned = ? WHERE id = ?", (new_val, chat_id))
        await db.commit()
    return bool(new_val)


async def toggle_search_chat(chat_id: str) -> bool:
    chat = await get_chat(chat_id)
    if not chat:
        return False
    new_val = 0 if chat.get("search_enabled") else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chats SET search_enabled = ? WHERE id = ?", (new_val, chat_id))
        await db.commit()
    return bool(new_val)


async def touch_chat(chat_id: str):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        await db.commit()


async def delete_chat(chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def clear_all_chats(user_id: int):
    chats = await get_chats(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE user_id = ?", (user_id,))
        for c in chats:
            await db.execute("DELETE FROM messages WHERE chat_id = ?", (c["id"],))
        await db.commit()


async def count_chats(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM chats WHERE user_id = ?", (user_id,)) as cur:
            return (await cur.fetchone())[0]


# ── Messages ────────────────────────────────────────────────────────────────────

async def get_messages(chat_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def add_message(chat_id: str, role: str, content: str, tg_message_id: int | None = None) -> int:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO messages (chat_id, role, content, tg_message_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, role, content, tg_message_id, now),
        )
        await db.commit()
        msg_id = cur.lastrowid
    await touch_chat(chat_id)
    return msg_id


async def update_message_content(message_id: int, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
        await db.commit()


async def delete_message(message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await db.commit()


async def delete_messages_after(chat_id: str, after_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE chat_id = ? AND id > ?", (chat_id, after_id))
        await db.commit()


async def get_last_message(chat_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE game_sessions SET {fields} WHERE game_id = ?", values)
        await db.commit()


async def delete_game_session(game_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM game_sessions WHERE game_id = ?", (game_id,))
        await db.commit()


async def get_active_session_for_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM game_sessions WHERE (player1_id = ? OR player2_id = ?) "
            "AND status IN ('active', 'waiting') ORDER BY updated_at DESC LIMIT 1",
            (user_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_session(row) if row else None


async def get_waiting_sessions_older_than(cutoff_iso: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM game_sessions WHERE status = 'waiting' AND created_at < ?",
            (cutoff_iso,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_session(r) for r in rows]


# ── Admin ────────────────────────────────────────────────────────────────────────

async def get_all_users() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_users_page(offset: int = 0, limit: int = 10, active_only: bool = False) -> tuple[list, int]:
    """Возвращает (страница пользователей, общее количество) для интерактивного списка.
    active_only=True — исключает пользователей, заблокировавших бота (blocked_bot=1)."""
    where = "WHERE blocked_bot = 0" if active_only else ""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE is_admin = 1") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_admin(telegram_id: int, is_admin: bool):
    await update_user(telegram_id, is_admin=1 if is_admin else 0)


async def get_subscribed_users() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
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

    async with aiosqlite.connect(DB_PATH) as db:
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
