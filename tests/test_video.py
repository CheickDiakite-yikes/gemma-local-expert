from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.contracts.api import AssetKind, AssistantMode, ExecutionMode, GroundingStatus
from engine.models.video import (
    FFmpegVideoRuntime,
    detect_tracking_runtime_status,
    VideoAnalysisRequest,
    VideoAsset,
    _extract_video_ocr_facts,
    _meaningful_video_ocr_lines,
)


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
    assert result.evidence_packet is not None
    assert any("contact sheet" in fact.summary.lower() for fact in result.evidence_packet.facts)
    assert any("visually" in fact.summary.lower() for fact in result.evidence_packet.facts)
    assert result.artifacts
    assert result.artifacts[0].kind == AssetKind.IMAGE
    assert Path(result.artifacts[0].local_path).exists()


def test_meaningful_video_ocr_lines_keeps_clean_ui_text() -> None:
    lines = _meaningful_video_ocr_lines(
        "Rifle inventory\nAK platform\n__\n11\n??\nSouth gate camera"
    )

    assert "Rifle inventory" in lines
    assert "AK platform" in lines
    assert "South gate camera" in lines
    assert "__" not in lines


def test_extract_video_ocr_facts_adds_timestamp_refs(monkeypatch, tmp_path: Path) -> None:
    frame_a = tmp_path / "frame-01.jpg"
    frame_b = tmp_path / "frame-02.jpg"
    frame_a.write_bytes(b"fake")
    frame_b.write_bytes(b"fake")

    class CompletedProcess:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    outputs = iter(
        [
            CompletedProcess("North gate camera\nPossible rifle case"),
            CompletedProcess("North gate camera\nWorker staging area"),
        ]
    )

    monkeypatch.setattr("engine.models.video.shutil.which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr("engine.models.video.subprocess.run", lambda *args, **kwargs: next(outputs))

    facts = _extract_video_ocr_facts(
        [frame_a, frame_b],
        {
            "sample_points": [
                {"time_seconds": 10.0},
                {"time_seconds": 20.0},
            ]
        },
    )

    assert facts
    assert 'Visible on-screen text from sampled frames includes "North gate camera".' == facts[0].summary
    assert any(ref.ref == "00:10" for ref in facts[0].refs)


def test_ffmpeg_video_runtime_combines_two_videos_for_comparison(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required for local video sampling tests")

    first_video = tmp_path / "first.mp4"
    second_video = tmp_path / "second.mp4"
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
            str(first_video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=160x90:rate=8",
            "-t",
            "2",
            str(second_video),
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
            user_text="Compare both videos conservatively.",
            tracking_model_name="sam3.1",
            tracking_model_source=None,
            assets=[
                VideoAsset(
                    asset_id="asset_video_first",
                    display_name="first.mp4",
                    local_path=str(first_video),
                    kind=AssetKind.VIDEO,
                    media_type="video/mp4",
                    care_context="general",
                    analysis_summary=None,
                ),
                VideoAsset(
                    asset_id="asset_video_second",
                    display_name="second.mp4",
                    local_path=str(second_video),
                    kind=AssetKind.VIDEO,
                    media_type="video/mp4",
                    care_context="general",
                    analysis_summary=None,
                ),
            ],
            sample_frames=3,
            resolution=384,
            detect_every=15,
        )
    )

    assert result.available is True
    assert result.evidence_packet is not None
    assert result.evidence_packet.execution_mode == ExecutionMode.FALLBACK
    assert result.evidence_packet.grounding_status == GroundingStatus.PARTIAL
    assert len(result.evidence_packet.asset_ids) == 2
    fact_summaries = [fact.summary for fact in result.evidence_packet.facts]
    assert any("first.mp4" in summary for summary in fact_summaries)
    assert any("second.mp4" in summary for summary in fact_summaries)
    assert any("contrasted conservatively" in summary for summary in fact_summaries)
    assert len(result.artifacts) >= 2


def test_detect_tracking_runtime_status_reports_ffmpeg_fallback(monkeypatch) -> None:
    monkeypatch.setattr("engine.models.video.resolve_local_model_source", lambda *args: None)
    monkeypatch.setattr("engine.models.video._mlx_sam_library_available", lambda: False)
    monkeypatch.setattr("engine.models.video.shutil.which", lambda name: f"/usr/bin/{name}")

    status = detect_tracking_runtime_status(
        tracking_backend="ffmpeg",
        tracking_model_source=None,
        tracking_model_name="sam3.1",
    )

    assert status.ffmpeg_available is True
    assert status.tracking_execution_available is False
    assert status.video_analysis_fallback_only is True
    assert "cannot run SAM tracking" in (status.reason or "")
