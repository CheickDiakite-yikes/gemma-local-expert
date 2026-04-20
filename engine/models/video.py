from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssistantMode,
    EvidenceFact,
    EvidencePacket,
    EvidenceRef,
    ExecutionMode,
    GroundingStatus,
    RuntimeProfile,
    SourceDomain,
)
from engine.models.sources import resolve_local_model_source, resolve_model_source


@dataclass(slots=True)
class VideoAsset:
    asset_id: str
    display_name: str
    local_path: str
    kind: AssetKind
    media_type: str | None
    care_context: str
    analysis_summary: str | None


@dataclass(slots=True)
class VideoArtifact:
    display_name: str
    local_path: str
    media_type: str
    kind: AssetKind
    care_context: AssetCareContext
    analysis_summary: str


@dataclass(slots=True)
class VideoAnalysisRequest:
    conversation_id: str
    turn_id: str
    mode: AssistantMode
    user_text: str
    tracking_model_name: str
    tracking_model_source: str | None
    assets: list[VideoAsset]
    sample_frames: int
    resolution: int
    detect_every: int


@dataclass(slots=True)
class VideoAnalysisResult:
    text: str
    backend: str
    model_name: str
    model_source: str | None
    available: bool
    evidence_packet: EvidencePacket | None = None
    artifacts: list[VideoArtifact] = field(default_factory=list)
    unavailable_reason: str | None = None


class VideoRuntime(Protocol):
    backend_name: str

    def analyze(self, request: VideoAnalysisRequest) -> VideoAnalysisResult: ...


class MetadataVideoRuntime:
    backend_name = "metadata"

    def analyze(self, request: VideoAnalysisRequest) -> VideoAnalysisResult:
        descriptions = []
        for asset in request.assets:
            bits = [asset.display_name, asset.media_type or asset.kind.value, asset.care_context]
            if asset.analysis_summary:
                bits.append(asset.analysis_summary)
            descriptions.append(" | ".join(bits))
        packet = EvidencePacket(
            source_domain=SourceDomain.VIDEO,
            asset_ids=[asset.asset_id for asset in request.assets],
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=ExecutionMode.UNAVAILABLE,
            grounding_status=GroundingStatus.UNAVAILABLE,
            summary="No local video specialist is available, so only video metadata can be reported.",
            uncertainties=[
                "Tracking and isolation did not run.",
                "No sampled local frame evidence was produced from this path.",
            ],
        )
        return VideoAnalysisResult(
            text="Video specialist routing selected.\n" + "\n".join(f"- {item}" for item in descriptions),
            backend=self.backend_name,
            model_name=request.tracking_model_name,
            model_source=request.tracking_model_source,
            available=False,
            evidence_packet=packet,
            unavailable_reason="No local video specialist is available, so only video metadata can be reported.",
        )


