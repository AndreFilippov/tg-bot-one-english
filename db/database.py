import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    level TEXT DEFAULT 'A1',
    current_topic TEXT DEFAULT 'alphabet',
    voice TEXT DEFAULT 'en-US-AriaNeural',
    speech_rate INTEGER DEFAULT -20,
    show_text INTEGER DEFAULT 1,
    reminder_time TEXT,
    onboarded INTEGER DEFAULT 0,
    last_test TEXT,
    nick TEXT,
    age INTEGER,
    city TEXT,
    occupation TEXT,
    goal TEXT,
    interests TEXT DEFAULT '',
    facts TEXT DEFAULT '[]',
    daily_goal INTEGER DEFAULT 20,
    partner_role TEXT DEFAULT 'friend',
    ru_help INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    translation TEXT NOT NULL,
    example TEXT DEFAULT '',
    ease REAL DEFAULT 2.5,
    interval INTEGER DEFAULT 0,
    reps INTEGER DEFAULT 0,
    due_date TEXT DEFAULT (date('now')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, word)
);
CREATE TABLE IF NOT EXISTS topic_progress (
    user_id INTEGER NOT NULL,
    topic_id TEXT NOT NULL,
    correct INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    status TEXT DEFAULT 'in_progress',
    PRIMARY KEY (user_id, topic_id)
);
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT DEFAULT 'grammar',
    wrong TEXT,
    right TEXT,
    explanation TEXT,
    session_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    scenario TEXT,
    turns INTEGER DEFAULT 0,
    history TEXT DEFAULT '[]',
    summary TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    points INTEGER DEFAULT 0,
    lessons INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS pending_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT NOT NULL,
    model TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (day, model)
);
CREATE TABLE IF NOT EXISTS fsm (
    key TEXT PRIMARY KEY,
    state TEXT,
    data TEXT DEFAULT '{}'
);
"""


# Колонки, добавленные после первой версии: (таблица, колонка, определение)
MIGRATIONS = [
    ("users", "onboarded", "INTEGER DEFAULT 0"),
    ("users", "last_test", "TEXT"),
    ("users", "nick", "TEXT"),
    ("users", "age", "INTEGER"),
    ("users", "city", "TEXT"),
    ("users", "occupation", "TEXT"),
    ("users", "goal", "TEXT"),
    ("users", "interests", "TEXT DEFAULT ''"),
    ("users", "facts", "TEXT DEFAULT '[]'"),
    ("users", "daily_goal", "INTEGER DEFAULT 20"),
    ("users", "partner_role", "TEXT DEFAULT 'friend'"),
    ("users", "ru_help", "INTEGER DEFAULT 1"),
]


async def connect(path) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        cur = await db.execute(f"PRAGMA table_info({table})")
        if column not in {r["name"] for r in await cur.fetchall()}:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    await db.commit()
    return db
