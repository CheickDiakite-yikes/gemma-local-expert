from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import LibrarySearchRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a retrieval-only smoke test.")
    parser.add_argument(
        "--query",
        default="watch for dehydration weakness while giving frequent sips",
    )
    parser.add_argument("--db-path", default="data/smoke-retrieval.db")
    parser.add_argument("--backend", choices=["hash", "mlx"], default="hash")
    parser.add_argument("--model-source", default=None)
    parser.add_argument("--model-name", default="embeddinggemma-300m")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    settings = Settings(
        database_path=args.db_path,
        default_embedding_model=args.model_name,
        embedding_backend=args.backend,
        embedding_model_source=args.model_source,
    )
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)

    container = build_container(settings)
    try:
        results = container.retrieval.search(
            LibrarySearchRequest(query=args.query, limit=args.limit)
        )
        print(json.dumps([result.model_dump(mode="json") for result in results], indent=2))
    finally:
        container.store.close()


if __name__ == "__main__":
    main()
