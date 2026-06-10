import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "eastpay.db")


async def init_db():
    """Создаёт все таблицы при первом запуске."""
    async with aiosqlite.connect(DB_PATH) as db:
        # ── Балансы (/b команды) ──────────────────────────────────────────────
        await db.execute("""
                    CREATE TABLE IF NOT EXISTS tracked_addresses (
                        chat_id INTEGER NOT NULL,
                        address TEXT    NOT NULL,
                        name    TEXT    DEFAULT '',
                        PRIMARY KEY (chat_id, address)
                    )
                """)
                # Добавляем колонку name если её нет (для существующих БД)
        try:
            await db.execute("ALTER TABLE tracked_addresses ADD COLUMN name TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass
        # ── История операций по балансам ──────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER NOT NULL,
                currency  TEXT    NOT NULL COLLATE NOCASE,
                delta     REAL    NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ── Отслеживаемые BTC-адреса ──────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracked_addresses (
                chat_id INTEGER NOT NULL,
                address TEXT    NOT NULL,
                PRIMARY KEY (chat_id, address)
            )
        """)
        # ── Последние известные tx для адреса (чтоб не дублировать уведомления)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS address_last_tx (
                address TEXT PRIMARY KEY,
                last_tx TEXT
            )
        """)
        # ── Курсы валют (вносит администратор) ───────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS currency_rates (
                currency    TEXT    NOT NULL,
                type        TEXT    NOT NULL,   -- 'cash' | 'transfer'
                rate        REAL    NOT NULL,
                updated_by  INTEGER,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (currency, type)
            )
        """)
        # ── Реестр сделок ─────────────────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                manager_id    INTEGER NOT NULL,
                manager_name  TEXT,
                chat_id       INTEGER NOT NULL,
                currency      TEXT    NOT NULL,
                currency_type TEXT    NOT NULL,   -- 'cash' | 'transfer'
                city          TEXT    NOT NULL,
                amount_foreign REAL   NOT NULL,
                amount_rub    REAL    NOT NULL,
                rate_used     REAL    NOT NULL,
                status        TEXT    DEFAULT 'pending',  -- pending|accepted|rejected
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ── Личные формулы пользователей ─────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_formulas (
                user_id   INTEGER NOT NULL,
                shortcut  TEXT    NOT NULL COLLATE NOCASE,
                formula   TEXT    NOT NULL,
                PRIMARY KEY (user_id, shortcut)
            )
        """)
        await db.commit()


# ════════════════════════════════════════════════════════════════════════════
#  БАЛАНСЫ
# ════════════════════════════════════════════════════════════════════════════

async def get_all_balances(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT currency, amount FROM balances WHERE chat_id=? ORDER BY currency",
            (chat_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_balance(chat_id: int, currency: str) -> float | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM balances WHERE chat_id=? AND currency=? COLLATE NOCASE",
            (chat_id, currency.upper())
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def update_balance(chat_id: int, currency: str, delta: float):
    currency = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO balances (chat_id, currency, amount) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, currency) DO UPDATE SET amount = amount + excluded.amount
        """, (chat_id, currency, delta))
        await db.execute(
            "INSERT INTO balance_history (chat_id, currency, delta) VALUES (?, ?, ?)",
            (chat_id, currency, delta)
        )
        await db.commit()


async def set_balance(chat_id: int, currency: str, amount: float):
    currency = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO balances (chat_id, currency, amount) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, currency) DO UPDATE SET amount = excluded.amount
        """, (chat_id, currency, amount))
        await db.commit()


async def delete_balance(chat_id: int, currency: str):
    currency = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM balances WHERE chat_id=? AND currency=?",
            (chat_id, currency)
        )
        await db.commit()


async def get_balance_history(chat_id: int, currency: str, limit: int = 6) -> list[dict]:
    currency = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT delta, created_at FROM balance_history
            WHERE chat_id=? AND currency=?
            ORDER BY id DESC LIMIT ?
        """, (chat_id, currency, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_total_turnover(chat_id: int, currency: str) -> float:
    currency = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COALESCE(SUM(ABS(delta)), 0)
            FROM balance_history WHERE chat_id=? AND currency=?
        """, (chat_id, currency)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0


