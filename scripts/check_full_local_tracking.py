#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from engine.config.settings import load_settings
from engine.models.video import detect_tracking_runtime_status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the local SAM/tracking stack is actually ready."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    settings = load_settings()
    status = detect_tracking_runtime_status(
        tracking_backend=settings.tracking_backend,
        tracking_model_source=settings.tracking_model_source,
        tracking_model_name=settings.default_tracking_model,
    )
    payload = {
        "tracking_backend": status.backend,
        "tracking_model": status.model_name,
        "local_model_source": status.local_model_source,
        "ffmpeg_available": status.ffmpeg_available,
        "tracking_library_available": status.tracking_library_available,
        "tracking_model_available": status.tracking_model_available,
        "tracking_execution_available": status.tracking_execution_available,
        "isolation_execution_available": status.isolation_execution_available,
        "video_analysis_fallback_only": status.video_analysis_fallback_only,
        "reason": status.reason,
        "recommended_server_command": "bash scripts/run_full_local_server.sh",
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("Field Assistant full-local tracking readiness")
    print(f"- tracking backend: {payload['tracking_backend']}")
    print(f"- tracking model: {payload['tracking_model']}")
    print(f"- local model source: {payload['local_model_source'] or 'not found'}")
    print(f"- ffmpeg fallback available: {'yes' if payload['ffmpeg_available'] else 'no'}")
    print(
        "- mlx_vlm SAM runtime importable: "
        + ("yes" if payload["tracking_library_available"] else "no")
    )
    print(
        "- local SAM model available: "
        + ("yes" if payload["tracking_model_available"] else "no")
    )
    print(
        "- tracking execution available: "
        + ("yes" if payload["tracking_execution_available"] else "no")
    )
    print(
        "- isolation execution available: "
        + ("yes" if payload["isolation_execution_available"] else "no")
    )
    print(
        "- video analysis fallback only: "
        + ("yes" if payload["video_analysis_fallback_only"] else "no")
    )
    if payload["reason"]:
        print(f"- status: {payload['reason']}")

    if not payload["tracking_execution_available"]:
        print("\nTo unlock true local tracking/isolation instead of fallback review:")
        print("1. Make sure the `mlx_vlm` package with SAM support is available in this environment.")
        print(
            "2. Cache or point `FIELD_ASSISTANT_TRACKING_MODEL_SOURCE` to a local `mlx-community/sam3.1-bf16` snapshot."
        )
        print("3. Launch the richer profile with: bash scripts/run_full_local_server.sh")
    else:
        print("\nThe full-local tracking path is ready.")
        print(f"Launch with: {payload['recommended_server_command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
