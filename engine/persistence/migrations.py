from __future__ import annotations

import sqlite3
from pathlib import Path

from engine.contracts.api import utc_now


def apply_migrations(database_path: str) -> None:
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    migrations_dir = Path("data/migrations")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

        for migration in sorted(migrations_dir.glob("*.sql")):
            if migration.name in applied_versions:
                continue
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (migration.name, utc_now().isoformat()),
            )
            connection.commit()
    finally:
        connection.close()
