from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from engine.contracts.api import AssetKind, AssistantMode
from engine.models.vision import (
    MLXVisionRuntime,
    VisionAnalysisRequest,
    VisionAsset,
    _extract_ocr_text,
)


def test_low_signal_visual_output_uses_ocr_augmentation(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "engine.models.vision.generate_vision",
        lambda *args, **kwargs: SimpleNamespace(text="- field_supply_board.png (general, image/png)"),
    )

    runtime = MLXVisionRuntime(allow_remote=False)
    monkeypatch.setattr(runtime, "_load_model", lambda source: (object(), object()))

    class CompletedProcess:
        def __init__(self) -> None:
            self.stdout = "Village Visit Supply Board\nLantern batteries LOW"

    monkeypatch.setattr(
        "engine.models.vision.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(),
    )

    model_dir = tmp_path / "fake-paligemma"
    model_dir.mkdir()
    image_path = tmp_path / "field_supply_board.png"
    image_path.write_bytes(_tiny_png_bytes())

    result = runtime.analyze(
        VisionAnalysisRequest(
            conversation_id="conv_test",
            turn_id="turn_test",
            mode=AssistantMode.GENERAL,
            user_text="Summarize the visible supply situation and note what looks low or urgent.",
            specialist_model_name="paligemma-2",
            specialist_model_source=str(model_dir),
            assets=[
                VisionAsset(
                    asset_id="asset_test",
                    display_name="field_supply_board.png",
                    local_path=str(image_path),
                    kind=AssetKind.IMAGE,
                    media_type="image/png",
                    care_context="general",
                    analysis_summary=None,
                )
            ],
            max_tokens=120,
            temperature=0.0,
        )
    )

    assert result.available is True
    assert result.backend == "mlx+tesseract"
    assert "Village Visit Supply Board" in result.text
    assert "Lantern batteries LOW" in result.text


def test_tesseract_ocr_uses_lossy_decode_for_non_utf8_output(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "field_supply_board.png"
    image_path.write_bytes(_tiny_png_bytes())

    def fake_run(*args, **kwargs):
        assert kwargs["errors"] == "replace"
        return SimpleNamespace(stdout="Village Visit Supply Board\nLantern batteries LOW")

    monkeypatch.setattr("engine.models.vision.subprocess.run", fake_run)

    assert "Village Visit Supply Board" in _extract_ocr_text([str(image_path)])


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
