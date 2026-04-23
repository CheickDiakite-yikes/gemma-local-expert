from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


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
    require(turn_response.status_code == 200, "Turn request failed.")

    lines = [json.loads(line) for line in turn_response.text.splitlines() if line.strip()]
    proposed_event = next((line for line in lines if line["type"] == "tool.proposed"), None)
    approval_event = next((line for line in lines if line["type"] == "approval.required"), None)
    require(proposed_event is not None, "Expected a tool.proposed event.")
    require(approval_event is not None, "Expected an approval.required event.")
    require(
        proposed_event["payload"]["item"]["kind"] == "tool_proposal",
        "tool.proposed did not carry a canonical tool_proposal item snapshot.",
    )
    require(
        approval_event["payload"]["item"]["kind"] == "approval",
        "approval.required did not carry a canonical approval item snapshot.",
    )
    require(
        approval_event["payload"].get("work_product_item", {}).get("kind") == "work_product",
        "approval.required did not carry a canonical work_product item snapshot.",
    )
    require(
        approval_event["payload"]["category"] == "durable_write",
        "Approval category was not durable_write.",
    )
    require(
        "durable_output" in approval_event["payload"]["permission_classes"],
        "Approval permission classes did not include durable_output.",
    )

    approval_id = approval_event["payload"]["id"]

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    print("\nApproval Result:")
    print(json.dumps(approval_response.json(), indent=2))
    require(approval_response.status_code == 200, "Approval decision failed.")
    approval = approval_response.json()
    require(approval["status"] == "executed", "Approval was not executed.")
    require(approval.get("item", {}).get("kind") == "approval", "Approval response did not return the canonical approval item.")
    require(
        approval.get("work_product_item", {}).get("kind") == "work_product",
        "Approval response did not return the canonical work_product item.",
    )
    require(
        approval.get("item", {}).get("payload", {}).get("approval", {}).get("status") == "executed",
        "Approval item snapshot was not updated to executed.",
    )
    require(
        approval.get("work_product_item", {}).get("payload", {}).get("approval", {}).get("status") == "executed",
        "Work product item snapshot was not updated to executed.",
    )

    notes = client.get("/v1/notes").json()
    tasks = client.get("/v1/tasks").json()
    state = client.get(f"/v1/conversations/{conversation['id']}/state").json()
    print("\nNotes:")
    print(json.dumps(notes, indent=2))
    print("\nTasks:")
    print(json.dumps(tasks, indent=2))
    print("\nConversation State:")
    print(json.dumps(state, indent=2))

    require(bool(notes), "Expected the approval path to create at least one note/checklist.")
    require(notes[0]["kind"] == "checklist", "Expected the created note kind to be checklist.")
    require(
        any(item["kind"] == "tool_proposal" for item in state["items"]),
        "Conversation state did not retain the tool_proposal item.",
    )
    require(
        any(
            item["kind"] == "approval"
            and item["payload"]["approval"]["id"] == approval_id
            and item["payload"]["approval"]["status"] == "executed"
            for item in state["items"]
        ),
        "Conversation state did not retain the executed approval item.",
    )
    require(
        any(
            item["kind"] == "work_product"
            and item["payload"]["approval_id"] == approval_id
            and item["payload"]["approval"]["status"] == "executed"
            for item in state["items"]
        ),
        "Conversation state did not retain the executed work_product item.",
    )
    print("\nSmoke tool approval: PASS")


if __name__ == "__main__":
    main()
