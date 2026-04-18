from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import AssistantMode, ConversationTurnRequest, LibrarySearchRequest


def run_routing_eval() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(database_path=str(Path(temp_dir) / "routing-eval.db"))
        container = build_container(settings)
        cases = json.loads(Path("evals/routing/sample_cases.json").read_text(encoding="utf-8"))
        failures = 0

        for case in cases:
            request = ConversationTurnRequest(
                conversation_id="conv_eval",
                mode=AssistantMode(case["mode"]),
                text=case["text"],
                asset_ids=case["asset_ids"],
                enabled_knowledge_pack_ids=case["enabled_knowledge_pack_ids"],
            )
            route = container.router.decide(request)
            actual = {
                "needs_retrieval": route.needs_retrieval,
                "specialist_model": route.specialist_model,
                "proposed_tool": route.proposed_tool,
            }
            if actual != case["expected"]:
                failures += 1
                print(f"FAIL {case['id']}: expected={case['expected']} actual={actual}")
            else:
                print(f"PASS {case['id']}")

        container.store.close()
        return failures


def run_retrieval_eval() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(database_path=str(Path(temp_dir) / "retrieval-eval.db"))
        container = build_container(settings)
        cases = json.loads(Path("evals/retrieval/sample_cases.json").read_text(encoding="utf-8"))
        failures = 0

        for case in cases:
            request = LibrarySearchRequest(
                query=case["query"],
                enabled_knowledge_pack_ids=case["enabled_knowledge_pack_ids"],
            )
            results = container.retrieval.search(request)
            top_label = results[0].label if results else None
            if top_label != case["expected_top_label"]:
                failures += 1
                print(
                    f"FAIL {case['id']}: expected_top_label={case['expected_top_label']} "
                    f"actual={top_label}"
                )
            else:
                print(f"PASS {case['id']}")

        container.store.close()
        return failures


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"routing", "retrieval"}:
        print("Usage: python scripts/run_local_eval.py [routing|retrieval]")
        return 2

    suite = sys.argv[1]
    return run_routing_eval() if suite == "routing" else run_retrieval_eval()


if __name__ == "__main__":
    raise SystemExit(main())
