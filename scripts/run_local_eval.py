from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssistantMode,
    ConversationTurnRequest,
    LibrarySearchRequest,
)
from engine.models.video import VideoAnalysisResult
from engine.models.vision import VisionAnalysisResult


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
            fake_assets = [
                AssetSummary(
                    id=asset_id,
                    display_name=asset_id,
                    source_path=asset_id,
                    kind=_guess_eval_asset_kind(asset_id),
                    care_context=AssetCareContext.MEDICAL if "medical" in asset_id else AssetCareContext.GENERAL,
                )
                for asset_id in case["asset_ids"]
            ]
            route = container.router.decide(request, assets=fake_assets)
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


def run_conversation_eval() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir()
        (workspace_root / "field-prep.md").write_text(
            "Field prep checklist\nPack oral rehydration salts\nPack backup batteries\n",
            encoding="utf-8",
        )
        (workspace_root / "route-notes.md").write_text(
            "Village route briefing\nConfirm translator contact sheet before departure.\n",
            encoding="utf-8",
        )
        settings = Settings(
            database_path=str(temp_root / "conversation-eval.db"),
            workspace_root=str(workspace_root),
            asset_storage_dir=str(temp_root / "uploads"),
            specialist_backend="mock",
            tracking_backend="mock",
        )
        app = create_app(settings)
        _install_fake_multimodal_runtimes(app)
        client = TestClient(app)
        cases = json.loads(Path("evals/conversation/sample_scenarios.json").read_text(encoding="utf-8"))
        failures = 0

        for case in cases:
            conversation = client.post(
                "/v1/conversations",
                json={"title": case["title"], "mode": case["mode"]},
            ).json()
            turn_outputs: list[str] = []
            approval_payload_content = ""
            approval_id = None
            cached_assets: dict[str, str] = {}

            for turn in case["turns"]:
                asset_ids = [
                    _ensure_eval_asset(client, cached_assets, asset_kind)
                    for asset_kind in turn.get("assets", [])
                ]
                response = client.post(
                    f"/v1/conversations/{conversation['id']}/turns",
                    json={
                        "conversation_id": conversation["id"],
                        "mode": case["mode"],
                        "text": turn["text"],
                        "asset_ids": asset_ids,
                        "enabled_knowledge_pack_ids": [],
                        "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
                    },
                )
                turn_outputs.append(response.text)
                if '"type":"approval.required"' in response.text:
                    approval_line = next(
                        json.loads(line)
                        for line in response.text.splitlines()
                        if '"type":"approval.required"' in line
                    )
                    approval_id = approval_line["payload"]["id"]
                    approval_payload_content = str(
                        approval_line["payload"]["payload"].get("content", "")
                    )

            note_content = ""
            if case.get("approve_last_tool") and approval_id:
                decision = client.post(
                    f"/v1/approvals/{approval_id}/decisions",
                    json={"action": "approve", "edited_payload": {}},
                )
                if decision.status_code == 200:
                    notes = client.get("/v1/notes").json()
                    if notes:
                        note_content = notes[0]["content"]

            transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
            actual = {
                "assistant_turns": sum(1 for message in transcript if message["role"] == "assistant"),
                "contains": [needle for needle in case["expected_contains"] if any(needle.lower() in output.lower() for output in turn_outputs)],
                "approval_contains": [
                    needle
                    for needle in case.get("expected_approval_contains", [])
                    if needle.lower() in approval_payload_content.lower()
                ],
                "note_contains": [
                    needle
                    for needle in case.get("expected_note_contains", [])
                    if needle.lower() in note_content.lower()
                ],
            }
            if (
                actual["assistant_turns"] != case["expected_assistant_turns"]
                or len(actual["contains"]) != len(case["expected_contains"])
                or len(actual["approval_contains"]) != len(case.get("expected_approval_contains", []))
                or len(actual["note_contains"]) != len(case.get("expected_note_contains", []))
            ):
                failures += 1
                print(f"FAIL {case['id']}: expected={case['expected_contains']} actual={actual}")
            else:
                print(f"PASS {case['id']}")

        return failures


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"routing", "retrieval", "conversation"}:
        print("Usage: python scripts/run_local_eval.py [routing|retrieval|conversation]")
        return 2

    suite = sys.argv[1]
    if suite == "routing":
        return run_routing_eval()
    if suite == "retrieval":
        return run_retrieval_eval()
    return run_conversation_eval()


def _guess_eval_asset_kind(asset_id: str) -> AssetKind:
    lowered = asset_id.lower()
    if "video" in lowered or lowered.endswith((".mov", ".mp4")):
        return AssetKind.VIDEO
    return AssetKind.IMAGE


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


def _ensure_eval_asset(
    client: TestClient,
    cached_assets: dict[str, str],
    asset_kind: str,
) -> str:
    cached = cached_assets.get(asset_kind)
    if cached:
        return cached

    if asset_kind == "image":
        response = client.post(
            "/v1/assets/upload",
            data={"care_context": "general"},
            files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
        )
    elif asset_kind == "video":
        response = client.post(
            "/v1/assets/upload",
            data={"care_context": "general"},
            files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
        )
    else:
        raise ValueError(f"Unsupported eval asset kind: {asset_kind}")

    asset_id = response.json()["asset"]["id"]
    cached_assets[asset_kind] = asset_id
    return asset_id


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


if __name__ == "__main__":
    raise SystemExit(main())
