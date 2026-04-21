from pathlib import Path

from engine.contracts.api import GroundingStatus
from engine.models.document import (
    DocumentAnalysisRequest,
    DocumentAsset,
    LocalDocumentRuntime,
    _PageText,
    _meaningful_lines,
)


def test_meaningful_lines_filters_noisy_ocr_fragments() -> None:
    text = """
    Mali at a Turning Point: Organizing Knowledge to Capture National Value
    The world is entering a new age of intelligence.
    Young ), Intelligence - National
    | Population 5 f gm ti & New Tools FR aa Leverage
    Countries that adapt quickly will capture the value.
    """

    lines = _meaningful_lines(text)

    assert "Mali at a Turning Point: Organizing Knowledge to Capture National Value" in lines
    assert "The world is entering a new age of intelligence." in lines
    assert "Countries that adapt quickly will capture the value." in lines
    assert "Young ), Intelligence - National" not in lines
    assert "| Population 5 f gm ti & New Tools FR aa Leverage" not in lines


def test_meaningful_lines_strips_short_mixed_case_numeric_suffix_noise() -> None:
    text = """
    Countries that adapt quickly will capture the value. aN 4
    """

    lines = _meaningful_lines(text)

    assert lines == ["Countries that adapt quickly will capture the value."]


def test_document_runtime_marks_sparse_ocr_fallback_unavailable(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr("engine.models.document._extract_pdf_text", lambda path: None)
    monkeypatch.setattr(
        "engine.models.document._ocr_pdf",
        lambda path, output_dir, max_pages: [
            _PageText(page_number=1, text="Mali at a Turning Point")
        ],
    )

    runtime = LocalDocumentRuntime(artifact_root=str(tmp_path / "artifacts"))
    result = runtime.analyze(
        DocumentAnalysisRequest(
            conversation_id="conv_test",
            turn_id="turn_test",
            user_text="Summarize this document conservatively.",
            assets=[
                DocumentAsset(
                    asset_id="asset_doc",
                    display_name="scan.pdf",
                    local_path=str(pdf_path),
                    media_type="application/pdf",
                    analysis_summary=None,
                )
            ],
        )
    )

    assert result.available is False
    assert result.evidence_packet.grounding_status == GroundingStatus.UNAVAILABLE
    assert "enough clean grounded text" in result.text.lower()
