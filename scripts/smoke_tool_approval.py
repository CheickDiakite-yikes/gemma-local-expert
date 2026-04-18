from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise approval-gated tool execution.")
    parser.add_argument(
        "--prompt",
        default="Create a checklist for tomorrow's village visits.",
    )
    parser.add_argument("--db-path", default="data/smoke-tool-approval.db")
    args = parser.parse_args()

    settings = Settings(database_path=args.db_path)
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(settings))

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Tool Smoke", "mode": "field"},
    ).json()

    turn_response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": args.prompt,
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {
                "style": "concise",
                "citations": True,
                "audio_reply": False,
            },
        },
    )
    print("Turn Stream:")
    print(turn_response.text)

    approval_line = next(
        line
        for line in turn_response.text.splitlines()
        if '"type":"approval.required"' in line
    )
    approval_event = json.loads(approval_line)
    approval_id = approval_event["payload"]["id"]

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    print("\nApproval Result:")
    print(json.dumps(approval_response.json(), indent=2))

    notes = client.get("/v1/notes").json()
    tasks = client.get("/v1/tasks").json()
    print("\nNotes:")
    print(json.dumps(notes, indent=2))
    print("\nTasks:")
    print(json.dumps(tasks, indent=2))


if __name__ == "__main__":
    main()