class FFmpegVideoRuntime:
    backend_name = "ffmpeg"

    def __init__(self, *, artifact_root: str) -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._fallback = MetadataVideoRuntime()
        self._sample_cache: dict[tuple[str, int, int], VideoAnalysisResult] = {}

    def analyze(self, request: VideoAnalysisRequest) -> VideoAnalysisResult:
        source_asset = next((asset for asset in request.assets if asset.kind == AssetKind.VIDEO), None)
        if source_asset is None:
            return self._fallback.analyze(request)

        video_path = Path(source_asset.local_path)
        if not video_path.exists():
            return VideoAnalysisResult(
                text="The attached video is no longer available on local storage.",
                backend=self.backend_name,
                model_name=request.tracking_model_name,
                model_source=request.tracking_model_source,
                available=False,
                evidence_packet=EvidencePacket(
                    source_domain=SourceDomain.VIDEO,
                    asset_ids=[source_asset.asset_id],
                    profile=RuntimeProfile.LOW_MEMORY,
                    execution_mode=ExecutionMode.UNAVAILABLE,
                    grounding_status=GroundingStatus.UNAVAILABLE,
                    summary="The referenced local video file is missing.",
                    uncertainties=["No video evidence could be reviewed because the local file is missing."],
                ),
                unavailable_reason="The referenced local video file is missing.",
            )

        cache_key = (
            source_asset.asset_id,
            int(video_path.stat().st_mtime_ns),
            request.sample_frames,
        )
        cached = self._sample_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            metadata = _probe_video(video_path)
            work_dir = self.artifact_root / source_asset.asset_id
            work_dir.mkdir(parents=True, exist_ok=True)
            frame_paths = _extract_sample_frames(video_path, metadata, work_dir, request.sample_frames)
        except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            fallback = self._fallback.analyze(request)
            return VideoAnalysisResult(
                text=fallback.text,
                backend=fallback.backend,
                model_name=request.tracking_model_name,
                model_source=request.tracking_model_source,
                available=False,
                evidence_packet=fallback.evidence_packet,
                artifacts=fallback.artifacts,
                unavailable_reason=f"Local video sampling failed: {exc}",
            )

        artifacts: list[VideoArtifact] = []
        if frame_paths:
            contact_sheet_path = work_dir / f"{video_path.stem}-contact-sheet.png"
            try:
                _build_contact_sheet(frame_paths, contact_sheet_path, metadata)
            except (OSError, UnidentifiedImageError):
                contact_sheet_path = None
            if contact_sheet_path and contact_sheet_path.exists():
                artifacts.append(
                    VideoArtifact(
                        display_name=contact_sheet_path.name,
                        local_path=str(contact_sheet_path),
                        media_type="image/png",
                        kind=AssetKind.IMAGE,
                        care_context=AssetCareContext.GENERAL,
                        analysis_summary=(
                            "Sampled contact sheet from the uploaded video for local review."
                        ),
                    )
                )

        times = ", ".join(_format_timestamp(item["time_seconds"]) for item in metadata["sample_points"])
        packet = EvidencePacket(
            source_domain=SourceDomain.VIDEO,
            asset_ids=[source_asset.asset_id],
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=ExecutionMode.FALLBACK,
            grounding_status=GroundingStatus.PARTIAL,
            summary=f"Sampled local frames from {source_asset.display_name} and prepared a contact sheet for review.",
            facts=[
                EvidenceFact(
                    summary=(
                        f"Sampled the clip around {times} after loading it locally "
                        f"({_format_timestamp(metadata['duration_seconds'])}, {metadata['width']}x{metadata['height']})."
                    ),
                    refs=[
                        EvidenceRef(label="Sample window", ref=_format_timestamp(item["time_seconds"]))
                        for item in metadata["sample_points"][:4]
                    ],
                )
            ],
            uncertainties=[
                "This path only reviews sampled frames and metadata.",
                "Full tracking and isolation did not run from the fallback path.",
            ],
            refs=[
                EvidenceRef(label="Sample window", ref=_format_timestamp(item["time_seconds"]))
                for item in metadata["sample_points"][:4]
            ],
        )
        result = VideoAnalysisResult(
            text=_fallback_video_summary(source_asset.display_name, packet),
            backend=self.backend_name,
            model_name=request.tracking_model_name,
            model_source=request.tracking_model_source,
            available=True,
            evidence_packet=packet,
            artifacts=artifacts,
        )
        self._sample_cache[cache_key] = result
        return result


