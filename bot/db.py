from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    weight_kg REAL NOT NULL,
    start_weight_kg REAL NOT NULL,
    target_kg REAL NOT NULL,
    height_cm REAL NOT NULL,
    age INTEGER NOT NULL,
    sex TEXT NOT NULL CHECK (sex IN ('m', 'f')),
    activity INTEGER NOT NULL CHECK (activity BETWEEN 1 AND 5)
);

-- Настройки хранятся отдельно: сводки работают и до заполнения профиля.
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    morning_time TEXT NOT NULL DEFAULT '08:00',
    evening_time TEXT NOT NULL DEFAULT '21:00',
    autocarry INTEGER NOT NULL DEFAULT 1,
    last_morning TEXT,
    last_evening TEXT
);
INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    grams REAL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    carbs REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS meals_day ON meals (day);

CREATE TABLE IF NOT EXISTS water (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    ml INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS water_day ON water (day);

CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    kg REAL NOT NULL,
    fat_pct REAL,
    muscle_kg REAL
);
CREATE INDEX IF NOT EXISTS weights_day ON weights (day);

CREATE TABLE IF NOT EXISTS activity (
    day TEXT PRIMARY KEY,
    steps INTEGER,
    active_kcal REAL,
    workouts TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('once', 'daily', 'weekly')),
    date TEXT,
    weekdays TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS task_log (
    task_id INTEGER NOT NULL REFERENCES tasks (id),
    day TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    PRIMARY KEY (task_id, day)
);

CREATE TABLE IF NOT EXISTS pills (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    dose TEXT NOT NULL,
    per_dose REAL NOT NULL DEFAULT 1,
    stock REAL,  -- NULL: остаток не отслеживается
    active INTEGER NOT NULL DEFAULT 1
);

-- Расписание. Таблетки и обычные напоминания используют один механизм.
CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('pill', 'reminder')),
    pill_id INTEGER REFERENCES pills (id),
    text TEXT,
    time TEXT NOT NULL,
    weekdays TEXT NOT NULL DEFAULT '',  -- '' значит каждый день
    date TEXT,  -- если задано, срабатывает один раз
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

-- Конкретное срабатывание за конкретный день. UNIQUE не даёт создать дубль,
-- а хранение в базе позволяет продолжить работу после перезапуска.
CREATE TABLE IF NOT EXISTS alarm_events (
    id INTEGER PRIMARY KEY,
    alarm_id INTEGER NOT NULL REFERENCES alarms (id),
    day TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'skipped', 'missed', 'cancelled')),
    next_at INTEGER,  -- когда отправить сообщение; NULL значит ничего не отправлять
    pings INTEGER NOT NULL DEFAULT 0,
    message_id INTEGER,
    resolved_at INTEGER,
    UNIQUE (alarm_id, day)
);
CREATE INDEX IF NOT EXISTS alarm_events_due ON alarm_events (status, next_at);
"""


async def connect(path: str) -> aiosqlite.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    await db.executescript(SCHEMA)
    await db.commit()
    return db
