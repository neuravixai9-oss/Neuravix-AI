"""
Единый слой совместимости SQLite <-> PostgreSQL.

Идея: весь остальной код в database/db.py как писал запросы с плейсхолдерами
"?" и открывал соединение через "async with _connect() as db:", так и
продолжает это делать — ни один SQL-запрос в db.py переписывать вручную под
два диалекта не пришлось. Вся разница между SQLite и PostgreSQL спрятана
здесь, в одном месте.

Логика выбора бэкенда:
- Если задана переменная окружения DATABASE_URL — используется PostgreSQL
  (через asyncpg, с пулом соединений).
- Если DATABASE_URL не задана — используется SQLite (aiosqlite), как и
  раньше, для локальной разработки.
"""
import contextlib
import os

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import asyncpg
    # Единый алиас исключения "нарушение уникальности" — используется в db.py
    # вместо aiosqlite.IntegrityError, чтобы одинаково работать с обоими бэкендами.
    IntegrityError = asyncpg.exceptions.UniqueViolationError
    # PostgreSQL требует "SERIAL PRIMARY KEY" вместо "INTEGER PRIMARY KEY AUTOINCREMENT".
    AUTOINCREMENT_PK = "SERIAL PRIMARY KEY"
else:
    import aiosqlite
    IntegrityError = aiosqlite.IntegrityError
    AUTOINCREMENT_PK = "INTEGER PRIMARY KEY AUTOINCREMENT"


_pg_pool = None
_pg_connection_error: str | None = None


async def init_pg_pool() -> bool:
    """
    Создаёт пул соединений PostgreSQL один раз при старте бота. Для SQLite
    не требуется (там каждое соединение — быстрый локальный файл).

    ВАЖНО: если подключиться не удалось (недоступен хост, неверный
    DATABASE_URL, БД ещё не готова и т.п.) — НЕ роняет бота. Вместо этого
    откатывается на SQLite и возвращает False, чтобы вызывающий код мог
    залогировать понятную причину. Раньше ошибка подключения (например
    socket.gaierror при недоступном DNS) падала необработанной и убивала
    весь процесс — это была причина полного краша (Crashed) на Railway.
    """
    global _pg_pool, USE_POSTGRES, _pg_connection_error
    if not USE_POSTGRES:
        return False
    if _pg_pool is not None:
        return True
    try:
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        return True
    except Exception as e:
        _pg_connection_error = repr(e)
        # Откатываемся на SQLite — get_connection() ниже читает USE_POSTGRES
        # заново при каждом вызове (не хранит закешированное значение),
        # поэтому эта правка сразу подхватится всем database/db.py.
        USE_POSTGRES = False
        _pg_pool = None
        return False


async def close_pg_pool():
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


def _translate_placeholders(query: str) -> str:
    """Заменяет позиционные '?' (стиль SQLite) на '$1, $2, ...' (стиль asyncpg),
    аккуратно не трогая '?' внутри строковых литералов (в текущих запросах
    их нет, но на всякий случай)."""
    result = []
    n = 0
    in_string = False
    for ch in query:
        if ch == "'":
            in_string = not in_string
            result.append(ch)
        elif ch == "?" and not in_string:
            n += 1
            result.append(f"${n}")
        else:
            result.append(ch)
    return "".join(result)


class _PGCursor:
    """
    Эмулирует поведение курсора aiosqlite поверх asyncpg — поддерживает и
    'cur = await db.execute(...)', и 'async with db.execute(...) as cur:',
    plus .fetchone()/.fetchall()/.lastrowid — как и вызывающий код в db.py.
    """
    def __init__(self, conn, query: str, params: tuple):
        self._conn = conn
        self._query = query
        self._params = params or ()
        self._rows = None
        self.lastrowid = None
        self._done = False

    async def _run(self):
        if self._done:
            return self
        self._done = True
        pg_query = _translate_placeholders(self._query)
        stripped = pg_query.strip().upper()

        if stripped.startswith("SELECT") or stripped.startswith("WITH"):
            self._rows = await self._conn.fetch(pg_query, *self._params)
        elif stripped.startswith("INSERT") and "RETURNING" not in stripped:
            # Эмулируем cursor.lastrowid (используется в add_message) через
            # RETURNING id — у всех таблиц проекта есть колонка id.
            try:
                row = await self._conn.fetchrow(pg_query + " RETURNING id", *self._params)
                self.lastrowid = row["id"] if row else None
            except Exception:
                await self._conn.execute(pg_query, *self._params)
            self._rows = []
        else:
            await self._conn.execute(pg_query, *self._params)
            self._rows = []
        return self

    def __await__(self):
        return self._run().__await__()

    async def __aenter__(self):
        return await self._run()

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def fetchone(self):
        await self._run()
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        await self._run()
        return list(self._rows) if self._rows else []


class _PGConn:
    """Обёртка над соединением asyncpg с интерфейсом, совместимым с aiosqlite.Connection."""
    def __init__(self, raw_conn):
        self._conn = raw_conn
        self.row_factory = None  # для совместимости с 'db.row_factory = aiosqlite.Row' — не используется

    def execute(self, query: str, params: tuple = ()) -> _PGCursor:
        return _PGCursor(self._conn, query, params)

    async def executescript(self, script: str):
        await self._conn.execute(script)

    async def commit(self):
        # asyncpg вне явной транзакции коммитит каждый запрос сразу —
        # оставляем как no-op для совместимости с вызовами db.commit().
        pass


@contextlib.asynccontextmanager
async def get_connection(sqlite_path: str):
    """
    Единая точка открытия соединения для всего database/db.py.
    Возвращает объект с одинаковым API независимо от бэкенда.
    """
    if USE_POSTGRES:
        if _pg_pool is None:
            ok = await init_pg_pool()
            if not ok:
                # init_pg_pool() уже откатил USE_POSTGRES на False при неудаче —
                # используем SQLite прямо в этом вызове, не пытаясь достучаться
                # до несуществующего пула.
                async with aiosqlite.connect(sqlite_path) as db:
                    yield db
                return
        async with _pg_pool.acquire() as raw_conn:
            yield _PGConn(raw_conn)
    else:
        async with aiosqlite.connect(sqlite_path) as db:
            yield db
