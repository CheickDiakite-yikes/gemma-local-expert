from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import LibrarySearchRequest


def test_hybrid_retrieval_returns_ors_guidance_for_approximate_query(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "retrieval.db"))
    container = build_container(settings)

    results = container.retrieval.search(
        LibrarySearchRequest(query="watch for dehydrated weakness while giving tiny sips")
    )
    container.store.close()

    assert results
    assert results[0].label == "ORS Guidance"


def test_hybrid_retrieval_prefers_guidance_for_teaching_style_ors_query(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "retrieval-guidance.db"))
    container = build_container(settings)

    results = container.retrieval.search(
        LibrarySearchRequest(query="Teach me how to prepare oral rehydration solution in the field.")
    )
    container.store.close()

    assert results
    assert results[0].label == "ORS Guidance"
