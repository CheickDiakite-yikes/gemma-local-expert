from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


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
    parser.add_argument("--edited-title", default="Field prep briefing (reviewed)")
    parser.add_argument(
        "--edited-content",
        default=(
            "Field prep briefing\n"
            "- Pack oral rehydration salts\n"
            "- Pack backup batteries\n"
            "- Carry printed route sheets\n"
            "- Confirm translator contact sheet before departure\n"
        ),
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

    runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
    print("\nRuns:")
    print(json.dumps(runs, indent=2))

    if args.mode != "brief":
        return

    approval_line = next(
        json.loads(line)
        for line in response.text.splitlines()
        if '"type":"approval.required"' in line
    )
    approval_id = approval_line["payload"]["id"]
    run_id = approval_line["payload"]["run_id"]

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": args.edited_title,
                "content": args.edited_content,
            },
        },
    )
    print("\nApproval result:")
    print(json.dumps(approval_response.json(), indent=2))

    run = client.get(f"/v1/runs/{run_id}").json()
    notes = client.get("/v1/notes").json()
    print("\nFinal run:")
    print(json.dumps(run, indent=2))
    print("\nNotes:")
    print(json.dumps(notes, indent=2))


if __name__ == "__main__":
    main()
