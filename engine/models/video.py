from __future__ import annotations

import json
import shutil
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


@dataclass(slots=True)
class TrackingRuntimeStatus:
    backend: str
    model_name: str | None
    local_model_source: str | None
    ffmpeg_available: bool
    tracking_library_available: bool
    tracking_model_available: bool
    tracking_execution_available: bool
    isolation_execution_available: bool
    video_analysis_fallback_only: bool
    reason: str | None = None


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
        video_assets = [asset for asset in request.assets if asset.kind == AssetKind.VIDEO]
        if not video_assets:
            return self._fallback.analyze(request)
        if len(video_assets) == 1:
            return self._analyze_single_video_asset(request, video_assets[0])
        return self._analyze_multiple_video_assets(request, video_assets)

    def _analyze_multiple_video_assets(
        self,
        request: VideoAnalysisRequest,
        video_assets: list[VideoAsset],
    ) -> VideoAnalysisResult:
        results = [self._analyze_single_video_asset(request, asset) for asset in video_assets]
        return _combine_video_results(
            request=request,
            runtime_backend=self.backend_name,
            runtime_profile=RuntimeProfile.LOW_MEMORY,
            assets=video_assets,
            results=results,
        )

    def _analyze_single_video_asset(
        self,
        request: VideoAnalysisRequest,
        source_asset: VideoAsset,
    ) -> VideoAnalysisResult:
        single_request = _single_video_asset_request(request, source_asset)

        video_path = Path(source_asset.local_path)
        if not video_path.exists():
            return VideoAnalysisResult(
                text="The attached video is no longer available on local storage.",
                backend=self.backend_name,
                model_name=single_request.tracking_model_name,
                model_source=single_request.tracking_model_source,
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
            frame_paths = _extract_sample_frames(
                video_path,
                metadata,
                work_dir,
                single_request.sample_frames,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            fallback = self._fallback.analyze(single_request)
            return VideoAnalysisResult(
                text=fallback.text,
                backend=fallback.backend,
                model_name=single_request.tracking_model_name,
                model_source=single_request.tracking_model_source,
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
        facts: list[EvidenceFact] = [
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
        ]
        variation_fact = _sample_frame_variation_fact(frame_paths, metadata)
        if variation_fact is not None:
            facts.append(variation_fact)
        if artifacts:
            facts.append(
                EvidenceFact(
                    summary="Generated a local contact sheet for review across the sampled timestamps.",
                    refs=[
                        EvidenceRef(label="Sample window", ref=_format_timestamp(item["time_seconds"]))
                        for item in metadata["sample_points"][:4]
                    ],
                )
            )
        facts.extend(_extract_video_ocr_facts(frame_paths, metadata))
        packet = EvidencePacket(
            source_domain=SourceDomain.VIDEO,
            asset_ids=[source_asset.asset_id],
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=ExecutionMode.FALLBACK,
            grounding_status=GroundingStatus.PARTIAL,
            summary=f"Sampled local frames from {source_asset.display_name} and prepared a contact sheet for review.",
            facts=facts[:6],
            uncertainties=[
                "This path only reviews sampled frames, contact-sheet artifacts, and any visible OCR text.",
                "No local pixel-level object or action recognizer ran on the sampled frames in this profile.",
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
            model_name=single_request.tracking_model_name,
            model_source=single_request.tracking_model_source,
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

        video_assets = [asset for asset in request.assets if asset.kind == AssetKind.VIDEO]
        if not video_assets:
            return self._fallback.analyze(request)
        if len(video_assets) > 1:
            results = [
                self._analyze_single_video_asset(request, asset, resolved_source)
                for asset in video_assets
            ]
            return _combine_video_results(
                request=request,
                runtime_backend=self.backend_name,
                runtime_profile=RuntimeProfile.FULL_LOCAL,
                assets=video_assets,
                results=results,
            )
        return self._analyze_single_video_asset(request, video_assets[0], resolved_source)

    def _analyze_single_video_asset(
        self,
        request: VideoAnalysisRequest,
        source_asset: VideoAsset,
        resolved_source: str,
    ) -> VideoAnalysisResult:
        single_request = _single_video_asset_request(request, source_asset)
        video_path = Path(source_asset.local_path)
        if not video_path.exists():
            return self._fallback.analyze(single_request)

        prompts = _tracking_prompts_for_text(single_request.user_text)
        output_path = self.artifact_root / single_request.turn_id / f"{video_path.stem}-tracked.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from mlx_vlm.models.sam3_1.generate import track_video

            with self._lock:
                track_video(
                    str(video_path),
                    prompts=prompts,
                    output=str(output_path),
                    model_path=resolved_source,
                    every=max(1, single_request.detect_every),
                    resolution=max(224, single_request.resolution),
                )
        except Exception as exc:  # pragma: no cover - integration path
            fallback = self._fallback.analyze(single_request)
            return VideoAnalysisResult(
                text=fallback.text,
                backend=fallback.backend,
                model_name=single_request.tracking_model_name,
                model_source=resolved_source,
                available=False,
                evidence_packet=fallback.evidence_packet,
                artifacts=fallback.artifacts,
                unavailable_reason=f"SAM video tracking failed locally: {exc}",
            )

        metadata = _probe_video(video_path)
        fallback = self._fallback.analyze(single_request)
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
            model_name=single_request.tracking_model_name,
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


def detect_tracking_runtime_status(
    *,
    tracking_backend: str,
    tracking_model_source: str | None,
    tracking_model_name: str | None,
) -> TrackingRuntimeStatus:
    local_model_source = resolve_local_model_source(
        tracking_model_source,
        tracking_model_name,
    )
    tracking_model_available = local_model_source is not None
    ffmpeg_available = (
        shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    )
    tracking_library_available = _mlx_sam_library_available()
    tracking_execution_available = False
    isolation_execution_available = False
    fallback_only = True
    reason: str | None = None

    if tracking_backend == "mock":
        reason = "Mock tracking backend is configured, so no local tracking or isolation can run."
    elif tracking_backend == "ffmpeg":
        reason = (
            "ffmpeg fallback review is configured. This profile can sample frames and build contact sheets, "
            "but cannot run SAM tracking or isolation."
        )
    elif tracking_backend in {"auto", "mlx"}:
        tracking_execution_available = tracking_model_available and tracking_library_available
        isolation_execution_available = tracking_execution_available
        fallback_only = not tracking_execution_available
        missing: list[str] = []
        if not tracking_model_available:
            missing.append("local SAM model snapshot is not installed")
        if not tracking_library_available:
            missing.append("mlx_vlm SAM runtime is not importable in this environment")
        if missing:
            reason = "Full local tracking is not ready because " + " and ".join(missing) + "."
        else:
            reason = "Local SAM tracking and isolation are ready in this environment."
    else:
        reason = f"Unsupported tracking backend: {tracking_backend}"

    return TrackingRuntimeStatus(
        backend=tracking_backend,
        model_name=tracking_model_name,
        local_model_source=local_model_source,
        ffmpeg_available=ffmpeg_available,
        tracking_library_available=tracking_library_available,
        tracking_model_available=tracking_model_available,
        tracking_execution_available=tracking_execution_available,
        isolation_execution_available=isolation_execution_available,
        video_analysis_fallback_only=fallback_only,
        reason=reason,
    )


def _mlx_sam_library_available() -> bool:
    try:
        from mlx_vlm.models.sam3_1.generate import track_video  # noqa: F401
    except Exception:
        return False
    return True


def _single_video_asset_request(
    request: VideoAnalysisRequest,
    asset: VideoAsset,
) -> VideoAnalysisRequest:
    return VideoAnalysisRequest(
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
        mode=request.mode,
        user_text=request.user_text,
        tracking_model_name=request.tracking_model_name,
        tracking_model_source=request.tracking_model_source,
        assets=[asset],
        sample_frames=request.sample_frames,
        resolution=request.resolution,
        detect_every=request.detect_every,
    )


def _combine_video_results(
    *,
    request: VideoAnalysisRequest,
    runtime_backend: str,
    runtime_profile: RuntimeProfile,
    assets: list[VideoAsset],
    results: list[VideoAnalysisResult],
) -> VideoAnalysisResult:
    evidence_packets = [
        result.evidence_packet
        for result in results
        if result.evidence_packet is not None
    ]
    if not evidence_packets:
        unavailable_reason = next(
            (result.unavailable_reason for result in results if result.unavailable_reason),
            "No local video evidence could be produced.",
        )
        return VideoAnalysisResult(
            text="I could not produce local evidence for the selected videos.",
            backend=runtime_backend,
            model_name=request.tracking_model_name,
            model_source=request.tracking_model_source,
            available=False,
            evidence_packet=EvidencePacket(
                source_domain=SourceDomain.VIDEO,
                asset_ids=[asset.asset_id for asset in assets],
                profile=runtime_profile,
                execution_mode=ExecutionMode.UNAVAILABLE,
                grounding_status=GroundingStatus.UNAVAILABLE,
                summary=unavailable_reason,
                uncertainties=[unavailable_reason],
            ),
            unavailable_reason=unavailable_reason,
        )

    facts: list[EvidenceFact] = []
    refs: list[EvidenceRef] = []
    uncertainties: list[str] = []
    seen_uncertainties: set[str] = set()
    artifacts: list[VideoArtifact] = []

    comparison_fact = _comparison_fact_from_packets(assets, evidence_packets)
    if comparison_fact is not None:
        facts.append(comparison_fact)

    for asset, result in zip(assets, results):
        packet = result.evidence_packet
        artifacts.extend(result.artifacts)
        if packet is None:
            continue
        facts.extend(_prefix_packet_facts(asset.display_name, packet))
        refs.extend(_prefixed_packet_refs(asset.display_name, packet.refs[:2]))
        for item in packet.uncertainties:
            if item in seen_uncertainties:
                continue
            seen_uncertainties.add(item)
            uncertainties.append(item)

    if len(assets) > 1:
        comparison_limit = (
            "Cross-video comparison is limited to per-video sampled evidence and derived artifacts; "
            "no synchronized tracking or isolation ran across the pair."
        )
        if comparison_limit not in seen_uncertainties:
            uncertainties.insert(0, comparison_limit)

    execution_mode = (
        ExecutionMode.FULL
        if any(packet.execution_mode == ExecutionMode.FULL for packet in evidence_packets)
        else ExecutionMode.FALLBACK
        if any(packet.execution_mode == ExecutionMode.FALLBACK for packet in evidence_packets)
        else ExecutionMode.UNAVAILABLE
    )
    grounding_status = (
        GroundingStatus.GROUNDED
        if all(packet.grounding_status == GroundingStatus.GROUNDED for packet in evidence_packets)
        else GroundingStatus.PARTIAL
        if any(packet.grounding_status != GroundingStatus.UNAVAILABLE for packet in evidence_packets)
        else GroundingStatus.UNAVAILABLE
    )

    packet = EvidencePacket(
        source_domain=SourceDomain.VIDEO,
        asset_ids=[asset.asset_id for asset in assets],
        profile=runtime_profile,
        execution_mode=execution_mode,
        grounding_status=grounding_status,
        summary=(
            f"Prepared separate local evidence for {len(assets)} videos so they can be compared conservatively."
        ),
        facts=facts[:8],
        uncertainties=uncertainties[:4],
        refs=refs[:6],
        artifact_ids=[artifact.local_path for artifact in artifacts if artifact.kind in {AssetKind.IMAGE, AssetKind.VIDEO}],
    )
    available = any(result.available for result in results)
    return VideoAnalysisResult(
        text=_fallback_video_summary(
            f"{len(assets)} selected videos",
            packet,
        ),
        backend=runtime_backend,
        model_name=request.tracking_model_name,
        model_source=request.tracking_model_source,
        available=available,
        evidence_packet=packet,
        artifacts=artifacts,
        unavailable_reason=None if available else "No local video evidence could be produced.",
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


def _sample_frame_variation_fact(
    frame_paths: list[Path],
    metadata: dict[str, object],
) -> EvidenceFact | None:
    if len(frame_paths) < 2:
        return None
    deltas: list[float] = []
    previous_pixels: list[int] | None = None
    for frame_path in frame_paths:
        try:
            with Image.open(frame_path) as image:
                pixels = list(image.convert("L").resize((64, 36)).getdata())
        except (OSError, UnidentifiedImageError):
            return None
        if previous_pixels is not None and len(previous_pixels) == len(pixels):
            delta = sum(abs(int(a) - int(b)) for a, b in zip(previous_pixels, pixels)) / len(pixels)
            deltas.append(delta)
        previous_pixels = pixels
    if not deltas:
        return None
    average_delta = sum(deltas) / len(deltas)
    if average_delta < 8:
        summary = (
            "Sampled frames stay visually similar across the clip, so the fallback evidence suggests limited scene change between the sampled moments."
        )
    elif average_delta < 22:
        summary = (
            "Sampled frames show some visual change across the clip, but not enough to ground a detailed process claim from fallback-only review."
        )
    else:
        summary = (
            "Sampled frames vary noticeably across the clip, so the fallback evidence suggests meaningful visual change over time."
        )
    refs: list[EvidenceRef] = []
    sample_points = metadata.get("sample_points", [])
    if sample_points:
        refs.append(
            EvidenceRef(
                label="First sample",
                ref=_format_timestamp(sample_points[0]["time_seconds"]),
            )
        )
        refs.append(
            EvidenceRef(
                label="Last sample",
                ref=_format_timestamp(sample_points[-1]["time_seconds"]),
            )
        )
    return EvidenceFact(summary=summary, refs=refs)


def _extract_video_ocr_facts(
    frame_paths: list[Path],
    metadata: dict[str, object],
) -> list[EvidenceFact]:
    if shutil.which("tesseract") is None:
        return []
    sample_points = metadata.get("sample_points", [])
    collected: dict[str, list[EvidenceRef]] = {}
    ordered_lines: list[str] = []
    for index, frame_path in enumerate(frame_paths):
        try:
            completed = subprocess.run(
                ["tesseract", str(frame_path), "stdout", "--psm", "6"],
                check=False,
                capture_output=True,
                errors="replace",
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            continue
        lines = _meaningful_video_ocr_lines(completed.stdout)
        if not lines:
            continue
        ref = None
        if index < len(sample_points):
            ref = EvidenceRef(
                label="Frame sample",
                ref=_format_timestamp(sample_points[index]["time_seconds"]),
            )
        for line in lines[:2]:
            key = line.lower()
            if key not in collected:
                collected[key] = []
                ordered_lines.append(line)
            if ref is not None and all(existing.ref != ref.ref for existing in collected[key]):
                collected[key].append(ref)
    facts: list[EvidenceFact] = []
    for line in ordered_lines[:2]:
        facts.append(
            EvidenceFact(
                summary=f'Visible on-screen text from sampled frames includes "{line}".',
                refs=collected.get(line.lower(), [])[:3],
            )
        )
    return facts


def _meaningful_video_ocr_lines(text: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = " ".join(raw_line.split()).strip()
        if len(cleaned) < 6:
            continue
        letters = sum(char.isalpha() for char in cleaned)
        digits = sum(char.isdigit() for char in cleaned)
        weird = sum(
            1
            for char in cleaned
            if not (char.isalnum() or char.isspace() or char in ".,:;!?'-/()%&")
        )
        tokens = [token for token in cleaned.replace("/", " ").split() if token]
        alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
        long_alpha_tokens = [
            token for token in tokens if sum(char.isalpha() for char in token) >= 3
        ]
        short_alpha_tokens = [
            token for token in alpha_tokens if sum(char.isalpha() for char in token) <= 2
        ]
        average_alpha_length = (
            sum(sum(char.isalpha() for char in token) for token in alpha_tokens) / len(alpha_tokens)
            if alpha_tokens
            else 0.0
        )
        if letters + digits < 6:
            continue
        if letters and letters / max(1, len(cleaned)) < 0.35:
            continue
        if weird > max(1, len(cleaned) // 16):
            continue
        if len(alpha_tokens) >= 3 and short_alpha_tokens and (
            len(short_alpha_tokens) / max(1, len(alpha_tokens)) > 0.4
        ):
            continue
        if len(alpha_tokens) >= 4 and average_alpha_length < 4.0:
            continue
        if len(tokens) > 5 and len(long_alpha_tokens) < 3:
            continue
        if not long_alpha_tokens and digits < 3:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        lines.append(cleaned)
        if len(lines) == 4:
            break
    return lines


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


def _comparison_fact_from_packets(
    assets: list[VideoAsset],
    packets: list[EvidencePacket],
) -> EvidenceFact | None:
    if len(assets) < 2 or len(packets) < 2:
        return None
    refs: list[EvidenceRef] = []
    for asset, packet in zip(assets[:2], packets[:2]):
        if packet.refs:
            first_ref = packet.refs[0]
            refs.append(
                EvidenceRef(
                    label=asset.display_name,
                    ref=first_ref.ref,
                )
            )
    names = ", ".join(asset.display_name for asset in assets[:2])
    return EvidenceFact(
        summary=(
            f"Prepared separate local evidence for {names} so they can be contrasted conservatively without claiming synchronized tracking."
        ),
        refs=refs,
    )


def _prefix_packet_facts(
    display_name: str,
    packet: EvidencePacket,
) -> list[EvidenceFact]:
    prefixed: list[EvidenceFact] = []
    for fact in packet.facts[:3]:
        prefixed.append(
            EvidenceFact(
                summary=f"{display_name}: {fact.summary}",
                refs=_prefixed_packet_refs(display_name, fact.refs[:3]),
            )
        )
    return prefixed


def _prefixed_packet_refs(
    display_name: str,
    refs: list[EvidenceRef],
) -> list[EvidenceRef]:
    prefixed: list[EvidenceRef] = []
    short_label = display_name if len(display_name) <= 36 else display_name[:33] + "..."
    for ref in refs:
        prefixed.append(
            EvidenceRef(
                label=f"{short_label} {ref.label}".strip(),
                ref=ref.ref,
            )
        )
    return prefixed


def _fallback_video_summary(display_name: str, packet: EvidencePacket) -> str:
    if packet.execution_mode == ExecutionMode.FULL:
        lines = [f"I reviewed {display_name} locally with SAM-backed tracking artifacts."]
    elif packet.execution_mode == ExecutionMode.FALLBACK:
        lines = [f"I reviewed {display_name} locally using sampled frames."]
    else:
        lines = [f"I reviewed {display_name} conservatively from local metadata only."]
    if packet.facts:
        if packet.execution_mode == ExecutionMode.FULL:
            lines.append("Grounded from the local tracking path:")
        elif packet.execution_mode == ExecutionMode.FALLBACK:
            lines.append("Grounded from the fallback path:")
        else:
            lines.append("Grounded from the local metadata path:")
        for fact in packet.facts[:2]:
            refs = ", ".join(ref.ref for ref in fact.refs)
            suffix = f" ({refs})" if refs else ""
            lines.append(f"- {fact.summary}{suffix}")
    if packet.uncertainties:
        lines.append("Limits:")
        for item in packet.uncertainties[:2]:
            lines.append(f"- {item}")
    return "\n".join(lines)