class MLXSamVideoRuntime:
    backend_name = "mlx-sam"

    def __init__(self, *, allow_remote: bool, artifact_root: str) -> None:
        self.allow_remote = allow_remote
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fallback = FFmpegVideoRuntime(artifact_root=artifact_root)

    def analyze(self, request: VideoAnalysisRequest) -> VideoAnalysisResult:
        resolved_source = self._resolve_source(request)
        if resolved_source is None:
            return self._fallback.analyze(request)

        source_asset = next((asset for asset in request.assets if asset.kind == AssetKind.VIDEO), None)
        if source_asset is None:
            return self._fallback.analyze(request)

        video_path = Path(source_asset.local_path)
        if not video_path.exists():
            return self._fallback.analyze(request)

        prompts = _tracking_prompts_for_text(request.user_text)
        output_path = self.artifact_root / request.turn_id / f"{video_path.stem}-tracked.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from mlx_vlm.models.sam3_1.generate import track_video

            with self._lock:
                track_video(
                    str(video_path),
                    prompts=prompts,
                    output=str(output_path),
                    model_path=resolved_source,
                    every=max(1, request.detect_every),
                    resolution=max(224, request.resolution),
                )
        except Exception as exc:  # pragma: no cover - integration path
            fallback = self._fallback.analyze(request)
            return VideoAnalysisResult(
                text=fallback.text,
                backend=fallback.backend,
                model_name=request.tracking_model_name,
                model_source=resolved_source,
                available=False,
                evidence_packet=fallback.evidence_packet,
                artifacts=fallback.artifacts,
                unavailable_reason=f"SAM video tracking failed locally: {exc}",
            )

        metadata = _probe_video(video_path)
        fallback = self._fallback.analyze(request)
        artifacts = list(fallback.artifacts)
        if output_path.exists():
            artifacts.append(
                VideoArtifact(
                    display_name=output_path.name,
                    local_path=str(output_path),
                    media_type="video/mp4",
                    kind=AssetKind.VIDEO,
                    care_context=AssetCareContext.GENERAL,
                    analysis_summary=(
                        "Locally tracked video generated with SAM 3.1 prompts: "
                        + ", ".join(prompts)
                    ),
                )
            )

        packet = EvidencePacket(
            source_domain=SourceDomain.VIDEO,
            asset_ids=[source_asset.asset_id],
            profile=RuntimeProfile.FULL_LOCAL,
            execution_mode=ExecutionMode.FULL,
            grounding_status=GroundingStatus.GROUNDED,
            summary=f"Tracked {source_asset.display_name} locally with SAM 3.1 prompts: {', '.join(prompts)}.",
            facts=[
                EvidenceFact(
                    summary=(
                        f"Generated a tracked local output for {_format_timestamp(metadata['duration_seconds'])} "
                        f"of video at {metadata['width']}x{metadata['height']}."
                    ),
                    refs=[EvidenceRef(label="Prompt", ref=prompt) for prompt in prompts[:4]],
                )
            ],
            uncertainties=[
                "The tracked output still needs assistant review before any policy or safety conclusion."
            ],
            artifact_ids=[artifact.local_path for artifact in artifacts if artifact.kind == AssetKind.VIDEO],
        )

        return VideoAnalysisResult(
            text=(
                f"I ran local SAM tracking on {source_asset.display_name} using prompts: {', '.join(prompts)}. "
                "The tracked output is ready for review, but any safety or policy conclusion should still come from visible evidence."
            ),
            backend=self.backend_name,
            model_name=request.tracking_model_name,
            model_source=resolved_source,
            available=True,
            evidence_packet=packet,
            artifacts=artifacts,
        )

    def _resolve_source(self, request: VideoAnalysisRequest) -> str | None:
        if self.allow_remote:
            return resolve_model_source(
                request.tracking_model_source,
                request.tracking_model_name,
            )
        return resolve_local_model_source(
            request.tracking_model_source,
            request.tracking_model_name,
        )


