from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def grounded_refinement(title: str, content: str) -> tuple[str, str]:
    refined_title = f"{title} (reviewed)"
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    files_reviewed_start = next((index for index, line in enumerate(lines) if line.lower().startswith("files reviewed:")), None)
    if files_reviewed_start is not None:
        keep = lines[: files_reviewed_start + 2]
    else:
        keep = lines[:4]
    refined_content = "\n".join(keep).strip()
    return refined_title, refined_content


def build_sample_workspace(root: Path) -> None:
    docs = root / "field-docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "field-prep.md").write_text(
        (
            "Field prep checklist\n"
            "Pack oral rehydration salts\n"
            "Pack backup batteries\n"
            "Carry printed route sheets\n"
        ),
        encoding="utf-8",
    )
    (docs / "contacts.txt").write_text(
        (
            "Translator contact sheet\n"
            "Village route: Mako junction -> north clinic -> market school\n"
        ),
        encoding="utf-8",
    )
    (root / "README-notes.md").write_text(
        "Local notes about visit sequencing and morning briefing structure.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise the bounded workspace agent.")
    parser.add_argument("--mode", choices=["summarize", "brief"], default="summarize")
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--db-path", default="data/smoke-workspace-agent.db")
    parser.add_argument(
        "--steer",
        default="",
        help="Optional thread steering instruction to apply before the workspace turn.",
    )
    args = parser.parse_args()

    if args.workspace_root:
        workspace_root = Path(args.workspace_root).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_root = Path(tempfile.mkdtemp(prefix="field-agent-smoke-"))
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        build_sample_workspace(workspace_root)

    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_path=args.db_path,
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Workspace Agent Smoke", "mode": "research"},
    ).json()
    require(bool(conversation.get("id")), "Conversation creation failed.")

    if args.steer.strip():
        steer_response = client.post(
            f"/v1/conversations/{conversation['id']}/steer",
            json={"instruction": args.steer},
        )
        require(steer_response.status_code == 200, "Steer request failed.")

    prompt = (
        "Search this workspace and summarize the field prep docs."
        if args.mode == "summarize"
        else "Prepare a briefing from the relevant workspace files."
    )
    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": prompt,
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {
                "style": "concise",
                "citations": True,
                "audio_reply": False,
            },
        },
    )

    print("Workspace root:")
    print(workspace_root)
    print("\nTurn stream:")
    print(response.text)
    require(response.status_code == 200, "Workspace turn failed.")

    runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
    print("\nRuns:")
    print(json.dumps(runs, indent=2))
    require(bool(runs), "Expected at least one workspace run.")
    if args.steer.strip():
        require(
            args.steer in runs[-1]["goal"],
            "Latest workspace run goal did not include the steering instruction.",
        )

    if args.mode != "brief":
        require(
            runs[-1]["status"] == "completed",
            "Summarize mode did not complete the workspace run.",
        )
        state = client.get(f"/v1/conversations/{conversation['id']}/state").json()
        require(
            any(item["kind"] == "steer" for item in state["items"]) if args.steer.strip() else True,
            "Steer item was not retained in conversation state.",
        )
        print("\nSmoke workspace agent: PASS")
        return

    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    proposed_event = next((line for line in lines if line["type"] == "tool.proposed"), None)
    approval_line = next((line for line in lines if line["type"] == "approval.required"), None)
    require(proposed_event is not None, "Expected a tool.proposed event.")
    require(approval_line is not None, "Expected an approval.required event.")
    require(
        proposed_event["payload"]["item"]["kind"] == "tool_proposal",
        "tool.proposed did not carry a canonical tool_proposal item snapshot.",
    )
    require(
        approval_line["payload"]["item"]["kind"] == "approval",
        "approval.required did not carry a canonical approval item snapshot.",
    )
    require(
        approval_line["payload"].get("work_product_item", {}).get("kind") == "work_product",
        "approval.required did not carry a canonical work_product item snapshot.",
    )
    approval_id = approval_line["payload"]["id"]
    run_id = approval_line["payload"]["run_id"]
    pending_payload = approval_line["payload"]["payload"]
    edited_title, edited_content = grounded_refinement(
        pending_payload["title"],
        pending_payload["content"],
    )

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": edited_title,
                "content": edited_content,
            },
        },
    )
    print("\nApproval result:")
    print(json.dumps(approval_response.json(), indent=2))
    require(approval_response.status_code == 200, "Approval decision failed.")
    approval = approval_response.json()
    require(approval["status"] == "executed", "Approval was not executed.")
    require(approval.get("item", {}).get("kind") == "approval", "Approval response did not include the canonical approval item.")
    require(
        approval.get("work_product_item", {}).get("kind") == "work_product",
        "Approval response did not include the canonical work_product item.",
    )
    require(approval.get("run", {}).get("status") == "completed", "Approval response did not include the completed run snapshot.")

    run = client.get(f"/v1/runs/{run_id}").json()
    notes = client.get("/v1/notes").json()
    state = client.get(f"/v1/conversations/{conversation['id']}/state").json()
    print("\nFinal run:")
    print(json.dumps(run, indent=2))
    print("\nNotes:")
    print(json.dumps(notes, indent=2))
    print("\nConversation State:")
    print(json.dumps(state, indent=2))

    require(run["status"] == "completed", "Final run did not complete.")
    require(bool(notes), "Expected the workspace briefing approval path to create a note/export artifact.")
    require(
        any(note["title"] == edited_title for note in notes),
        "Expected the refined grounded title to be saved.",
    )
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
    print("\nSmoke workspace agent: PASS")


if __name__ == "__main__":
    main()
