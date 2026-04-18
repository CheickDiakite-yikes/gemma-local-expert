from __future__ import annotations

from engine.config.settings import load_settings
from engine.persistence.migrations import apply_migrations


def main() -> None:
    settings = load_settings()
    apply_migrations(settings.database_path)
    print(f"Applied migrations to {settings.database_path}")


if __name__ == "__main__":
    main()
