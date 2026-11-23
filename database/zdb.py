import aiosqlite
from datetime import datetime
from zoneinfo import ZoneInfo
from database.db import DB_PATH

VLAT = ZoneInfo("Asia/Vladivostok")


def _now() -> str:
    return datetime.now(VLAT).strftime("%Y-%m-%d %H:%M:%S")


async def init_z_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript("""
        CREATE TABLE IF NOT EXISTS z_chats (
            chat_id INTEGER PRIMARY KEY,
            title   TEXT
        );
        CREATE TABLE IF NOT EXISTS z_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL,
            num          INTEGER NOT NULL,
            label        TEXT    NOT NULL,
            currency     TEXT    NOT NULL,
            amount       REAL    NOT NULL,
            client       TEXT    NOT NULL,
            creator_id   INTEGER,
            creator_name TEXT,
            message_id   INTEGER DEFAULT 0,
            status       TEXT    DEFAULT 'open',
            closed_by    TEXT,
            created_at   TEXT,
            closed_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_z_chat_status ON z_requests(chat_id, status);
        """)
        await conn.commit()


async def touch_chat(chat_id: int, title: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO z_chats (chat_id, title) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title
        """, (chat_id, title))
        await conn.commit()


async def get_chats() -> list[tuple[int, str]]:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT chat_id, title FROM z_chats") as cur:
            return await cur.fetchall()


async def next_num(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COALESCE(MAX(num), 0) + 1 FROM z_requests WHERE chat_id=?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0]


async def create_request(chat_id, num, label, currency, amount, client,
                         creator_id, creator_name) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("""
            INSERT INTO z_requests
              (chat_id, num, label, currency, amount, client,
               creator_id, creator_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, num, label, currency, amount, client,
              creator_id, creator_name, _now()))
        await conn.commit()
        return cur.lastrowid


async def set_message_id(req_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE z_requests SET message_id=? WHERE id=?", (message_id, req_id))
        await conn.commit()


async def get_request(req_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM z_requests WHERE id=?", (req_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_status(req_id: int, status: str, closed_by: str) -> bool:
    """Закрывает заявку, только если она ещё открыта. True — если получилось."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("""
            UPDATE z_requests SET status=?, closed_by=?, closed_at=?
            WHERE id=? AND status='open'
        """, (status, closed_by, _now(), req_id))
        await conn.commit()
        return cur.rowcount > 0


async def list_requests(chat_id: int, status: str, limit: int | None = None) -> list[dict]:
    order = "ASC" if status == "open" else "DESC"
    sql = f"SELECT * FROM z_requests WHERE chat_id=? AND status=? ORDER BY id {order}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, (chat_id, status)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def list_all(status: str, limit: int | None = None) -> list[dict]:
    order = "ASC" if status == "open" else "DESC"
    sql = f"""
        SELECT r.*, COALESCE(c.title, 'Чат ' || r.chat_id) AS chat_title
        FROM z_requests r LEFT JOIN z_chats c ON c.chat_id = r.chat_id
        WHERE r.status=? ORDER BY r.id {order}
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, (status,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def _ensure_settings(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS z_settings (key TEXT PRIMARY KEY, value TEXT)"
    )


async def set_hub(chat_id: int | None):
    async with aiosqlite.connect(DB_PATH) as conn:
        await _ensure_settings(conn)
        if chat_id is None:
            await conn.execute("DELETE FROM z_settings WHERE key='hub_chat'")
        else:
            await conn.execute("""
                INSERT INTO z_settings (key, value) VALUES ('hub_chat', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (str(chat_id),))
        await conn.commit()


async def get_hub() -> int | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await _ensure_settings(conn)
        async with conn.execute(
            "SELECT value FROM z_settings WHERE key='hub_chat'"
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else None        