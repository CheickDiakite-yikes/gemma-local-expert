from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.contracts.api import AssetKind, AssistantMode
from engine.models.video import FFmpegVideoRuntime, VideoAnalysisRequest, VideoAsset


def test_ffmpeg_video_runtime_creates_contact_sheet(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required for local video sampling tests")

    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=8",
            "-t",
            "2",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    runtime = FFmpegVideoRuntime(artifact_root=str(tmp_path / "artifacts"))
    result = runtime.analyze(
        VideoAnalysisRequest(
            conversation_id="conv_test",
            turn_id="turn_test",
            mode=AssistantMode.GENERAL,
            user_text="Review this short site video conservatively.",
            tracking_model_name="sam3.1",
            tracking_model_source=None,
            assets=[
                VideoAsset(
                    asset_id="asset_video",
                    display_name="sample.mp4",
                    local_path=str(video_path),
                    kind=AssetKind.VIDEO,
                    media_type="video/mp4",
                    care_context="general",
                    analysis_summary=None,
                )
            ],
            sample_frames=3,
            resolution=384,
            detect_every=15,
        )
    )

    assert result.available is True
    assert result.backend == "ffmpeg"
    assert "sampled frames" in result.text.lower()
    assert result.artifacts
    assert result.artifacts[0].kind == AssetKind.IMAGE
    assert Path(result.artifacts[0].local_path).exists()
