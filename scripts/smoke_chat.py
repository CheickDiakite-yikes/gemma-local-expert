from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import AssistantMode, ConversationCreateRequest, ConversationTurnRequest


async def run_turn(prompt: str, settings: Settings) -> None:
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Smoke Chat", mode=AssistantMode.RESEARCH)
        )
        turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text=prompt,
        )
        async for event in container.orchestrator.stream_turn(turn):
            print(json.dumps(event.model_dump(), default=str))
    finally:
        container.store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an end-to-end conversation smoke test.")
    parser.add_argument(
        "--prompt",
        default="Summarize the trip checklist and cite the most relevant local source.",
    )
    parser.add_argument("--db-path", default="data/smoke-chat.db")
    parser.add_argument("--backend", choices=["mock", "mlx"], default="mock")
    parser.add_argument(
        "--model-source",
        "--assistant-model-source",
        dest="assistant_model_source",
        default=None,
    )
    parser.add_argument(
        "--model-name",
        "--assistant-model-name",
        dest="assistant_model_name",
        default="gemma-4-e4b-it",
    )
    parser.add_argument("--embedding-backend", choices=["hash", "mlx"], default="hash")
    parser.add_argument("--embedding-model-source", default=None)
    parser.add_argument("--embedding-model-name", default="embeddinggemma-300m")
    parser.add_argument("--max-tokens", type=int, default=220)
    args = parser.parse_args()

    settings = Settings(
        database_path=args.db_path,
        default_assistant_model=args.assistant_model_name,
        assistant_backend=args.backend,
        assistant_model_source=args.assistant_model_source,
        assistant_max_tokens=args.max_tokens,
        default_embedding_model=args.embedding_model_name,
        embedding_backend=args.embedding_backend,
        embedding_model_source=args.embedding_model_source,
    )
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_turn(args.prompt, settings))


if __name__ == "__main__":
    main()
