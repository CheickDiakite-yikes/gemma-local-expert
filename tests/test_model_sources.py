from pathlib import Path

from engine.models import sources


def test_resolve_model_source_prefers_local_path(tmp_path: Path) -> None:
    local_model = tmp_path / "embeddinggemma"
    local_model.mkdir()

    resolved = sources.resolve_model_source(str(local_model), "embeddinggemma-300m")

    assert resolved == str(local_model)


def test_resolve_model_source_uses_hf_cache_alias(monkeypatch, tmp_path: Path) -> None:
    cache_root = tmp_path / "hub"
    repo_dir = cache_root / "models--google--embeddinggemma-300m"
    snapshot_dir = repo_dir / "snapshots" / "abc123"
    snapshot_dir.mkdir(parents=True)
    refs_dir = repo_dir / "refs"
    refs_dir.mkdir(parents=True)
    (refs_dir / "main").write_text("abc123", encoding="utf-8")
    monkeypatch.setattr(sources, "HF_CACHE_ROOT", cache_root)

    resolved = sources.resolve_model_source(None, "embeddinggemma-300m")

    assert resolved == str(snapshot_dir)
    assert sources.resolve_model_id(None, "embeddinggemma-300m") == "google/embeddinggemma-300m"
