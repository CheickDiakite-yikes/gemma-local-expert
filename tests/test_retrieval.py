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
