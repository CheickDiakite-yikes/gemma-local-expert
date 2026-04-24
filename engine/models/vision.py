from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engine.contracts.api import (
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

generate_vision = None
load_vision = None


def _mlx_vlm_generate():
    global generate_vision
    if generate_vision is None:
        from mlx_vlm import generate as loaded_generate

        generate_vision = loaded_generate
    return generate_vision


def _mlx_vlm_load():
    global load_vision
    if load_vision is None:
        from mlx_vlm import load as loaded_load

        load_vision = loaded_load
    return load_vision


@dataclass(slots=True)
class VisionAsset:
    asset_id: str
    display_name: str
    local_path: str
    kind: AssetKind
    media_type: str | None
    care_context: str
    analysis_summary: str | None


@dataclass(slots=True)
class VisionAnalysisRequest:
    conversation_id: str
    turn_id: str
    mode: AssistantMode
    user_text: str
    specialist_model_name: str
    specialist_model_source: str | None
    assets: list[VisionAsset]
    max_tokens: int
    temperature: float


@dataclass(slots=True)
class VisionAnalysisResult:
    text: str
    backend: str
    model_name: str
    model_source: str | None
    available: bool
    evidence_packet: EvidencePacket | None = None
    unavailable_reason: str | None = None


class VisionRuntime(Protocol):
    backend_name: str

    def analyze(self, request: VisionAnalysisRequest) -> VisionAnalysisResult: ...


class MetadataVisionRuntime:
    backend_name = "metadata"

    def analyze(self, request: VisionAnalysisRequest) -> VisionAnalysisResult:
        packet = EvidencePacket(
            source_domain=SourceDomain.IMAGE,
            asset_ids=[asset.asset_id for asset in request.assets],
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=ExecutionMode.UNAVAILABLE,
            grounding_status=GroundingStatus.UNAVAILABLE,
            summary="No local vision specialist model is available, so only attachment metadata can be reported.",
            uncertainties=["Pixel-level image review did not run from this path."],
        )
        return VisionAnalysisResult(
            text=_metadata_summary(request),
            backend=self.backend_name,
            model_name=request.specialist_model_name,
            model_source=request.specialist_model_source,
            available=False,
            evidence_packet=packet,
            unavailable_reason=(
                "No local vision specialist model is available, so the assistant is using "
                "attachment metadata only."
            ),
        )


class TesseractVisionRuntime:
    backend_name = "tesseract"

    def __init__(self) -> None:
        self._fallback = MetadataVisionRuntime()

    def analyze(self, request: VisionAnalysisRequest) -> VisionAnalysisResult:
        ocr_result = _ocr_analysis(request)
        if ocr_result is not None:
            return ocr_result
        return self._fallback.analyze(request)


class MLXVisionRuntime:
    backend_name = "mlx"

    def __init__(self, *, allow_remote: bool) -> None:
        self.allow_remote = allow_remote
        self._fallback = MetadataVisionRuntime()
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[object, object]] = {}

    def analyze(self, request: VisionAnalysisRequest) -> VisionAnalysisResult:
        resolved_source = self._resolve_source(request)
        if resolved_source is None:
            ocr_result = _ocr_analysis(request)
            if ocr_result is not None:
                return ocr_result
            fallback = self._fallback.analyze(request)
            return fallback

        image_paths = [
            asset.local_path
            for asset in request.assets
            if asset.kind == AssetKind.IMAGE and Path(asset.local_path).exists()
        ]
        if not image_paths:
            return VisionAnalysisResult(
                text="No local image files were available for multimodal analysis.",
                backend=self.backend_name,
                model_name=request.specialist_model_name,
                model_source=resolved_source,
                available=False,
                evidence_packet=EvidencePacket(
                    source_domain=SourceDomain.IMAGE,
                    asset_ids=[asset.asset_id for asset in request.assets],
                    profile=RuntimeProfile.FULL_LOCAL,
                    execution_mode=ExecutionMode.UNAVAILABLE,
                    grounding_status=GroundingStatus.UNAVAILABLE,
                    summary="Attached images could not be loaded from local storage.",
                    uncertainties=["No local image files were available for multimodal analysis."],
                ),
                unavailable_reason="Attached images could not be loaded from local storage.",
            )

        try:
            model, processor = self._load_model(resolved_source)
            generate_vision_fn = _mlx_vlm_generate()
            result = generate_vision_fn(
                model,
                processor,
                prompt=_build_prompt(request),
                image=image_paths if len(image_paths) > 1 else image_paths[0],
                verbose=False,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except Exception as exc:  # pragma: no cover - exercised via integration paths
            ocr_result = _ocr_analysis(request)
            if ocr_result is not None:
                return ocr_result
            fallback = self._fallback.analyze(request)
            return VisionAnalysisResult(
                text=fallback.text,
                backend=fallback.backend,
                model_name=request.specialist_model_name,
                model_source=resolved_source,
                available=False,
                evidence_packet=fallback.evidence_packet,
                unavailable_reason=f"Vision specialist inference failed: {exc}",
            )

        text = getattr(result, "text", "").strip()
        if not text:
            text = "The vision specialist returned no textual analysis."

        ocr_text = _extract_ocr_text(image_paths)
        backend = self.backend_name
        if ocr_text and (_request_prefers_text_extraction(request) or _is_low_signal_visual_output(text, request)):
            text = _merge_visual_and_ocr_text(text, ocr_text, request)
            backend = "mlx+tesseract"

        return VisionAnalysisResult(
            text=text,
            backend=backend,
            model_name=request.specialist_model_name,
            model_source=resolved_source,
            available=True,
            evidence_packet=_vision_packet(
                request,
                summary=text,
                backend=backend,
                grounded=GroundingStatus.GROUNDED if backend == self.backend_name else GroundingStatus.PARTIAL,
            ),
        )

    def _resolve_source(self, request: VisionAnalysisRequest) -> str | None:
        if self.allow_remote:
            return resolve_model_source(
                request.specialist_model_source,
                request.specialist_model_name,
            )
        return resolve_local_model_source(
            request.specialist_model_source,
            request.specialist_model_name,
        )

    def _load_model(self, source: str) -> tuple[object, object]:
        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached
            load_vision_fn = _mlx_vlm_load()
            model, processor = load_vision_fn(source)
            self._cache[source] = (model, processor)
            return model, processor


def _build_prompt(request: VisionAnalysisRequest) -> str:
    image_token_prefix = "<image>\n" * max(len(request.assets), 1)
    lines = [
        "You are the local visual specialist for Field Assistant.",
        "Answer only from what is visually present in the attached image or images.",
        "If the image is unclear, say so directly.",
    ]

    if request.mode == AssistantMode.MEDICAL:
        lines.extend(
            [
                "This is a medical support workflow.",
                "Stay assistive and descriptive. Do not present a definitive diagnosis.",
                "Flag uncertainty and recommend qualified clinical review when appropriate.",
            ]
        )

    lines.append(f"User request: {request.user_text}")
    lines.append("Attached assets:")
    for asset in request.assets:
        descriptor = f"- {asset.display_name} ({asset.care_context}"
        if asset.media_type:
            descriptor += f", {asset.media_type}"
        descriptor += ")"
        if asset.analysis_summary:
            descriptor += f": {asset.analysis_summary}"
        lines.append(descriptor)

    lines.append(
        "Return a concise observation summary. Include visible text, layout, objects, and any limits."
    )
    return image_token_prefix + "\n".join(lines)


def _metadata_summary(request: VisionAnalysisRequest) -> str:
    descriptors: list[str] = []
    for asset in request.assets:
        parts = [asset.display_name]
        if asset.media_type:
            parts.append(asset.media_type)
        parts.append(asset.care_context)
        if asset.analysis_summary:
            parts.append(asset.analysis_summary)
        descriptors.append(" | ".join(parts))

    prefix = (
        "Medical specialist routing selected."
        if request.mode == AssistantMode.MEDICAL
        else "Vision specialist routing selected."
    )
    return prefix + " Available attachment metadata:\n" + "\n".join(f"- {item}" for item in descriptors)


def _ocr_analysis(request: VisionAnalysisRequest) -> VisionAnalysisResult | None:
    image_paths = [
        asset.local_path
        for asset in request.assets
        if asset.kind == AssetKind.IMAGE and Path(asset.local_path).exists()
    ]
    ocr_text = _extract_ocr_text(image_paths)
    if not ocr_text:
        return None

    prefix = (
        "Visible text extracted from the medical image:\n"
        if request.mode == AssistantMode.MEDICAL
        else "Visible text extracted from the image:\n"
    )
    return VisionAnalysisResult(
        text=prefix + ocr_text,
        backend="tesseract",
        model_name="tesseract",
        model_source=None,
        available=True,
        evidence_packet=_vision_packet(
            request,
            summary=ocr_text,
            backend="tesseract",
            grounded=GroundingStatus.PARTIAL,
        ),
    )


def _extract_ocr_text(image_paths: list[str]) -> str | None:
    snippets: list[str] = []
    for image_path in image_paths:
        try:
            completed = subprocess.run(
                ["tesseract", image_path, "stdout", "--psm", "6"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        text = completed.stdout.strip()
        if text:
            snippets.append(text)

    if not snippets:
        return None
    return "\n\n".join(snippets)


def _request_prefers_text_extraction(request: VisionAnalysisRequest) -> bool:
    lowered = request.user_text.lower()
    return any(
        token in lowered
        for token in {
            "read",
            "text",
            "summarize",
            "extract",
            "receipt",
            "board",
            "whiteboard",
            "form",
            "card",
            "note",
            "visible",
            "shown",
            "screenshot",
        }
    )


def _is_low_signal_visual_output(text: str, request: VisionAnalysisRequest) -> bool:
    lowered = text.lower().strip()
    if len(lowered) < 48:
        return True
    if any(token in lowered for token in {"image/png", "image/jpg", "image/jpeg", "attached image"}):
        return True
    return any(asset.display_name.lower() in lowered for asset in request.assets)


def _merge_visual_and_ocr_text(
    visual_text: str,
    ocr_text: str,
    request: VisionAnalysisRequest,
) -> str:
    if _is_low_signal_visual_output(visual_text, request):
        return "Visible text extracted from the image:\n" + ocr_text

    return "\n\n".join(
        [
            "Visual observations:",
            visual_text,
            "Visible text extracted from the image:",
            ocr_text,
        ]
    )


def _vision_packet(
    request: VisionAnalysisRequest,
    *,
    summary: str,
    backend: str,
    grounded: GroundingStatus,
) -> EvidencePacket:
    lines = [
        line.strip(" -*")
        for line in summary.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    facts: list[EvidenceFact] = []
    for line in lines:
        lowered = line.lower()
        if lowered.startswith(("visible text extracted", "visual observations", "vision specialist routing selected")):
            continue
        facts.append(EvidenceFact(summary=line))
        if len(facts) == 6:
            break

    execution_mode = ExecutionMode.FULL if backend == "mlx" else ExecutionMode.FALLBACK
    uncertainties: list[str] = []
    if grounded != GroundingStatus.GROUNDED:
        uncertainties.append("This result came from OCR or a fallback image path.")

    return EvidencePacket(
        source_domain=SourceDomain.IMAGE,
        asset_ids=[asset.asset_id for asset in request.assets],
        profile=RuntimeProfile.FULL_LOCAL if backend == "mlx" else RuntimeProfile.LOW_MEMORY,
        execution_mode=execution_mode,
        grounding_status=grounded,
        summary=facts[0].summary if facts else "Local image review completed.",
        facts=facts,
        uncertainties=uncertainties,
        refs=[EvidenceRef(label=asset.display_name, ref=asset.asset_id) for asset in request.assets[:2]],
    )
