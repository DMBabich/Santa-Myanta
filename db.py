import aiosqlite
from datetime import datetime


# ---------------- BASE INIT ----------------
async def init_db(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pairs(
            santa_id INTEGER PRIMARY KEY,
            child_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS schedules(
            hh INTEGER NOT NULL,
            mm INTEGER NOT NULL,
            PRIMARY KEY(hh, mm)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS sent_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            task_text TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")

        # состояние волн (ЕДИНСТВЕННАЯ версия)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS wave_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            wave_index INTEGER NOT NULL,
            active_group_idx INTEGER NOT NULL,
            is_initialized INTEGER NOT NULL
        )""")

        # группы волн
        await db.execute("""
        CREATE TABLE IF NOT EXISTS wave_groups (
            group_idx INTEGER,
            position INTEGER,
            tg_id INTEGER,
            PRIMARY KEY (group_idx, position)
        )""")

        # назначения волн
        await db.execute("""
        CREATE TABLE IF NOT EXISTS wave_assignments(
            wave_index INTEGER NOT NULL,
            active_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            emotion TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS used_tasks (
        user_id INTEGER,
        group_id INTEGER,
        task TEXT,
        UNIQUE(user_id, group_id, task)
         )""")

        await db.commit()


# ---------------- USERS ----------------
async def upsert_user(db_path: str, tg_id: int, username: str | None, full_name: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        INSERT INTO users(tg_id, username, full_name, is_active, created_at)
        VALUES(?, ?, ?, 1, ?)
        ON CONFLICT(tg_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            is_active=1
        """, (tg_id, username, full_name, datetime.utcnow().isoformat()))
        await db.commit()


async def set_inactive(db_path: str, tg_id: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE users SET is_active=0 WHERE tg_id=?", (tg_id,))
        await db.execute("DELETE FROM pairs WHERE santa_id=? OR child_id=?", (tg_id, tg_id))
        await db.commit()


async def get_active_users(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("""
        SELECT tg_id, username, full_name
        FROM users
        WHERE is_active=1
        ORDER BY created_at
        """)
        return await cur.fetchall()


async def get_user_label(db_path: str, tg_id: int) -> str:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT username, full_name FROM users WHERE tg_id=?",
            (tg_id,)
        )
        row = await cur.fetchone()

    if not row:
        return str(tg_id)

    username, full_name = row
    return f"{full_name}" + (f" (@{username})" if username else "")


# ---------------- SANTA ----------------
async def clear_pairs(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM pairs")
        await db.commit()


async def set_pair(db_path: str, santa_id: int, child_id: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        INSERT INTO pairs(santa_id, child_id, created_at)
        VALUES(?, ?, ?)
        ON CONFLICT(santa_id) DO UPDATE SET
            child_id=excluded.child_id,
            created_at=excluded.created_at
        """, (santa_id, child_id, datetime.utcnow().isoformat()))
        await db.commit()


async def get_child_for_santa(db_path: str, santa_id: int):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT child_id FROM pairs WHERE santa_id=?",
            (santa_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


# ---------------- TASKS ----------------
async def load_tasks_if_empty(db_path: str, tasks_file: str):
    import os
    if not os.path.exists(tasks_file):
        return

    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM tasks")
        (cnt,) = await cur.fetchone()
        if cnt > 0:
            return

        with open(tasks_file, "r", encoding="utf-8") as f:
            lines = [x.strip() for x in f if x.strip()]

        if not lines:
            return

        await db.executemany(
            "INSERT INTO tasks(text) VALUES(?)",
            [(t,) for t in lines]
        )
        await db.commit()


async def get_random_task(db_path: str) -> str | None:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT text FROM tasks ORDER BY RANDOM() LIMIT 1"
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def log_sent_task(db_path: str, tg_id: int, task_text: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO sent_tasks(tg_id, task_text, sent_at) VALUES(?,?,?)",
            (tg_id, task_text, datetime.utcnow().isoformat())
        )
        await db.commit()


# ---------------- SCHEDULE ----------------
async def add_schedule(db_path: str, hh: int, mm: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO schedules(hh, mm) VALUES(?,?)",
            (hh, mm)
        )
        await db.commit()


async def remove_schedule(db_path: str, hh: int, mm: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "DELETE FROM schedules WHERE hh=? AND mm=?",
            (hh, mm)
        )
        await db.commit()


async def list_schedules(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT hh, mm FROM schedules ORDER BY hh, mm"
        )
        return await cur.fetchall()


# ---------------- SETTINGS ----------------
async def set_setting(db_path: str, key: str, value: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        INSERT INTO settings(key, value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        await db.commit()


async def get_setting(db_path: str, key: str) -> str | None:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


# ---------------- WAVES (FIXED QUEUE) ----------------
async def reset_waves(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM wave_groups")
        await db.execute("DELETE FROM wave_assignments")
        await db.execute("""
            INSERT INTO wave_state(id, wave_index, active_group_idx, is_initialized)
            VALUES (1, 0, 0, 0)
            ON CONFLICT(id) DO UPDATE SET
                wave_index=0,
                active_group_idx=0,
                is_initialized=0
        """)
        await db.commit()


async def init_wave_queue(db_path: str, groups: list[list[int]]):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM wave_groups")

        for g_idx, group in enumerate(groups):
            for pos, tg_id in enumerate(group):
                await db.execute(
                    "INSERT INTO wave_groups(group_idx, position, tg_id) VALUES (?,?,?)",
                    (g_idx, pos, tg_id)
                )

        await db.execute("""
            INSERT INTO wave_state(id, wave_index, active_group_idx, is_initialized)
            VALUES (1, 1, 0, 1)
            ON CONFLICT(id) DO UPDATE SET
                wave_index=1,
                active_group_idx=0,
                is_initialized=1
        """)
        await db.commit()


async def get_wave_state_full(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("""
            SELECT wave_index, active_group_idx, is_initialized
            FROM wave_state WHERE id=1
        """)
        row = await cur.fetchone()
        return row if row else (0, 0, 0)


async def get_wave_groups(db_path: str) -> dict[int, list[int]]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("""
            SELECT group_idx, tg_id
            FROM wave_groups
            ORDER BY group_idx, position
        """)
        rows = await cur.fetchall()

    groups: dict[int, list[int]] = {}
    for g_idx, tg_id in rows:
        groups.setdefault(g_idx, []).append(tg_id)
    return groups


async def advance_wave(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT active_group_idx FROM wave_state WHERE id=1"
        )
        row = await cur.fetchone()
        if not row:
            return

        active_idx = row[0]
        cur2 = await db.execute("SELECT MAX(group_idx) FROM wave_groups")
        max_idx = (await cur2.fetchone())[0]

        next_idx = (active_idx + 1) % (max_idx + 1)

        await db.execute("""
            UPDATE wave_state
            SET active_group_idx = ?, wave_index = wave_index + 1
            WHERE id=1
        """, (next_idx,))
        await db.commit()


# ---------------- FULL RESET ----------------
async def full_reset(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM users")
        await db.execute("DELETE FROM pairs")
        await db.execute("DELETE FROM wave_groups")
        await db.execute("DELETE FROM wave_assignments")
        await db.execute("DELETE FROM sent_tasks")
        await db.execute("DELETE FROM schedules")
        await db.execute("DELETE FROM settings")

        await db.execute("""
            INSERT INTO wave_state(id, wave_index, active_group_idx, is_initialized)
            VALUES (1, 0, 0, 0)
            ON CONFLICT(id) DO UPDATE SET
                wave_index=0,
                active_group_idx=0,
                is_initialized=0
        """)
        await db.commit()

async def reload_tasks_from_file(db_path: str, tasks_file: str) -> int:
    import os
    if not os.path.exists(tasks_file):
        return 0

    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM tasks")

        with open(tasks_file, "r", encoding="utf-8") as f:
            lines = [x.strip() for x in f if x.strip()]

        if not lines:
            await db.commit()
            return 0

        await db.executemany(
            "INSERT INTO tasks(text) VALUES(?)",
            [(t,) for t in lines]
        )
        await db.commit()
        return len(lines)

# ---------------- WAVE ASSIGNMENTS ----------------
async def clear_wave_assignments(db_path: str, wave_index: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "DELETE FROM wave_assignments WHERE wave_index=?",
            (wave_index,)
        )
        await db.commit()


async def insert_wave_assignment(
    db_path: str,
    wave_index: int,
    active_id: int,
    target_id: int,
    emotion: str
):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO wave_assignments(
                wave_index, active_id, target_id, emotion
            )
            VALUES (?, ?, ?, ?)
            """,
            (wave_index, active_id, target_id, emotion)
        )
        await db.commit()


async def get_wave_assignments(db_path: str, wave_index: int):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT active_id, target_id, emotion
            FROM wave_assignments
            WHERE wave_index=?
            """,
            (wave_index,)
        )
        return await cur.fetchall()

async def get_used_tasks(db_path: str, user_id: int, group_idx: int) -> set[str]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT task FROM used_tasks WHERE user_id=? AND group_idx=?",
            (user_id, group_idx)
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def mark_task_used(db_path: str, user_id: int, group_idx: int, task: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO used_tasks(user_id, group_id, task) VALUES(?,?,?)",
            (user_id, group_idx, task)
        )
        await db.commit()



async def reset_used_tasks_for_group(db_path: str, group_idx: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "DELETE FROM used_tasks WHERE group_idx=?",
            (group_idx,)
        )
        await db.commit()
