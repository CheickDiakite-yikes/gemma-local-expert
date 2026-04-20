from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings
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
            if '"type":"approval.required"' in response.text:
                approval_line = next(
                    json.loads(line)
                    for line in response.text.splitlines()
                    if '"type":"approval.required"' in line
                )
                approval_id = approval_line["payload"]["id"]

        if approval_id:
            decision = client.post(
                f"/v1/approvals/{approval_id}/decisions",
                json={
                    "action": "approve",
                    "edited_payload": {
                        "title": "Reviewed field briefing",
                        "content": (
                            "Reviewed field briefing\n"
                            "- Pack oral rehydration salts\n"
                            "- Uses bounded routing, retrieval, vision, and approvals\n"
                            "- Confirm translator contact sheet before departure\n"
                        ),
                    },
                },
            )
            print("\nAPPROVAL RESULT")
            print(json.dumps(decision.json(), indent=2))

        transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
        runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
        print("\nTRANSCRIPT ROLES")
        print([message["role"] for message in transcript])
        print("\nRUNS")
        print(json.dumps(runs, indent=2))


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
