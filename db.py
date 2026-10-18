"""Работа с базой данных SQLite (это один файл bot.db рядом с ботом)."""
import json
import time

import aiosqlite

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    premium_until INTEGER NOT NULL DEFAULT 0      -- до какого момента (unix-время) действует премиум
);
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,                    -- кто создал розыгрыш
    channel_id INTEGER NOT NULL,
    channel_title TEXT NOT NULL,
    text TEXT NOT NULL,                           -- текст поста (HTML)
    photo_id TEXT,                                -- картинка, если есть
    extra_channels TEXT NOT NULL DEFAULT '[]',     -- каналы-партнёры (JSON-список)
    winners_count INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,                     -- когда подводить итоги (unix-время)
    message_id INTEGER,                           -- номер поста в канале
    status TEXT NOT NULL DEFAULT 'active'         -- active или finished
);
CREATE TABLE IF NOT EXISTS participants (
    giveaway_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, user_id)
);
CREATE TABLE IF NOT EXISTS payments (
    charge_id TEXT PRIMARY KEY,                   -- нужен, если придётся вернуть деньги
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    paid_at INTEGER NOT NULL
);
"""


def _connect():
    return aiosqlite.connect(DB_PATH)


async def init():
    async with _connect() as db:
        await db.executescript(SCHEMA)
        # Если база создана старой версией бота, добавляем новую колонку.
        cur = await db.execute("PRAGMA table_info(giveaways)")
        columns = [row[1] for row in await cur.fetchall()]
        if "extra_channels" not in columns:
            await db.execute("ALTER TABLE giveaways ADD COLUMN extra_channels TEXT NOT NULL DEFAULT '[]'")
        await db.commit()


# ---------- Премиум ----------

async def premium_until(user_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
    return row[0] if row else 0


async def is_premium(user_id: int) -> bool:
    return await premium_until(user_id) > time.time()


async def add_payment(user_id: int, charge_id: str, amount: int, until: int):
    async with _connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO payments VALUES (?, ?, ?, ?)",
            (charge_id, user_id, amount, int(time.time())),
        )
        await db.execute(
            "INSERT INTO users (user_id, premium_until) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET premium_until = MAX(premium_until, excluded.premium_until)",
            (user_id, until),
        )
        await db.commit()


# ---------- Розыгрыши ----------

async def create_giveaway(owner_id, channel_id, channel_title, text, photo_id, winners_count, ends_at,
                          extra_channels: list | None = None) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO giveaways (owner_id, channel_id, channel_title, text, photo_id, winners_count, ends_at, "
            "extra_channels) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, channel_id, channel_title, text, photo_id, winners_count, ends_at,
             json.dumps(extra_channels or [], ensure_ascii=False)),
        )
        await db.commit()
        return cur.lastrowid


async def set_message_id(giveaway_id: int, message_id: int):
    async with _connect() as db:
        await db.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
        await db.commit()


async def delete_giveaway(giveaway_id: int):
    async with _connect() as db:
        await db.execute("DELETE FROM giveaways WHERE id = ?", (giveaway_id,))
        await db.commit()


async def get_giveaway(giveaway_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        return await cur.fetchone()


async def active_giveaways(owner_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT g.*, (SELECT COUNT(*) FROM participants p WHERE p.giveaway_id = g.id) AS members "
            "FROM giveaways g WHERE owner_id = ? AND status = 'active' ORDER BY ends_at",
            (owner_id,),
        )
        return await cur.fetchall()


async def due_giveaways():
    """Розыгрыши, у которых наступило время подвести итоги."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM giveaways WHERE status = 'active' AND message_id IS NOT NULL AND ends_at <= ?",
            (int(time.time()),),
        )
        return await cur.fetchall()


async def finish(giveaway_id: int):
    async with _connect() as db:
        await db.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
        await db.commit()


# ---------- Участники ----------

async def add_participant(giveaway_id: int, user_id: int, full_name: str) -> bool:
    """Добавляет участника. Возвращает False, если он уже участвует."""
    async with _connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO participants VALUES (?, ?, ?, ?)",
            (giveaway_id, user_id, full_name, int(time.time())),
        )
        await db.commit()
        return cur.rowcount > 0


async def count_participants(giveaway_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
        return (await cur.fetchone())[0]


async def participants(giveaway_id: int):
    async with _connect() as db:
        cur = await db.execute("SELECT user_id, full_name FROM participants WHERE giveaway_id = ?", (giveaway_id,))
        return await cur.fetchall()
