from pathlib import Path

from engine.agent.service import WorkspaceAgentError, WorkspaceAgentService
from engine.contracts.api import AgentStepStatus


def test_workspace_agent_blocks_scope_escape(tmp_path: Path) -> None:
    service = WorkspaceAgentService(
        workspace_root=str(tmp_path),
        max_steps=6,
        max_file_reads=4,
        max_context_chars=3000,
    )

    try:
        service.plan("Search /tmp and summarize the docs there.")
    except WorkspaceAgentError as exc:
        assert "outside the allowed workspace scope" in str(exc)
    else:  # pragma: no cover - safety guard
        raise AssertionError("Expected workspace scope escape to be blocked.")


def test_workspace_agent_reads_supported_files_and_builds_summary(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "field-prep.md").write_text(
        "Field prep checklist\nPack batteries\nPack oral rehydration salts\n", encoding="utf-8"
    )
    (docs / "notes.txt").write_text(
        "Translator contact sheet and village visit sequence.\n", encoding="utf-8"
    )

    service = WorkspaceAgentService(
        workspace_root=str(tmp_path),
        max_steps=6,
        max_file_reads=4,
        max_context_chars=3000,
    )
    plan = service.plan("Search this workspace and summarize the field prep docs.")
    state = service.create_state(plan)

    completed_steps = [service.execute_step(plan, state, step) for step in plan.steps]

    assert all(step.status == AgentStepStatus.COMPLETED for step in completed_steps)
    assert state.summary_text is not None
    assert "field-prep.md" in state.summary_text
    assert "Pack batteries" in state.summary_text


def test_workspace_agent_plan_is_bounded_by_max_steps(tmp_path: Path) -> None:
    service = WorkspaceAgentService(
        workspace_root=str(tmp_path),
        max_steps=3,
        max_file_reads=4,
        max_context_chars=3000,
    )

    plan = service.plan("Prepare a briefing from the relevant workspace files.")

    assert len(plan.steps) == 3


def test_workspace_agent_generic_brief_tops_off_context_when_matches_are_sparse(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "field-prep.md").write_text(
        "Pack oral rehydration salts and backup batteries.\n",
        encoding="utf-8",
    )
    (docs / "contacts.txt").write_text(
        "Translator contact sheet and village route details.\n",
        encoding="utf-8",
    )
    (tmp_path / "README-notes.md").write_text(
        "Morning briefing structure and sequencing notes.\n",
        encoding="utf-8",
    )

    service = WorkspaceAgentService(
        workspace_root=str(tmp_path),
        max_steps=6,
        max_file_reads=4,
        max_context_chars=4000,
    )
    plan = service.plan("Prepare a briefing from the relevant workspace files.")
    state = service.create_state(plan)

    for step in plan.steps:
        service.execute_step(plan, state, step)

    assert len(state.read_documents) >= 2
    assert state.summary_text is not None
    assert "field-prep.md" in state.summary_text
    assert "contacts.txt" in state.summary_text
