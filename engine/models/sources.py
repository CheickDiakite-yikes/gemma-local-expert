from __future__ import annotations

from pathlib import Path

HF_CACHE_ROOT = Path.home() / ".cache" / "huggingface" / "hub"

MODEL_SOURCE_ALIASES: dict[str, list[str]] = {
    "embeddinggemma-300m": ["google/embeddinggemma-300m"],
    "gemma-4-e4b-it": ["google/gemma-4-E4B-it"],
    "gemma-4-e2b-it-4bit": ["mlx-community/gemma-4-e2b-it-4bit"],
    "paligemma-2": ["mlx-community/paligemma2-3b-mix-224-4bit"],
    "paligemma2-3b-mix-224-4bit": ["mlx-community/paligemma2-3b-mix-224-4bit"],
    "sam3.1": ["mlx-community/sam3.1-bf16"],
    "sam3.1-bf16": ["mlx-community/sam3.1-bf16"],
    "medgemma-1.5-4b": ["mlx-community/medgemma-1.5-4b-it-4bit"],
    "medgemma-1.5-4b-it-4bit": ["mlx-community/medgemma-1.5-4b-it-4bit"],
}


def resolve_model_source(source: str | None, model_name: str | None = None) -> str | None:
    refs = _iter_candidate_refs(source, model_name)
    for ref in refs:
        path = Path(ref).expanduser()
        if path.exists():
            return str(path)

        if "/" in ref:
            snapshot = resolve_cached_snapshot(ref)
            if snapshot is not None:
                return snapshot

    if source:
        return source

    for ref in refs:
        if "/" in ref:
            return ref
    return None


def resolve_local_model_source(source: str | None, model_name: str | None = None) -> str | None:
    for ref in _iter_candidate_refs(source, model_name):
        path = Path(ref).expanduser()
        if path.exists():
            return str(path)
        if "/" in ref:
            snapshot = resolve_cached_snapshot(ref)
            if snapshot is not None:
                return snapshot
    return None


def resolve_model_id(source: str | None, model_name: str | None = None) -> str:
    if source:
        path = Path(source).expanduser()
        return str(path) if path.exists() else source

    for ref in _iter_candidate_refs(None, model_name):
        if "/" in ref:
            return ref

    return model_name or "unknown"


def resolve_cached_snapshot(repo_id: str) -> str | None:
    cache_dir = HF_CACHE_ROOT / f"models--{repo_id.replace('/', '--')}"
    if not cache_dir.exists():
        return None

    refs_main = cache_dir / "refs" / "main"
    if refs_main.exists():
        revision = refs_main.read_text(encoding="utf-8").strip()
        if revision:
            snapshot = cache_dir / "snapshots" / revision
            if snapshot.exists():
                return str(snapshot)

    snapshots_dir = cache_dir / "snapshots"
    if not snapshots_dir.exists():
        return None

    snapshots = sorted(
        (path for path in snapshots_dir.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return str(snapshots[0]) if snapshots else None


def _iter_candidate_refs(source: str | None, model_name: str | None) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def add(ref: str | None) -> None:
        if not ref:
            return
        if ref in seen:
            return
        seen.add(ref)
        refs.append(ref)

    for ref in (source, model_name):
        add(ref)
        for alias in MODEL_SOURCE_ALIASES.get((ref or "").strip().lower(), []):
            add(alias)

    return refs
