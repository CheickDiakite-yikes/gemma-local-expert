from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import AgentRunStatus, AssistantMode, ConversationCreateRequest


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


def test_agent_run_persists_across_container_rebuilds(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "agent-run-persist.db"))

    container = build_container(settings)
    conversation = container.store.create_conversation(
        ConversationCreateRequest(title="Workspace", mode=AssistantMode.RESEARCH)
    )
    run = container.store.create_agent_run(
        conversation.id,
        "turn_demo",
        "Search this workspace and summarize the docs.",
        str(tmp_path),
        status=AgentRunStatus.COMPLETED,
        result_summary="Completed a bounded workspace run.",
    )
    container.store.close()

    reloaded = build_container(settings)
    restored = reloaded.store.get_agent_run(run.id)
    reloaded.store.close()

    assert restored is not None
    assert restored.id == run.id
    assert restored.status == AgentRunStatus.COMPLETED
    assert restored.result_summary == "Completed a bounded workspace run."
