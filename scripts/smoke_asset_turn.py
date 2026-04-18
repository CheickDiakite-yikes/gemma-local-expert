from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.config.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an asset-backed conversation smoke test.")
    parser.add_argument("--db-path", default="data/smoke-asset-turn.db")
    parser.add_argument("--asset-storage-dir", default="data/smoke-uploads")
    parser.add_argument("--care-context", choices=["general", "medical"], default="general")
    parser.add_argument(
        "--prompt",
        default="Describe the attached image conservatively.",
    )
    parser.add_argument("--assistant-backend", choices=["mock", "mlx"], default="mock")
    parser.add_argument("--specialist-backend", choices=["mock", "auto", "mlx"], default="auto")
    parser.add_argument("--assistant-model-name", default="gemma-4-e4b-it")
    parser.add_argument("--assistant-model-source", default=None)
    parser.add_argument("--vision-model-name", default="paligemma-2")
    parser.add_argument("--vision-model-source", default=None)
    parser.add_argument("--medical-model-name", default="medgemma-1.5-4b")
    parser.add_argument("--medical-model-source", default=None)
    parser.add_argument("--image-path", default=None)
    args = parser.parse_args()

    settings = Settings(
        database_path=args.db_path,
        asset_storage_dir=args.asset_storage_dir,
        assistant_backend=args.assistant_backend,
        specialist_backend=args.specialist_backend,
        default_assistant_model=args.assistant_model_name,
        assistant_model_source=args.assistant_model_source,
        default_vision_model=args.vision_model_name,
        vision_model_source=args.vision_model_source,
        default_medical_model=args.medical_model_name,
        medical_model_source=args.medical_model_source,
    )
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.asset_storage_dir).mkdir(parents=True, exist_ok=True)

    client = TestClient(create_app(settings))
    if args.image_path:
        image_path = Path(args.image_path).expanduser()
        upload_name = image_path.name
        upload_bytes = image_path.read_bytes()
        media_type = _guess_media_type(upload_name)
    else:
        upload_name = "sample.png"
        upload_bytes = tiny_png_bytes()
        media_type = "image/png"

    upload_response = client.post(
        "/v1/assets/upload",
        data={"care_context": args.care_context},
        files={"file": (upload_name, upload_bytes, media_type)},
    )
    upload_response.raise_for_status()
    asset = upload_response.json()["asset"]

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Smoke Asset Turn", "mode": "general"},
    )
    conversation.raise_for_status()
    conversation_id = conversation.json()["id"]

    mode = "general"
    medical_session_id = None
    if args.care_context == "medical":
        mode = "medical"
        session = client.post(f"/v1/medical/sessions?conversation_id={conversation_id}")
        session.raise_for_status()
        medical_session_id = session.json()["id"]

    response = client.post(
        f"/v1/conversations/{conversation_id}/turns",
        json={
            "conversation_id": conversation_id,
            "mode": mode,
            "text": args.prompt,
            "asset_ids": [asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {
                "style": "concise",
                "citations": True,
                "audio_reply": False,
            },
            "medical_session_id": medical_session_id,
        },
    )
    response.raise_for_status()

    print("# Asset")
    print(json.dumps(asset, indent=2))
    print("# Stream")
    for line in response.text.splitlines():
        if line.strip():
            print(line)


def tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _guess_media_type(file_name: str) -> str:
    lowered = file_name.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


if __name__ == "__main__":
    main()