def _probe_video(video_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height,avg_frame_rate",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )
    duration_seconds = float(payload.get("format", {}).get("duration", 0.0) or 0.0)
    fps_value = video_stream.get("avg_frame_rate", "0/1")
    fps = _parse_frame_rate(fps_value)
    return {
        "duration_seconds": duration_seconds,
        "width": int(video_stream.get("width", 0) or 0),
        "height": int(video_stream.get("height", 0) or 0),
        "fps": fps,
        "sample_points": [],
    }


def _extract_sample_frames(
    video_path: Path,
    metadata: dict[str, object],
    work_dir: Path,
    count: int,
) -> list[Path]:
    duration = float(metadata["duration_seconds"])
    if duration <= 0:
        return []
    count = max(1, count)
    points = []
    for index in range(count):
        fraction = (index + 1) / (count + 1)
        points.append(duration * fraction)
    metadata["sample_points"] = [{"time_seconds": point} for point in points]

    frame_paths: list[Path] = []
    for index, point in enumerate(points, start=1):
        frame_path = work_dir / f"frame-{index:02d}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{point:.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(frame_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if frame_path.exists():
            frame_paths.append(frame_path)
    return frame_paths


def _build_contact_sheet(
    frame_paths: list[Path],
    output_path: Path,
    metadata: dict[str, object],
) -> None:
    images = [Image.open(path).convert("RGB") for path in frame_paths]
    try:
        if not images:
            return
        thumb_width = 320
        thumb_height = 180
        cols = 2
        rows = (len(images) + cols - 1) // cols
        gutter = 18
        padding = 20
        header = 62
        width = cols * thumb_width + (cols - 1) * gutter + padding * 2
        height = rows * thumb_height + (rows - 1) * gutter + padding * 2 + header
        canvas = Image.new("RGB", (width, height), "#0a0d12")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        draw.text((padding, 18), "Local video contact sheet", fill="#f5f1e8", font=font)
        draw.text(
            (padding, 38),
            f"{metadata['width']}x{metadata['height']} · {_format_timestamp(metadata['duration_seconds'])}",
            fill="#9098a6",
            font=font,
        )

        for index, image in enumerate(images):
            thumb = image.copy()
            thumb.thumbnail((thumb_width, thumb_height))
            background = Image.new("RGB", (thumb_width, thumb_height), "#121720")
            offset_x = (thumb_width - thumb.width) // 2
            offset_y = (thumb_height - thumb.height) // 2
            background.paste(thumb, (offset_x, offset_y))
            row = index // cols
            col = index % cols
            x = padding + col * (thumb_width + gutter)
            y = padding + header + row * (thumb_height + gutter)
            canvas.paste(background, (x, y))
            label = _format_timestamp(metadata["sample_points"][index]["time_seconds"])
            draw.rounded_rectangle((x + 10, y + 10, x + 72, y + 32), radius=10, fill="#0a0d12")
            draw.text((x + 18, y + 17), label, fill="#f5f1e8", font=font)

        canvas.save(output_path, format="PNG", optimize=True)
    finally:
        for image in images:
            image.close()


def _parse_frame_rate(value: str) -> float:
    if "/" not in value:
        return float(value)
    numerator, denominator = value.split("/", maxsplit=1)
    denominator_value = float(denominator or 1)
    if denominator_value == 0:
        return 0.0
    return float(numerator or 0) / denominator_value


def _format_timestamp(seconds: float) -> str:
    whole = int(max(0, round(seconds)))
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _looks_like_tracking_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in {
            "track",
            "detect",
            "monitor",
            "follow",
            "illegal",
            "unsafe",
            "bad process",
            "bad tool",
            "mining",
            "site",
        }
    )


def _tracking_prompts_for_text(text: str) -> list[str]:
    lowered = text.lower()
    prompts: list[str] = []
    keyword_prompts = {
        "person": {"person", "people", "worker", "workers", "volunteer", "staff"},
        "tool": {"tool", "tools", "illegal tool", "bad tool", "equipment"},
        "vehicle": {"vehicle", "truck", "car", "tractor"},
        "machine": {"machine", "machinery", "excavator", "drill", "generator"},
        "helmet": {"helmet", "ppe", "hard hat"},
    }
    for prompt, keywords in keyword_prompts.items():
        if any(keyword in lowered for keyword in keywords):
            prompts.append(prompt)

    if "\"" in text:
        quoted = [part.strip() for part in text.split("\"")[1::2] if part.strip()]
        prompts.extend(quoted)

    if not prompts and any(token in lowered for token in {"illegal", "unsafe", "mining", "site"}):
        prompts.extend(["person", "tool", "vehicle", "machine"])
    if not prompts:
        prompts.append("person")
    return list(dict.fromkeys(prompts))


def _fallback_video_summary(display_name: str, packet: EvidencePacket) -> str:
    lines = [f"I reviewed {display_name} locally using sampled frames."]
    if packet.facts:
        lines.append("Grounded from the fallback path:")
        for fact in packet.facts[:2]:
            refs = ", ".join(ref.ref for ref in fact.refs)
            suffix = f" ({refs})" if refs else ""
            lines.append(f"- {fact.summary}{suffix}")
    if packet.uncertainties:
        lines.append("Limits:")
        for item in packet.uncertainties[:2]:
            lines.append(f"- {item}")
    return "\n".join(lines)