# ════════════════════════════════════════════════════════════════════════════
#  BTC АДРЕСА
# ════════════════════════════════════════════════════════════════════════════

async def add_tracked_address(chat_id: int, address: str, name: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tracked_addresses (chat_id, address, name) VALUES (?, ?, ?)",
            (chat_id, address, name)
        )
        await db.commit()


async def get_tracked_wallets(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT address, name FROM tracked_addresses WHERE chat_id=?", (chat_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def remove_tracked_address(chat_id: int, address: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM tracked_addresses WHERE chat_id=? AND address=?",
            (chat_id, address)
        )
        await db.commit()


async def get_tracked_addresses(chat_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT address FROM tracked_addresses WHERE chat_id=?", (chat_id,)
        ) as cur:
            return [r[0] for r in await cur.fetchall()]

async def get_all_tracked() -> list[tuple[int, str, str]]:
    """Все (chat_id, address, name) для фонового мониторинга."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id, address, COALESCE(name, '') FROM tracked_addresses") as cur:
            return await cur.fetchall()


async def get_last_tx(address: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_tx FROM address_last_tx WHERE address=?", (address,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_last_tx(address: str, tx_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO address_last_tx (address, last_tx) VALUES (?, ?)",
            (address, tx_id)
        )
        await db.commit()


# ════════════════════════════════════════════════════════════════════════════
#  КУРСЫ ВАЛЮТ
# ════════════════════════════════════════════════════════════════════════════

async def set_currency_rate(currency: str, type_: str, rate: float, admin_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO currency_rates (currency, type, rate, updated_by, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(currency, type) DO UPDATE SET
                rate=excluded.rate,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
        """, (currency.upper(), type_, rate, admin_id))
        await db.commit()


async def get_currency_rate(currency: str, type_: str) -> float | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT rate FROM currency_rates WHERE currency=? AND type=?",
            (currency.upper(), type_)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_all_currency_rates() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT currency, type, rate, updated_at FROM currency_rates ORDER BY currency, type"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ════════════════════════════════════════════════════════════════════════════
#  СДЕЛКИ
# ════════════════════════════════════════════════════════════════════════════

async def create_deal(manager_id: int, manager_name: str, chat_id: int,
                      currency: str, currency_type: str, city: str,
                      amount_foreign: float, amount_rub: float, rate_used: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO deals
              (manager_id, manager_name, chat_id, currency, currency_type, city,
               amount_foreign, amount_rub, rate_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (manager_id, manager_name, chat_id, currency.upper(), currency_type,
              city, amount_foreign, amount_rub, rate_used))
        await db.commit()
        return cur.lastrowid


async def update_deal_status(deal_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE deals SET status=? WHERE id=?", (status, deal_id)
        )
        await db.commit()


async def get_deal(deal_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deals WHERE id=?", (deal_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ════════════════════════════════════════════════════════════════════════════
#  ЛИЧНЫЕ ФОРМУЛЫ
# ════════════════════════════════════════════════════════════════════════════

async def save_formula(user_id: int, shortcut: str, formula: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_formulas (user_id, shortcut, formula) VALUES (?, ?, ?)
            ON CONFLICT(user_id, shortcut) DO UPDATE SET formula=excluded.formula
        """, (user_id, shortcut.lower(), formula))
        await db.commit()


async def get_formula(user_id: int, shortcut: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT formula FROM user_formulas WHERE user_id=? AND shortcut=? COLLATE NOCASE",
            (user_id, shortcut.lower())
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_all_formulas(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT shortcut, formula FROM user_formulas WHERE user_id=? ORDER BY shortcut",
            (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def delete_formula(user_id: int, shortcut: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_formulas WHERE user_id=? AND shortcut=? COLLATE NOCASE",
            (user_id, shortcut.lower())
        )
        await db.commit()
