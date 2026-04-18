from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import AssistantMode, ConversationCreateRequest


def test_conversation_persists_across_container_rebuilds(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "persist.db"))

    container = build_container(settings)
    created = container.store.create_conversation(
        ConversationCreateRequest(title="Field Trip", mode=AssistantMode.FIELD)
    )
    container.store.close()

    reloaded = build_container(settings)
    restored = reloaded.store.ensure_conversation(created.id)
    reloaded.store.close()

    assert restored.id == created.id
    assert restored.title == "Field Trip"
    assert restored.mode == AssistantMode.FIELD
