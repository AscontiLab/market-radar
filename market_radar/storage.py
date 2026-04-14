from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_products (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    repo_url TEXT,
    objective TEXT,
    keywords_json TEXT NOT NULL,
    priority_signal_types_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_competitors (
    slug TEXT PRIMARY KEY,
    product_slug TEXT NOT NULL,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    relevance TEXT,
    source_urls_json TEXT NOT NULL,
    watch_for_json TEXT NOT NULL,
    FOREIGN KEY(product_slug) REFERENCES tracked_products(slug)
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_slug TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT,
    source_kind TEXT,
    fetched_at TEXT NOT NULL,
    status_code INTEGER,
    content_hash TEXT,
    title TEXT,
    body_excerpt TEXT,
    raw_path TEXT,
    UNIQUE(competitor_slug, source_url, fetched_at),
    FOREIGN KEY(competitor_slug) REFERENCES tracked_competitors(slug)
);

CREATE TABLE IF NOT EXISTS market_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_slug TEXT NOT NULL,
    competitor_slug TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    source_url TEXT NOT NULL,
    source_type TEXT,
    source_kind TEXT,
    detected_at TEXT NOT NULL,
    repo_fit REAL,
    market_strength REAL,
    actionability REAL,
    recommendation TEXT,
    detection_mode TEXT,
    evidence_json TEXT,
    UNIQUE(product_slug, competitor_slug, signal_type, title, detected_at),
    FOREIGN KEY(product_slug) REFERENCES tracked_products(slug),
    FOREIGN KEY(competitor_slug) REFERENCES tracked_competitors(slug)
);
"""

REQUIRED_COLUMNS = {
    "source_snapshots": {
        "source_type": "TEXT",
        "source_kind": "TEXT",
    },
    "market_signals": {
        "detection_mode": "TEXT",
        "evidence_json": "TEXT",
        "source_type": "TEXT",
        "source_kind": "TEXT",
        "llm_summary": "TEXT",
        "llm_confidence": "REAL",
        "llm_recommendation": "TEXT",
        "llm_keywords": "TEXT",
        "llm_model": "TEXT",
    }
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        migrate_db(connection)
        connection.commit()


def migrate_db(connection: sqlite3.Connection) -> None:
    for table_name, columns in REQUIRED_COLUMNS.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})")
        }
        for column_name, column_type in columns.items():
            if column_name in existing:
                continue
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )

    # Backfill: source_type und source_kind fuer bestehende Snapshots setzen
    connection.execute("""
        UPDATE source_snapshots
        SET source_type = 'github',
            source_kind = CASE
                WHEN source_url LIKE '%/readme' THEN 'readme'
                WHEN source_url LIKE '%/release' THEN 'release'
                ELSE 'page'
            END
        WHERE source_url LIKE 'github://%'
          AND source_type IS NULL
    """)
    connection.execute("""
        UPDATE source_snapshots
        SET source_type = 'web',
            source_kind = 'page'
        WHERE source_url NOT LIKE 'github://%'
          AND source_type IS NULL
    """)


def backfill_source_types(connection: sqlite3.Connection) -> int:
    """Backfill NULL source_type/source_kind in source_snapshots."""
    # GitHub-URLs: Typ github, Kind je nach Pfad (readme/release)
    connection.execute("""
        UPDATE source_snapshots
        SET source_type = 'github',
            source_kind = CASE
                WHEN source_url LIKE '%/readme' THEN 'readme'
                WHEN source_url LIKE '%/release' THEN 'release'
                ELSE 'page'
            END
        WHERE source_url LIKE 'github://%'
          AND (source_type IS NULL OR source_kind IS NULL)
    """)
    github_updated = connection.execute("SELECT changes()").fetchone()[0]

    # Alle anderen URLs: Typ web, Kind page
    connection.execute("""
        UPDATE source_snapshots
        SET source_type = 'web',
            source_kind = 'page'
        WHERE source_url NOT LIKE 'github://%'
          AND (source_type IS NULL OR source_kind IS NULL)
    """)
    web_updated = connection.execute("SELECT changes()").fetchone()[0]

    connection.commit()
    return github_updated + web_updated
