from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import re

from engine.contracts.api import (
    EvidenceFact,
    EvidencePacket,
    EvidenceRef,
    ExecutionMode,
    GroundingStatus,
    RuntimeProfile,
    SourceDomain,
)


@dataclass(slots=True)
class DocumentAsset:
    asset_id: str
    display_name: str
    local_path: str
    media_type: str | None
    analysis_summary: str | None


@dataclass(slots=True)
class DocumentAnalysisRequest:
    conversation_id: str
    turn_id: str
    user_text: str
    assets: list[DocumentAsset]
    max_pages: int = 6


@dataclass(slots=True)
class DocumentAnalysisResult:
    text: str
    backend: str
    model_name: str
    model_source: str | None
    available: bool
    evidence_packet: EvidencePacket
    unavailable_reason: str | None = None


class DocumentRuntime(Protocol):
    backend_name: str

    def analyze(self, request: DocumentAnalysisRequest) -> DocumentAnalysisResult: ...


@dataclass(slots=True)
class _PageText:
    page_number: int
    text: str


class LocalDocumentRuntime:
    backend_name = "document"

    def __init__(self, *, artifact_root: str) -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def analyze(self, request: DocumentAnalysisRequest) -> DocumentAnalysisResult:
        asset = next((item for item in request.assets if Path(item.local_path).exists()), None)
        if asset is None:
            packet = self._unavailable_packet(
                asset_ids=[],
                summary="No local document file was available for extraction.",
                uncertainties=["The referenced document is missing from local storage."],
            )
            return DocumentAnalysisResult(
                text=packet.summary,
                backend=self.backend_name,
                model_name="document-fallback",
                model_source=None,
                available=False,
                evidence_packet=packet,
                unavailable_reason="Attached document could not be loaded from disk.",
            )

        document_path = Path(asset.local_path)
        suffix = document_path.suffix.lower()
        if suffix == ".pdf":
            return self._analyze_pdf(asset, request)
        return self._analyze_text_document(asset)

    def _analyze_pdf(
        self,
        asset: DocumentAsset,
        request: DocumentAnalysisRequest,
    ) -> DocumentAnalysisResult:
        embedded_text = _extract_pdf_text(Path(asset.local_path))
        if embedded_text:
            page_texts = [_PageText(page_number=1, text=embedded_text)]
            packet = self._packet_from_pages(
                asset_ids=[asset.asset_id],
                page_texts=page_texts,
                execution_mode=ExecutionMode.FULL,
                grounding_status=GroundingStatus.GROUNDED,
            )
            return DocumentAnalysisResult(
                text=_document_summary(packet, asset.display_name),
                backend=self.backend_name,
                model_name="pdftotext",
                model_source=None,
                available=True,
                evidence_packet=packet,
            )

        page_texts = _ocr_pdf(
            Path(asset.local_path),
            output_dir=self.artifact_root / request.turn_id,
            max_pages=request.max_pages,
        )
        if page_texts:
            packet = self._packet_from_pages(
                asset_ids=[asset.asset_id],
                page_texts=page_texts,
                execution_mode=ExecutionMode.FALLBACK,
                grounding_status=GroundingStatus.PARTIAL,
            )
            if len(packet.facts) < 2:
                packet = self._unavailable_packet(
                    asset_ids=[asset.asset_id],
                    summary=(
                        f"I could not extract enough clean grounded text from {asset.display_name} "
                        "with the local OCR fallback to summarize or draft from it safely yet."
                    ),
                    uncertainties=[
                        "Embedded text extraction failed.",
                        "OCR fallback did not yield enough clean page text to ground a safe summary.",
                    ],
                )
                return DocumentAnalysisResult(
                    text=packet.summary,
                    backend=self.backend_name,
                    model_name="pdftoppm+tesseract",
                    model_source=None,
                    available=False,
                    evidence_packet=packet,
                    unavailable_reason="OCR fallback did not yield enough clean grounded text.",
                )
            return DocumentAnalysisResult(
                text=_document_summary(packet, asset.display_name),
                backend=self.backend_name,
                model_name="pdftoppm+tesseract",
                model_source=None,
                available=True,
                evidence_packet=packet,
                unavailable_reason="Embedded PDF text was unavailable, so OCR fallback was used.",
            )

        packet = self._unavailable_packet(
            asset_ids=[asset.asset_id],
            summary=(
                f"I could not extract reliable text from {asset.display_name} with the local PDF "
                "stack, so I cannot safely summarize or draft from it yet."
            ),
            uncertainties=[
                "Embedded text extraction failed.",
                "OCR fallback did not produce usable page text.",
            ],
        )
        return DocumentAnalysisResult(
            text=packet.summary,
            backend=self.backend_name,
            model_name="document-fallback",
            model_source=None,
            available=False,
            evidence_packet=packet,
            unavailable_reason="Local PDF extraction did not produce usable text.",
        )

    def _analyze_text_document(self, asset: DocumentAsset) -> DocumentAnalysisResult:
        try:
            text = Path(asset.local_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            packet = self._unavailable_packet(
                asset_ids=[asset.asset_id],
                summary=f"I could not read {asset.display_name} as local text.",
                uncertainties=["The local text document could not be decoded safely."],
            )
            return DocumentAnalysisResult(
                text=packet.summary,
                backend=self.backend_name,
                model_name="text-reader",
                model_source=None,
                available=False,
                evidence_packet=packet,
                unavailable_reason="Local text document could not be decoded.",
            )

        packet = self._packet_from_pages(
            asset_ids=[asset.asset_id],
            page_texts=[_PageText(page_number=1, text=text)],
            execution_mode=ExecutionMode.FULL,
            grounding_status=GroundingStatus.GROUNDED,
        )
        return DocumentAnalysisResult(
            text=_document_summary(packet, asset.display_name),
            backend=self.backend_name,
            model_name="text-reader",
            model_source=None,
            available=True,
            evidence_packet=packet,
        )

    def _packet_from_pages(
        self,
        *,
        asset_ids: list[str],
        page_texts: list[_PageText],
        execution_mode: ExecutionMode,
        grounding_status: GroundingStatus,
    ) -> EvidencePacket:
        facts: list[EvidenceFact] = []
        refs: list[EvidenceRef] = []
        seen_summaries: set[str] = set()
        for page in page_texts:
            ref = EvidenceRef(label=f"Page {page.page_number}", ref=f"p{page.page_number}")
            refs.append(ref)
            for line in _meaningful_lines(page.text):
                normalized = line.lower()
                if normalized in seen_summaries:
                    continue
                seen_summaries.add(normalized)
                facts.append(EvidenceFact(summary=line, refs=[ref]))
                if len(facts) == 8:
                    break
            if len(facts) == 8:
                break

        summary = (
            facts[0].summary
            if facts
            else "Local extraction succeeded, but the resulting document text was still sparse."
        )
        uncertainties: list[str] = []
        if execution_mode == ExecutionMode.FALLBACK:
            uncertainties.append("The document summary is based on OCR fallback rather than embedded text.")
        if grounding_status == GroundingStatus.PARTIAL:
            uncertainties.append("Only a partial document view is currently grounded.")

        return EvidencePacket(
            source_domain=SourceDomain.DOCUMENT,
            asset_ids=asset_ids,
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=execution_mode,
            grounding_status=grounding_status,
            summary=summary,
            facts=facts,
            uncertainties=uncertainties,
            refs=refs[: min(4, len(refs))],
        )

    def _unavailable_packet(
        self,
        *,
        asset_ids: list[str],
        summary: str,
        uncertainties: list[str],
    ) -> EvidencePacket:
        return EvidencePacket(
            source_domain=SourceDomain.DOCUMENT,
            asset_ids=asset_ids,
            profile=RuntimeProfile.LOW_MEMORY,
            execution_mode=ExecutionMode.UNAVAILABLE,
            grounding_status=GroundingStatus.UNAVAILABLE,
            summary=summary,
            uncertainties=uncertainties,
        )


def document_extraction_available() -> bool:
    has_embedded = shutil.which("pdftotext") is not None
    has_ocr_stack = shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None
    return has_embedded or has_ocr_stack


def _extract_pdf_text(pdf_path: Path) -> str | None:
    if shutil.which("pdftotext") is None:
        return None
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None
    text = completed.stdout.replace("\x0c", "\n").strip()
    if len("".join(text.split())) < 40:
        return None
    return text


def _ocr_pdf(pdf_path: Path, *, output_dir: Path, max_pages: int) -> list[_PageText]:
    if shutil.which("pdftoppm") is None or shutil.which("tesseract") is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / pdf_path.stem
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "220",
                "-f",
                "1",
                "-l",
                str(max(1, max_pages)),
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    page_texts: list[_PageText] = []
    for image_path in sorted(output_dir.glob(f"{pdf_path.stem}-*.png"))[:max_pages]:
        page_number = _page_number_from_name(image_path.name)
        try:
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "--psm", "3"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            continue
        text = _normalize_ocr_text(completed.stdout)
        if len("".join(text.split())) < 30:
            continue
        page_texts.append(_PageText(page_number=page_number, text=text))
    return page_texts


def _page_number_from_name(name: str) -> int:
    stem = Path(name).stem
    suffix = stem.rsplit("-", 1)[-1]
    if suffix.isdigit():
        return int(suffix)
    return 1


def _meaningful_lines(text: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    cleaned_lines = [
        " ".join(raw_line.split()).strip()
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if " ".join(raw_line.split()).strip()
    ]
    candidates: list[str] = []
    for index, cleaned in enumerate(cleaned_lines):
        candidates.append(cleaned)
        if len(cleaned) < 72 and index + 1 < len(cleaned_lines):
            pair = f"{cleaned} {cleaned_lines[index + 1]}".strip()
            if len(pair) <= 140:
                candidates.append(pair)
            if (
                len(cleaned_lines[index + 1]) < 72
                and index + 2 < len(cleaned_lines)
            ):
                triple = f"{pair} {cleaned_lines[index + 2]}".strip()
                if len(triple) <= 160:
                    candidates.append(triple)

    for cleaned in candidates:
        tokens_simple = cleaned.split()
        if len(tokens_simple) >= 4:
            last_token = tokens_simple[-1]
            if (
                len(last_token) <= 2
                and any(char.islower() for char in last_token)
                and any(char.isupper() for char in last_token)
            ):
                cleaned = " ".join(tokens_simple[:-1]).strip()
                tokens_simple = cleaned.split()
        if len(tokens_simple) >= 5:
            last_token = tokens_simple[-1]
            previous_token = tokens_simple[-2]
            if (
                len(last_token) <= 2
                and last_token.isdigit()
                and len(previous_token) <= 3
                and any(char.islower() for char in previous_token)
                and any(char.isupper() for char in previous_token)
            ):
                cleaned = " ".join(tokens_simple[:-2]).strip()
        if len(cleaned) < 20:
            continue
        if cleaned.isupper() and len(cleaned.split()) <= 2:
            continue
        letters = sum(char.isalpha() for char in cleaned)
        digits = sum(char.isdigit() for char in cleaned)
        weird = sum(
            1
            for char in cleaned
            if not (char.isalnum() or char.isspace() or char in ".,:;!?'-/()%&")
        )
        if letters < 14:
            continue
        if letters / max(1, len(cleaned)) < 0.55:
            continue
        if weird > max(1, len(cleaned) // 18):
            continue
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", cleaned)
        alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
        long_alpha_tokens = [token for token in alpha_tokens if sum(char.isalpha() for char in token) >= 3]
        short_alpha_tokens = [token for token in alpha_tokens if sum(char.isalpha() for char in token) <= 2]
        if len(long_alpha_tokens) < 3:
            continue
        if short_alpha_tokens and len(short_alpha_tokens) / max(1, len(alpha_tokens)) > 0.35:
            continue
        if any(marker in cleaned for marker in {"|", "__", "— —", "==", "~~", "),", "(,", "[,", "] ,"}):
            continue
        if digits and digits > letters:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        lines.append(cleaned)
        if len(lines) == 8:
            break
    filtered: list[str] = []
    lowered_lines = [line.lower() for line in lines]
    for index, line in enumerate(lines):
        lowered = lowered_lines[index]
        if any(
            lowered != other and lowered in other and len(line.split()) <= 6
            for other in lowered_lines
        ):
            continue
        filtered.append(line)
    return filtered


def _normalize_ocr_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("—", "-").replace("–", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _document_summary(packet: EvidencePacket, display_name: str) -> str:
    lines = [f"I reviewed {display_name} locally."]
    if packet.facts:
        lines.append("Key grounded points:")
        for fact in packet.facts[:4]:
            refs = ", ".join(ref.ref for ref in fact.refs)
            suffix = f" ({refs})" if refs else ""
            lines.append(f"- {fact.summary}{suffix}")
    if packet.uncertainties:
        lines.append("Limits:")
        for item in packet.uncertainties[:2]:
            lines.append(f"- {item}")
    return "\n".join(lines)
