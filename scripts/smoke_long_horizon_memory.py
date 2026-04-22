from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings
from engine.contracts.api import AssetCareContext, AssetKind
from engine.models.video import VideoAnalysisResult
from engine.models.vision import VisionAnalysisResult


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
    with tempfile.TemporaryDirectory(prefix="field-assistant-long-memory-") as temp_dir:
        temp_root = Path(temp_dir)
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir()
        build_sample_workspace(workspace_root)

        settings = Settings(
            database_path=str(temp_root / "long-memory.db"),
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
            json={"title": "Long Horizon Memory Smoke", "mode": "research"},
        ).json()

        turns = [
            ("Hey, can we talk normally while you help me think through field work?", []),
            ("Teach me how to prepare oral rehydration solution in the field.", []),
            ("What should I emphasize first to a volunteer with no medical training?", []),
            ("Separate tangent about lunch and coffee for a second.", []),
            ("Can we go back to that oral rehydration point again?", []),
            ("If I had to say that in one sentence, how would you put it?", []),
            ("What should make me stop and escalate?", []),
            ("Describe the attached supply image conservatively.", [image_asset["id"]]),
            ("Which two shortages matter most before departure?", []),
            ("Create a checklist from those two shortages for tomorrow morning.", []),
            ("What is that checklist called?", []),
            ("Thanks", []),
            ("yoo", []),
            ("Actually just talk normally with me for a second.", []),
            ("Review the attached mining video conservatively.", [video_asset["id"]]),
            ("Summarize what stands out in that video, but keep it cautious.", []),
            ("Create a short report from that video review.", []),
            ("What is the report called?", []),
            ("Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.", []),
            ("What's the export title now?", []),
            ("Go back to that architecture point again.", []),
            ("What was in that checklist again?", []),
            ("What was in the report again?", []),
            ("Compare the report title and export title for me.", []),
            ("Go back to the earlier image for a second. Which shortage mattered most?", []),
            ("And now just talk normally again for a second.", []),
        ]

        pending_approvals: list[dict[str, object]] = []
        turn_texts: list[str] = []
        turn_outputs: list[str] = []
        completed_texts: list[str] = []

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
            turn_texts.append(text)
            turn_outputs.append(response.text)
            print(f"\nTURN {index}: {text}")
            print(response.text)

            completed_line = next(
                (
                    json.loads(line)
                    for line in response.text.splitlines()
                    if '"type":"assistant.message.completed"' in line
                ),
                None,
            )
            if completed_line:
                completed_texts.append(completed_line["payload"]["text"])
            else:
                completed_texts.append("")

            approval_line = next(
                (
                    json.loads(line)
                    for line in response.text.splitlines()
                    if '"type":"approval.required"' in line
                ),
                None,
            )
            if approval_line:
                pending_approvals.append(approval_line["payload"])
                _approve_payload(client, approval_line["payload"])

        transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
        runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
        memories = app.state.container.store.list_conversation_memories(conversation["id"])

        assert "[ORS Guidance]" in completed_texts[1]
        assert "approach how to" not in completed_texts[1].lower()
        assert "teach me how" not in completed_texts[4].lower()
        assert "earlier we were talking about how to prepare oral rehydration solution in the field" in completed_texts[4].lower()
        assert "oral rehydration solution in the field" in completed_texts[4].lower()
        assert completed_texts[5].lower().startswith("in one sentence:")
        assert "grounded in [ors guidance]" in completed_texts[5].lower()
        assert "stop and escalate if you see worsening weakness, confusion, or inability to drink" in completed_texts[6].lower()
        assert completed_texts[11] == "Of course. I'm here when you want to keep going."
        assert completed_texts[12] == "Hey. What's up?"
        assert "field assistant architecture brief" in completed_texts[20].lower()
        assert "local-first assistant built on gemma" in completed_texts[20].lower()
        assert "bounded routing" in completed_texts[20].lower()
        assert "lantern batteries" in completed_texts[24].lower()
        assert "pit edge" not in completed_texts[24].lower()

        memory_summaries = [memory.summary.lower() for memory in memories]
        assert len(memory_summaries) <= 3
        assert any(
            "markdown export" in summary
            and "i reviewed" not in summary
            and "files reviewed" not in summary
            for summary in memory_summaries
        )
        assert any(
            "start with the core action from [ors guidance]" in summary
            and "here is a practical way" not in summary
            for summary in memory_summaries
        )
        assert not any(
            phrase in summary
            for summary in memory_summaries
            for phrase in {
                "current work product",
                "of course. i'm here when you want to keep going",
                "hey. what's up",
                "yes. we can just talk this through",
            }
        )

        print("\nMEMORIES")
        print(
            json.dumps(
                [
                    {
                        "topic": memory.topic,
                        "summary": memory.summary,
                        "kind": memory.kind.value,
                        "source_domain": memory.source_domain.value if memory.source_domain else None,
                    }
                    for memory in memories
                ],
                indent=2,
            )
        )
        print("\nTRANSCRIPT ROLES")
        print([message["role"] for message in transcript])
        print("\nRUNS")
        print(json.dumps(runs, indent=2))


def _approve_payload(client: TestClient, payload: dict[str, object]) -> None:
    approval_id = str(payload["id"])
    tool_name = str(payload["tool_name"])
    edited_payload: dict[str, object] = {}
    if tool_name == "create_checklist":
        edited_payload = {
            "title": "Departure shortage checklist",
            "content": "- Pack lantern batteries\n- Refill translator phone credits\n",
        }
    elif tool_name == "create_report":
        edited_payload = {
            "title": "Mining Video Review Report",
            "content": (
                "Mining Video Review Report\n\n"
                "Key points:\n"
                "- Workers are visible near excavation equipment.\n"
                "- The review remains conservative and sampled-frame based.\n"
            ),
        }
    elif tool_name == "export_brief":
        edited_payload = {
            "title": "Field Assistant Architecture Brief",
            "content": (
                "Field Assistant Architecture Brief\n\n"
                "Key points:\n"
                "- Local-first assistant built on Gemma.\n"
                "- Uses bounded routing, retrieval, vision, and approvals.\n"
            ),
        }
    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": edited_payload},
    )
    print("\nAPPROVAL RESULT")
    print(json.dumps(decision.json(), indent=2))


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
