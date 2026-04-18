from __future__ import annotations

import json
from pathlib import Path

from engine.api.app import create_app


def main() -> None:
    app = create_app()
    output_path = Path("contracts/openapi/field-assistant.openapi.json")
    output_path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
