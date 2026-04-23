from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings
from engine.models.video import VideoAnalysisResult
from engine.models.vision import VisionAnalysisResult


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_sample_workspace(root: Path) -> None:
    (root / "field-prep.md").write_text(
        "Field prep checklist\nPack oral rehydration salts\nPack backup batteries\n",
        encoding="utf-8",
    )
    (root / "route-notes.md").write_text(
        "Village route briefing\nConfirm translator contact sheet before departure.\n",
        encoding="utf-8",
    )
    (root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="field-assistant-deep-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir()
        build_sample_workspace(workspace_root)

        settings = Settings(
            database_path=str(temp_root / "deep-smoke.db"),
            workspace_root=str(workspace_root),
            asset_storage_dir=str(temp_root / "uploads"),
            specialist_backend="mock",
            tracking_backend="mock",
        )
        app = create_app(settings)
        _install_fake_multimodal_runtimes(app)
        client = TestClient(app)

        image_asset = client.post(
            "/v1/assets/upload",
            data={"care_context": "general"},
            files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
        ).json()["asset"]
        video_asset = client.post(
            "/v1/assets/upload",
            data={"care_context": "general"},
            files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
        ).json()["asset"]

        conversation = client.post(
            "/v1/conversations",
            json={"title": "Deep Smoke", "mode": "research"},
        ).json()

        turns = [
            ("Hey, can we talk normally while you help me think through field work?", []),
            ("What do you mean by that?", []),
            ("Teach me how to prepare oral rehydration solution in the field.", []),
            ("What should I emphasize first to a volunteer with no medical training?", []),
            ("Describe the attached supply image conservatively.", [image_asset["id"]]),
            ("Which two shortages matter most before departure?", []),
            (
                "Honestly I'm a little anxious about tomorrow. "
                "No checklist right now, just help me calm down for a second.",
                [],
            ),
            ("Review the attached mining video conservatively.", [video_asset["id"]]),
            ("Go back to the earlier image for a second. Which shortage mattered most?", []),
            ("Teach me how to explain oral rehydration solution to a new volunteer.", []),
            ("Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.", []),
            ("What title are you using for that draft?", []),
            ("What's in that draft again?", []),
            ("Keep the same draft, but make that shorter before I save it.", []),
            ("Actually, just talk normally with me for a second.", []),
            ("Go back to the earlier image for a second. Which shortage mattered most?", []),
            ("And what is the draft called now?", []),
        ]

        approval_id = None
        turn_texts: dict[int, str] = {}
        for index, (text, asset_ids) in enumerate(turns, start=1):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/turns",
                json={
                    "conversation_id": conversation["id"],
                    "mode": "research",
                    "text": text,
                    "asset_ids": asset_ids,
                    "enabled_knowledge_pack_ids": [],
                    "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
                },
            )
            print(f"\nTURN {index}: {text}")
            print(response.text)
            require(response.status_code == 200, f"Turn {index} failed.")
            lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            completed = next((line for line in lines if line["type"] == "assistant.message.completed"), None)
            require(completed is not None, f"Turn {index} did not complete an assistant message.")
            turn_texts[index] = completed["payload"]["text"]

            if index == 1:
                require("talk this through" in turn_texts[index], "Turn 1 lost the conversational opener.")
            if index == 2:
                require("keep this conversational" in turn_texts[index], "Turn 2 lost the conversational clarification.")
            if index == 3:
                require(any(line["type"] == "citation.added" for line in lines), "Turn 3 did not emit retrieval citations.")
                require("ORS Guidance" in turn_texts[index], "Turn 3 lost the grounded ORS guidance answer.")
            if index == 5:
                require("Lantern batteries low" in turn_texts[index], "Turn 5 lost the conservative image grounding.")
            if index == 6:
                require("Lantern batteries" in turn_texts[index], "Turn 6 lost the shortage prioritization.")
            if index == 7:
                require("Take a breath." in turn_texts[index], "Turn 7 lost the calming conversational reply.")
            if index == 8:
                require("mining clip conservatively" in turn_texts[index], "Turn 8 lost the conservative video review.")
            if index == 9:
                require("Lantern batteries" in turn_texts[index], "Turn 9 failed to return to the earlier image.")
            if index == 11:
                approval_line = next((line for line in lines if line["type"] == "approval.required"), None)
                require(approval_line is not None, "Turn 11 did not request approval for the export.")
                require(
                    approval_line["payload"]["category"] == "audited_export",
                    "Turn 11 export approval did not use the audited_export category.",
                )
                require(
                    "audit_log" in approval_line["payload"]["permission_classes"],
                    "Turn 11 export approval did not carry the audit_log permission class.",
                )
                approval_id = approval_line["payload"]["id"]
            if index == 15:
                require("talk this through" in turn_texts[index], "Turn 15 lost the conversational detour.")
            if index == 16:
                require("Lantern batteries" in turn_texts[index], "Turn 16 failed to return to the earlier image after the draft detour.")
            if index == 17:
                require(
                    "Field Assistant Architecture Brief" in turn_texts[index],
                    "Turn 17 failed to recall the pending draft title.",
                )

        require(approval_id is not None, "The deep conversation smoke never produced an approval flow.")
        decision = client.post(
            f"/v1/approvals/{approval_id}/decisions",
            json={
                "action": "approve",
                "edited_payload": {
                    "title": "Field Assistant Architecture Brief",
                    "content": (
                        "Field Assistant Architecture Brief\n\n"
                        "Key points:\n"
                        "- Local-first assistant built on Gemma.\n"
                        "- Uses bounded routing, retrieval, vision, and approvals.\n"
                    ),
                },
            },
        )
        print("\nAPPROVAL RESULT")
        print(json.dumps(decision.json(), indent=2))
        require(decision.status_code == 200, "Approval decision failed.")
        approval = decision.json()
        require(approval["status"] == "executed", "Approval did not execute.")
        require(approval["category"] == "audited_export", "Approval category drifted away from audited_export.")
        require(approval.get("run", {}).get("status") == "completed", "Export run did not complete.")

        transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
        runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
        state = client.get(f"/v1/conversations/{conversation['id']}/state").json()
        print("\nTRANSCRIPT ROLES")
        print([message["role"] for message in transcript])
        print("\nRUNS")
        print(json.dumps(runs, indent=2))
        print("\nSTATE")
        print(json.dumps(state, indent=2))

        require(len(transcript) == len(turns) * 2, "Transcript length drifted away from the expected alternating turns.")
        require(bool(runs), "Expected at least one workspace run in the deep smoke.")
        require(runs[-1]["status"] == "completed", "The latest run did not complete.")
        require(
            any(
                item["kind"] == "approval"
                and item["payload"]["approval"]["id"] == approval_id
                and item["payload"]["approval"]["status"] == "executed"
                for item in state["items"]
            ),
            "Conversation state did not retain the executed audited export approval item.",
        )
        require(
            any(
                message["role"] == "assistant"
                and "Field Assistant Architecture Brief" in message["content"]
                for message in transcript
            ),
            "Transcript lost the export title across the long conversation.",
        )
        print("\nDeep conversation smoke: PASS")


def _install_fake_multimodal_runtimes(app) -> None:
    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            return VisionAnalysisResult(
                text=(
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                ),
                backend="fake-vision",
                model_name=request.specialist_model_name,
                model_source="/tmp/fake-paligemma",
                available=True,
            )

    class FakeVideoRuntime:
        backend_name = "fake-video"

        def analyze(self, request):
            return VideoAnalysisResult(
                text=(
                    "Reviewed the attached mining clip conservatively. "
                    "I can see workers near excavation equipment and repeated tool handling around the pit edge."
                ),
                backend="fake-video",
                model_name=request.tracking_model_name,
                model_source="/tmp/fake-sam",
                available=True,
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    app.state.container.orchestrator.video_runtime = FakeVideoRuntime()


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


if __name__ == "__main__":
    main()
