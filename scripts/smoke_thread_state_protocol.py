from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_sample_workspace(root: Path) -> None:
    (root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )
    (root / "ops-notes.md").write_text(
        "Ops notes\n"
        "Keep the thread focused on architecture and approval discipline.\n",
        encoding="utf-8",
    )


def tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def parse_stream_events(response_text: str) -> list[dict]:
    return [json.loads(line) for line in response_text.splitlines() if line.strip()]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="field-assistant-thread-protocol-") as temp_dir:
        temp_root = Path(temp_dir)
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir()
        build_sample_workspace(workspace_root)

        settings = Settings(
            database_path=str(temp_root / "thread-state-protocol.db"),
            workspace_root=str(workspace_root),
            asset_storage_dir=str(temp_root / "uploads"),
        )
        client = TestClient(create_app(settings))

        print("== Thread / item / state protocol smoke ==")
        print(f"Workspace root: {workspace_root}")

        conversation = client.post(
            "/v1/conversations",
            json={"title": "Thread protocol smoke", "mode": "research"},
        ).json()
        require(bool(conversation.get("id")), "Conversation creation failed.")

        first_turn = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": "Create a report summarizing the current field assistant architecture.",
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
            },
        )
        require(first_turn.status_code == 200, "Initial report turn failed.")
        first_events = parse_stream_events(first_turn.text)
        print("\nInitial report stream:")
        print(first_turn.text)

        tool_proposed = next((event for event in first_events if event["type"] == "tool.proposed"), None)
        approval_required = next((event for event in first_events if event["type"] == "approval.required"), None)
        require(tool_proposed is not None, "Missing tool.proposed event on report turn.")
        require(approval_required is not None, "Missing approval.required event on report turn.")
        require(tool_proposed["payload"]["item"]["kind"] == "tool_proposal", "tool.proposed did not carry a tool_proposal item.")
        require(approval_required["payload"]["item"]["kind"] == "approval", "approval.required did not carry an approval item.")
        require(
            approval_required["payload"].get("work_product_item", {}).get("kind") == "work_product",
            "approval.required did not carry a work_product item.",
        )

        turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()
        require(bool(turns), "Turns endpoint returned no turns.")
        latest_turn_id = turns[-1]["id"]

        steer = client.post(
            f"/v1/conversations/{conversation['id']}/steer",
            json={"instruction": "Keep the thread focused on architecture and approval discipline."},
        )
        require(steer.status_code == 200, "Steer request failed.")
        compact = client.post(
            f"/v1/conversations/{conversation['id']}/compact",
            json={"up_to_turn_id": latest_turn_id},
        )
        require(compact.status_code == 200, "Compact request failed.")

        state_after_controls = client.get(f"/v1/conversations/{conversation['id']}/state").json()
        print("\nState after steer + compact:")
        print(json.dumps(state_after_controls, indent=2))
        require(
            any(item["kind"] == "steer" for item in state_after_controls["items"]),
            "Conversation state did not retain the steer item.",
        )
        require(
            any(item["kind"] == "compaction_marker" for item in state_after_controls["items"]),
            "Conversation state did not retain the compaction marker.",
        )
        require(
            any(item["kind"] == "work_product" for item in state_after_controls["items"]),
            "Conversation state did not retain the work_product item.",
        )

        workspace_turn = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": "Search this workspace and summarize the field assistant docs.",
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
            },
        )
        require(workspace_turn.status_code == 200, "Workspace summarize turn failed.")
        print("\nWorkspace summarize stream:")
        print(workspace_turn.text)

        runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
        require(bool(runs), "Expected at least one agent run after workspace summarize turn.")
        require(
            "Keep the thread focused on architecture and approval discipline." in runs[-1]["goal"],
            "Latest run goal did not include the steering instruction.",
        )

        forked = client.post(
            f"/v1/conversations/{conversation['id']}/fork",
            json={"title": "Thread protocol fork", "up_to_turn_id": latest_turn_id},
        )
        require(forked.status_code == 200, "Fork request failed.")
        forked_conversation = forked.json()
        print("\nFork result:")
        print(json.dumps(forked_conversation, indent=2))
        require(forked_conversation["parent_conversation_id"] == conversation["id"], "Forked conversation lost parent lineage.")
        require(forked_conversation["forked_from_turn_id"] == latest_turn_id, "Forked conversation lost turn lineage.")

        rollback = client.post(
            f"/v1/conversations/{conversation['id']}/rollback",
            json={"up_to_turn_id": latest_turn_id},
        )
        require(rollback.status_code == 200, "Rollback request failed.")
        rolled_back = rollback.json()
        print("\nRollback result:")
        print(json.dumps(rolled_back, indent=2))
        require(rolled_back["parent_conversation_id"] == conversation["id"], "Rollback result lost parent lineage.")

        archived_source = client.get(f"/v1/conversations/{conversation['id']}").json()
        require(archived_source["archived_at"] is not None, "Rollback did not archive the source conversation.")

        image_conversation = client.post(
            "/v1/conversations",
            json={"title": "Direct tool protocol", "mode": "general"},
        ).json()
        image_asset = client.post(
            "/v1/assets/upload",
            data={"care_context": "general"},
            files={"file": ("xray.png", tiny_png_bytes(), "image/png")},
        ).json()["asset"]

        tool_turn = client.post(
            f"/v1/conversations/{image_conversation['id']}/turns",
            json={
                "conversation_id": image_conversation["id"],
                "mode": "general",
                "text": "Do a segmented heatmap layering of this x-ray image.",
                "asset_ids": [image_asset["id"]],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
            },
        )
        require(tool_turn.status_code == 200, "Direct tool turn failed.")
        print("\nDirect tool stream:")
        print(tool_turn.text)

        tool_events = parse_stream_events(tool_turn.text)
        tool_proposal_event = next((event for event in tool_events if event["type"] == "tool.proposed"), None)
        tool_completed_event = next((event for event in tool_events if event["type"] == "tool.completed"), None)
        require(tool_proposal_event is not None, "Missing tool.proposed event for direct tool execution.")
        require(tool_completed_event is not None, "Missing tool.completed event for direct tool execution.")
        require(tool_proposal_event["payload"]["item"]["kind"] == "tool_proposal", "Direct tool proposal was not item-backed.")
        require(tool_completed_event["payload"]["item"]["kind"] == "tool_result", "Direct tool completion was not item-backed.")

        direct_state = client.get(f"/v1/conversations/{image_conversation['id']}/state").json()
        print("\nDirect tool conversation state:")
        print(json.dumps(direct_state, indent=2))
        require(
            any(item["kind"] == "tool_proposal" for item in direct_state["items"]),
            "Direct tool conversation state is missing tool_proposal item.",
        )
        require(
            any(item["kind"] == "tool_result" for item in direct_state["items"]),
            "Direct tool conversation state is missing tool_result item.",
        )

        print("\nThread / item / state protocol smoke: PASS")


if __name__ == "__main__":
    main()
