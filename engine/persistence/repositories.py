from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from engine.contracts.api import (
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    ApprovalDecision,
    ApprovalState,
    AssetAnalysisStatus,
    AssetCareContext,
    AssistantMode,
    AssetIngestRequest,
    AssetIngestResult,
    AssetKind,
    AssetSummary,
    Conversation,
    ConversationItem,
    ConversationItemKind,
    ConversationMessage,
    ConversationMemoryEntry,
    ConversationSummary,
    ConversationCreateRequest,
    ConversationForkRequest,
    ConversationTurnRecord,
    EvidencePacket,
    ExportRequest,
    ExportResult,
    KnowledgeDocumentInput,
    KnowledgePackImportRequest,
    KnowledgePackImportResult,
    LibrarySearchRequest,
    MedicalSession,
    Note,
    SearchResultItem,
    Task,
    TranscriptMessage,
    TurnExecutionPolicy,
    WorkspaceBinding,
    WorkspaceIsolationMode,
    new_id,
    utc_now,
)
from engine.ingestion.chunking import DocumentChunker, TextChunk
from engine.retrieval.embeddings import EmbeddingProvider

_UNSET = object()


@dataclass(slots=True)
class ChunkCandidate:
    asset_id: str
    chunk_id: str
    label: str
    text: str
    lexical_score: float = 0.0
    semantic_score: float = 0.0


class PersistenceStore(Protocol):
    def seed_demo_content(self) -> None: ...

    def create_conversation(self, request: ConversationCreateRequest) -> Conversation: ...

    def get_conversation(self, conversation_id: str) -> Conversation | None: ...

    def update_conversation_workspace_binding(
        self, conversation_id: str, workspace_binding: WorkspaceBinding
    ) -> Conversation | None: ...

    def list_conversations(
        self, limit: int = 50, *, include_archived: bool = False
    ) -> list[ConversationSummary]: ...

    def delete_conversation(self, conversation_id: str) -> bool: ...

    def archive_conversation(self, conversation_id: str) -> Conversation | None: ...

    def fork_conversation(
        self, conversation_id: str, request: ConversationForkRequest
    ) -> Conversation | None: ...

    def ensure_conversation(
        self,
        conversation_id: str,
        mode: AssistantMode = AssistantMode.GENERAL,
        *,
        workspace_binding: WorkspaceBinding | None = None,
    ) -> Conversation: ...

    def append_transcript(
        self,
        conversation_id: str,
        role: str,
        content: str,
        asset_ids: list[str] | None = None,
        turn_id: str | None = None,
        evidence_packet: EvidencePacket | None = None,
    ) -> TranscriptMessage: ...

    def list_recent_messages(
        self, conversation_id: str, limit: int = 8
    ) -> list[ConversationMessage]: ...

    def list_transcript(
        self, conversation_id: str, limit: int = 200
    ) -> list[TranscriptMessage]: ...

    def create_turn_record(
        self, record: ConversationTurnRecord
    ) -> ConversationTurnRecord: ...

    def get_turn_record(self, turn_id: str) -> ConversationTurnRecord | None: ...

    def update_turn_record(
        self,
        turn_id: str,
        *,
        route_kind: str | None | object = _UNSET,
        policy: TurnExecutionPolicy | object = _UNSET,
        user_message_id: str | None | object = _UNSET,
        assistant_message_id: str | None | object = _UNSET,
        workspace_root: str | object = _UNSET,
        cwd: str | object = _UNSET,
    ) -> ConversationTurnRecord: ...

    def list_turn_records(
        self, conversation_id: str, limit: int = 100
    ) -> list[ConversationTurnRecord]: ...

    def append_item(self, item: ConversationItem) -> ConversationItem: ...

    def list_items(
        self, conversation_id: str, *, turn_id: str | None = None, limit: int = 500
    ) -> list[ConversationItem]: ...

    def create_conversation_memory(
        self, entry: ConversationMemoryEntry
    ) -> ConversationMemoryEntry: ...

    def list_conversation_memories(
        self, conversation_id: str, limit: int = 12
    ) -> list[ConversationMemoryEntry]: ...

    def create_asset_record(
        self,
        *,
        asset_id: str,
        source_path: str,
        display_name: str,
        description: str | None,
        media_type: str | None,
        kind: AssetKind,
        byte_size: int | None,
        local_path: str | None,
        care_context: AssetCareContext,
        analysis_status: AssetAnalysisStatus,
        analysis_summary: str | None,
    ) -> AssetSummary: ...

    def get_asset(self, asset_id: str) -> AssetSummary | None: ...

    def get_asset_local_path(self, asset_id: str) -> str | None: ...

    def list_assets(self, asset_ids: list[str]) -> list[AssetSummary]: ...

    def import_knowledge_pack(
        self, request: KnowledgePackImportRequest
    ) -> KnowledgePackImportResult: ...

    def ingest_assets(self, request: AssetIngestRequest) -> AssetIngestResult: ...

    def search_library(self, request: LibrarySearchRequest) -> list[SearchResultItem]: ...

    def create_approval(
        self,
        conversation_id: str,
        turn_id: str,
        tool_name: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> ApprovalState: ...

    def get_approval(self, approval_id: str) -> ApprovalState | None: ...

    def update_approval_payload(
        self,
        approval_id: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> ApprovalState: ...

    def resolve_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalState: ...

    def finalize_approval(
        self, approval_id: str, status: str, result: dict[str, Any] | None = None
    ) -> ApprovalState: ...

    def create_medical_session(self, conversation_id: str) -> MedicalSession: ...

    def create_export(self, request: ExportRequest, status: str = "queued") -> ExportResult: ...

    def create_agent_run(
        self,
        conversation_id: str,
        turn_id: str,
        goal: str,
        scope_root: str,
        *,
        status: AgentRunStatus = AgentRunStatus.RUNNING,
        plan_steps: list[AgentRunStep] | None = None,
        executed_steps: list[AgentRunStep] | None = None,
        result_summary: str | None = None,
        artifact_ids: list[str] | None = None,
        approval_id: str | None = None,
    ) -> AgentRun: ...

    def get_agent_run(self, run_id: str) -> AgentRun | None: ...

    def list_agent_runs(self, conversation_id: str) -> list[AgentRun]: ...

    def update_agent_run(
        self,
        run_id: str,
        *,
        scope_root: str | object = _UNSET,
        status: AgentRunStatus | str | object = _UNSET,
        plan_steps: list[AgentRunStep] | object = _UNSET,
        executed_steps: list[AgentRunStep] | object = _UNSET,
        result_summary: str | None | object = _UNSET,
        artifact_ids: list[str] | object = _UNSET,
        approval_id: str | None | object = _UNSET,
    ) -> AgentRun: ...

    def create_note(self, title: str, content: str, kind: str = "note") -> Note: ...

    def list_notes(self) -> list[Note]: ...

    def create_task(
        self, title: str, details: str | None = None, status: str = "open"
    ) -> Task: ...

    def list_tasks(self) -> list[Task]: ...

    def add_audit(self, event_type: str, details: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class SQLiteStore:
    def __init__(
        self,
        database_path: str,
        *,
        chunker: DocumentChunker,
        embedding_provider: EmbeddingProvider,
        lexical_weight: float = 0.35,
        semantic_weight: float = 0.65,
        candidate_limit: int = 24,
    ) -> None:
        self.database_path = database_path
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.lexical_weight = lexical_weight
        self.semantic_weight = semantic_weight
        self.candidate_limit = candidate_limit

        db_path = Path(database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def seed_demo_content(self) -> None:
        with self._lock:
            existing = self._connection.execute(
                "SELECT COUNT(*) AS count FROM knowledge_packs"
            ).fetchone()
        if existing and existing["count"] > 0:
            self._backfill_missing_embeddings()
            return

        self.import_knowledge_pack(
            KnowledgePackImportRequest(
                name="Mission Training Pack",
                source_path="knowledge_packs/mission-training",
                tags=["operations", "field"],
                documents=[
                    KnowledgeDocumentInput(
                        label="Kenya Trip Checklist",
                        text=(
                            "Pack oral rehydration salts, water purification tablets, "
                            "printed checklists, consent forms, backup batteries, and "
                            "local contact sheets before departure. Confirm translators, "
                            "map the visit sequence, and carry printed daily debrief forms."
                        ),
                    ),
                    KnowledgeDocumentInput(
                        label="Daily Debrief Template",
                        text=(
                            "Capture visits completed, observations, open risks, supply "
                            "needs, translation blockers, and next-day priorities. Include "
                            "handoff notes and unresolved questions for the local team."
                        ),
                    ),
                ],
            )
        )

        self.import_knowledge_pack(
            KnowledgePackImportRequest(
                name="Public Health Education Pack",
                source_path="knowledge_packs/public-health",
                tags=["care", "education"],
                documents=[
                    KnowledgeDocumentInput(
                        label="ORS Guidance",
                        text=(
                            "Oral rehydration guidance: mix the packet with safe water, "
                            "continue small frequent sips, and monitor dehydration signs. "
                            "Watch for worsening weakness, confusion, or inability to drink."
                        ),
                    ),
                    KnowledgeDocumentInput(
                        label="Community Visit Notes",
                        text=(
                            "Use simple language, verify understanding, and document "
                            "follow-up dates for community health education visits. Keep "
                            "instructions short and culturally clear."
                        ),
                    ),
                ],
            )
        )

    def create_conversation(self, request: ConversationCreateRequest) -> Conversation:
        conversation = Conversation(
            id=new_id("conv"),
            title=request.title,
            mode=request.mode,
            workspace_binding=request.workspace_binding,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversations (
                    id,
                    title,
                    mode,
                    created_at,
                    archived_at,
                    workspace_binding_json,
                    parent_conversation_id,
                    forked_from_turn_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation.id,
                    conversation.title,
                    conversation.mode.value,
                    conversation.created_at.isoformat(),
                    conversation.archived_at,
                    (
                        conversation.workspace_binding.model_dump_json()
                        if conversation.workspace_binding
                        else None
                    ),
                    conversation.parent_conversation_id,
                    conversation.forked_from_turn_id,
                ),
            )
            self._connection.commit()
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = self._fetchone(
            """
            SELECT
                id,
                title,
                mode,
                created_at,
                archived_at,
                workspace_binding_json,
                parent_conversation_id,
                forked_from_turn_id
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        return self._row_to_conversation(row) if row else None

    def update_conversation_workspace_binding(
        self, conversation_id: str, workspace_binding: WorkspaceBinding
    ) -> Conversation | None:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return None
        with self._lock:
            self._connection.execute(
                "UPDATE conversations SET workspace_binding_json = ? WHERE id = ?",
                (workspace_binding.model_dump_json(), conversation_id),
            )
            self._connection.commit()
        return conversation.model_copy(update={"workspace_binding": workspace_binding})

    def list_conversations(
        self, limit: int = 50, *, include_archived: bool = False
    ) -> list[ConversationSummary]:
        archived_clause = "" if include_archived else "WHERE c.archived_at IS NULL"
        rows = self._fetchall(
            f"""
            SELECT
                c.id,
                c.title,
                c.mode,
                c.created_at,
                c.archived_at,
                c.workspace_binding_json,
                c.parent_conversation_id,
                c.forked_from_turn_id,
                COALESCE(MAX(cm.created_at), c.created_at) AS last_activity_at,
                (
                    SELECT content
                    FROM conversation_messages latest
                    WHERE latest.conversation_id = c.id
                    ORDER BY latest.created_at DESC
                    LIMIT 1
                ) AS last_message_preview
            FROM conversations c
            LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
            {archived_clause}
            GROUP BY
                c.id,
                c.title,
                c.mode,
                c.created_at,
                c.archived_at,
                c.workspace_binding_json,
                c.parent_conversation_id,
                c.forked_from_turn_id
            ORDER BY last_activity_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                mode=AssistantMode(row["mode"]),
                created_at=row["created_at"],
                last_activity_at=row["last_activity_at"],
                last_message_preview=row["last_message_preview"],
                archived_at=row["archived_at"] if "archived_at" in row.keys() else None,
                workspace_binding=(
                    WorkspaceBinding.model_validate_json(row["workspace_binding_json"])
                    if row["workspace_binding_json"]
                    else None
                ),
                parent_conversation_id=row["parent_conversation_id"],
                forked_from_turn_id=row["forked_from_turn_id"],
            )
            for row in rows
        ]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def archive_conversation(self, conversation_id: str) -> Conversation | None:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return None
        archived_at = utc_now()
        with self._lock:
            self._connection.execute(
                "UPDATE conversations SET archived_at = ? WHERE id = ?",
                (archived_at.isoformat(), conversation_id),
            )
            self._connection.commit()
        return conversation.model_copy(update={"archived_at": archived_at})

    def fork_conversation(
        self, conversation_id: str, request: ConversationForkRequest
    ) -> Conversation | None:
        source = self.get_conversation(conversation_id)
        if source is None:
            return None

        source_turns = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                mode,
                user_text,
                workspace_root,
                cwd,
                policy_json,
                route_kind,
                user_message_id,
                assistant_message_id,
                created_at,
                updated_at
            FROM conversation_turns
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        turn_rows = [self._row_to_turn_record(row) for row in source_turns]
        selected_turn_rows = turn_rows
        selected_source_turn_id = request.up_to_turn_id
        if request.up_to_turn_id is not None:
            matching_index = next(
                (index for index, row in enumerate(turn_rows) if row.id == request.up_to_turn_id),
                None,
            )
            if matching_index is None:
                raise ValueError("Turn not found in source conversation.")
            selected_turn_rows = turn_rows[: matching_index + 1]
        elif turn_rows:
            selected_source_turn_id = turn_rows[-1].id

        source_binding = source.workspace_binding
        if source_binding is None and selected_turn_rows:
            source_binding = WorkspaceBinding(
                root=selected_turn_rows[-1].workspace_root,
                cwd=selected_turn_rows[-1].cwd,
                isolation=WorkspaceIsolationMode.SHARED,
            )
        fork_binding = (
            source_binding.model_copy(update={"isolation": WorkspaceIsolationMode.FORKED})
            if source_binding is not None
            else None
        )
        forked = Conversation(
            id=new_id("conv"),
            title=request.title or self._default_fork_title(source.title),
            mode=request.mode or source.mode,
            workspace_binding=fork_binding,
            parent_conversation_id=source.id,
            forked_from_turn_id=selected_source_turn_id,
        )

        copied_turn_ids = {row.id for row in selected_turn_rows}
        cutoff_created_at = (
            selected_turn_rows[-1].created_at if selected_turn_rows else None
        )
        message_rows = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                role,
                content,
                created_at,
                turn_id,
                evidence_packet_json
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        copied_message_rows = [
            row
            for row in message_rows
            if (
                row["turn_id"] in copied_turn_ids
                or (
                    row["turn_id"] is None
                    and (
                        cutoff_created_at is None
                        or row["created_at"] <= cutoff_created_at.isoformat()
                    )
                )
            )
        ]
        message_asset_rows = self._fetchall(
            """
            SELECT message_id, asset_id
            FROM conversation_message_assets
            WHERE message_id IN (
                SELECT id FROM conversation_messages WHERE conversation_id = ?
            )
            """,
            (conversation_id,),
        )
        asset_ids_by_message: dict[str, list[str]] = {}
        for row in message_asset_rows:
            asset_ids_by_message.setdefault(row["message_id"], []).append(row["asset_id"])

        approval_rows = (
            self._fetchall(
                """
                SELECT
                    id,
                    conversation_id,
                    turn_id,
                    run_id,
                    tool_name,
                    reason,
                    status,
                    payload_json,
                    result_json
                FROM approvals
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            if request.copy_approvals
            else []
        )
        copied_approval_rows = [row for row in approval_rows if row["turn_id"] in copied_turn_ids]

        agent_run_rows = (
            self._fetchall(
                """
                SELECT
                    id,
                    conversation_id,
                    turn_id,
                    goal,
                    scope_root,
                    status,
                    plan_steps_json,
                    executed_steps_json,
                    result_summary,
                    artifact_ids_json,
                    approval_id,
                    created_at,
                    updated_at
                FROM agent_runs
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            if request.copy_agent_runs
            else []
        )
        copied_run_rows = [row for row in agent_run_rows if row["turn_id"] in copied_turn_ids]

        item_rows = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                turn_id,
                item_kind,
                summary,
                payload_json,
                created_at
            FROM conversation_items
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        copied_item_rows = [row for row in item_rows if row["turn_id"] in copied_turn_ids]

        memory_rows = (
            self._fetchall(
                """
                SELECT
                    id,
                    conversation_id,
                    turn_id,
                    kind,
                    topic,
                    summary,
                    keywords_json,
                    source_domain,
                    asset_ids_json,
                    tool_name,
                    referent_title,
                    created_at
                FROM conversation_memories
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            if request.copy_memories
            else []
        )
        copied_memory_rows = [row for row in memory_rows if row["turn_id"] in copied_turn_ids]

        next_timestamp = self._copy_timestamp_factory(forked.created_at)
        turn_id_map = {row.id: new_id("turn") for row in selected_turn_rows}
        message_id_map = {row["id"]: new_id("msg") for row in copied_message_rows}
        approval_id_map = {row["id"]: new_id("approval") for row in copied_approval_rows}
        run_id_map = {row["id"]: new_id("run") for row in copied_run_rows}

        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversations (
                    id,
                    title,
                    mode,
                    created_at,
                    archived_at,
                    workspace_binding_json,
                    parent_conversation_id,
                    forked_from_turn_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    forked.id,
                    forked.title,
                    forked.mode.value,
                    forked.created_at.isoformat(),
                    None,
                    forked.workspace_binding.model_dump_json()
                    if forked.workspace_binding
                    else None,
                    forked.parent_conversation_id,
                    forked.forked_from_turn_id,
                ),
            )

            for row in selected_turn_rows:
                copied_created_at = next_timestamp()
                copied_updated_at = next_timestamp()
                self._connection.execute(
                    """
                    INSERT INTO conversation_turns (
                        id,
                        conversation_id,
                        mode,
                        user_text,
                        workspace_root,
                        cwd,
                        policy_json,
                        route_kind,
                        user_message_id,
                        assistant_message_id,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id_map[row.id],
                        forked.id,
                        row.mode.value,
                        row.user_text,
                        row.workspace_root,
                        row.cwd,
                        row.policy.model_dump_json(),
                        row.route_kind,
                        None,
                        None,
                        copied_created_at.isoformat(),
                        copied_updated_at.isoformat(),
                    ),
                )

            for row in copied_message_rows:
                copied_created_at = next_timestamp()
                self._connection.execute(
                    """
                    INSERT INTO conversation_messages (
                        id,
                        conversation_id,
                        role,
                        content,
                        created_at,
                        turn_id,
                        evidence_packet_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id_map[row["id"]],
                        forked.id,
                        row["role"],
                        row["content"],
                        copied_created_at.isoformat(),
                        turn_id_map.get(row["turn_id"]),
                        row["evidence_packet_json"],
                    ),
                )
                for asset_id in asset_ids_by_message.get(row["id"], []):
                    self._connection.execute(
                        """
                        INSERT INTO conversation_message_assets (message_id, asset_id)
                        VALUES (?, ?)
                        """,
                        (message_id_map[row["id"]], asset_id),
                    )

            for row in selected_turn_rows:
                self._connection.execute(
                    """
                    UPDATE conversation_turns
                    SET user_message_id = ?, assistant_message_id = ?
                    WHERE id = ?
                    """,
                    (
                        message_id_map.get(row.user_message_id),
                        message_id_map.get(row.assistant_message_id),
                        turn_id_map[row.id],
                    ),
                )

            for row in copied_run_rows:
                copied_created_at = next_timestamp()
                copied_updated_at = next_timestamp()
                self._connection.execute(
                    """
                    INSERT INTO agent_runs (
                        id,
                        conversation_id,
                        turn_id,
                        goal,
                        scope_root,
                        status,
                        plan_steps_json,
                        executed_steps_json,
                        result_summary,
                        artifact_ids_json,
                        approval_id,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id_map[row["id"]],
                        forked.id,
                        turn_id_map[row["turn_id"]],
                        row["goal"],
                        row["scope_root"],
                        row["status"],
                        row["plan_steps_json"],
                        row["executed_steps_json"],
                        row["result_summary"],
                        row["artifact_ids_json"],
                        (
                            approval_id_map.get(row["approval_id"])
                            if row["approval_id"] is not None
                            else None
                        ),
                        copied_created_at.isoformat(),
                        copied_updated_at.isoformat(),
                    ),
                )

            for row in copied_approval_rows:
                copied_created_at = next_timestamp()
                self._connection.execute(
                    """
                    INSERT INTO approvals (
                        id,
                        conversation_id,
                        turn_id,
                        run_id,
                        tool_name,
                        reason,
                        status,
                        payload_json,
                        result_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id_map[row["id"]],
                        forked.id,
                        turn_id_map[row["turn_id"]],
                        run_id_map.get(row["run_id"]) if row["run_id"] is not None else None,
                        row["tool_name"],
                        row["reason"],
                        row["status"],
                        row["payload_json"],
                        row["result_json"],
                        copied_created_at.isoformat(),
                    ),
                )

            for row in copied_item_rows:
                payload = self._remap_item_payload(
                    json.loads(row["payload_json"] or "{}"),
                    turn_id_map=turn_id_map,
                    message_id_map=message_id_map,
                    approval_id_map=approval_id_map,
                    run_id_map=run_id_map,
                )
                self._connection.execute(
                    """
                    INSERT INTO conversation_items (
                        id,
                        conversation_id,
                        turn_id,
                        item_kind,
                        summary,
                        payload_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("item"),
                        forked.id,
                        turn_id_map[row["turn_id"]],
                        row["item_kind"],
                        row["summary"],
                        json.dumps(payload),
                        next_timestamp().isoformat(),
                    ),
                )

            for row in copied_memory_rows:
                self._connection.execute(
                    """
                    INSERT INTO conversation_memories (
                        id,
                        conversation_id,
                        turn_id,
                        kind,
                        topic,
                        summary,
                        keywords_json,
                        source_domain,
                        asset_ids_json,
                        tool_name,
                        referent_title,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("memory"),
                        forked.id,
                        turn_id_map[row["turn_id"]],
                        row["kind"],
                        row["topic"],
                        row["summary"],
                        row["keywords_json"],
                        row["source_domain"],
                        row["asset_ids_json"],
                        row["tool_name"],
                        row["referent_title"],
                        next_timestamp().isoformat(),
                    ),
                )

            self._connection.commit()

        return forked

    def ensure_conversation(
        self,
        conversation_id: str,
        mode: AssistantMode = AssistantMode.GENERAL,
        *,
        workspace_binding: WorkspaceBinding | None = None,
    ) -> Conversation:
        existing = self.get_conversation(conversation_id)
        if existing:
            return existing

        conversation = Conversation(
            id=conversation_id,
            mode=mode,
            workspace_binding=workspace_binding,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversations (
                    id,
                    title,
                    mode,
                    created_at,
                    archived_at,
                    workspace_binding_json,
                    parent_conversation_id,
                    forked_from_turn_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation.id,
                    conversation.title,
                    conversation.mode.value,
                    conversation.created_at.isoformat(),
                    conversation.archived_at,
                    (
                        conversation.workspace_binding.model_dump_json()
                        if conversation.workspace_binding
                        else None
                    ),
                    conversation.parent_conversation_id,
                    conversation.forked_from_turn_id,
                ),
            )
            self._connection.commit()
        return conversation

    def append_transcript(
        self,
        conversation_id: str,
        role: str,
        content: str,
        asset_ids: list[str] | None = None,
        turn_id: str | None = None,
        evidence_packet: EvidencePacket | None = None,
    ) -> TranscriptMessage:
        created_at = utc_now()
        message_id = new_id("msg")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversation_messages (id, conversation_id, role, content, created_at, turn_id, evidence_packet_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    created_at.isoformat(),
                    turn_id,
                    evidence_packet.model_dump_json() if evidence_packet else None,
                ),
            )
            for asset_id in asset_ids or []:
                self._connection.execute(
                    """
                    INSERT INTO conversation_message_assets (message_id, asset_id)
                    VALUES (?, ?)
                    """,
                    (message_id, asset_id),
                )
            if turn_id:
                item_kind = (
                    ConversationItemKind.USER_MESSAGE
                    if role == "user"
                    else ConversationItemKind.ASSISTANT_MESSAGE
                )
                item_payload: dict[str, Any] = {
                    "message_id": message_id,
                    "role": role,
                    "asset_ids": list(asset_ids or []),
                }
                if evidence_packet is not None:
                    item_payload["evidence_packet_id"] = evidence_packet.id
                self._insert_item_locked(
                    ConversationItem(
                        id=new_id("item"),
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        kind=item_kind,
                        summary=self._summarize_item_text(content),
                        payload=item_payload,
                        created_at=created_at,
                    )
                )
                if evidence_packet is not None:
                    self._insert_item_locked(
                        ConversationItem(
                            id=new_id("item"),
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            kind=ConversationItemKind.EVIDENCE_PACKET,
                            summary=evidence_packet.summary,
                            payload=evidence_packet.model_dump(mode="json"),
                            created_at=created_at,
                        )
                    )
            self._connection.commit()
        return TranscriptMessage(
            id=message_id,
            role=role,
            content=content,
            turn_id=turn_id,
            assets=self.list_assets(asset_ids or []),
            evidence_packet=evidence_packet,
            created_at=created_at,
        )

    def create_turn_record(
        self, record: ConversationTurnRecord
    ) -> ConversationTurnRecord:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversation_turns (
                    id,
                    conversation_id,
                    mode,
                    user_text,
                    workspace_root,
                    cwd,
                    policy_json,
                    route_kind,
                    user_message_id,
                    assistant_message_id,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.conversation_id,
                    record.mode.value,
                    record.user_text,
                    record.workspace_root,
                    record.cwd,
                    record.policy.model_dump_json(),
                    record.route_kind,
                    record.user_message_id,
                    record.assistant_message_id,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            self._connection.commit()
        return record

    def get_turn_record(self, turn_id: str) -> ConversationTurnRecord | None:
        row = self._fetchone(
            """
            SELECT
                id,
                conversation_id,
                mode,
                user_text,
                workspace_root,
                cwd,
                policy_json,
                route_kind,
                user_message_id,
                assistant_message_id,
                created_at,
                updated_at
            FROM conversation_turns
            WHERE id = ?
            """,
            (turn_id,),
        )
        return self._row_to_turn_record(row) if row else None

    def update_turn_record(
        self,
        turn_id: str,
        *,
        route_kind: str | None | object = _UNSET,
        policy: TurnExecutionPolicy | object = _UNSET,
        user_message_id: str | None | object = _UNSET,
        assistant_message_id: str | None | object = _UNSET,
        workspace_root: str | object = _UNSET,
        cwd: str | object = _UNSET,
    ) -> ConversationTurnRecord:
        record = self.get_turn_record(turn_id)
        if record is None:
            raise KeyError(turn_id)

        next_route_kind = record.route_kind if route_kind is _UNSET else route_kind
        next_policy = record.policy if policy is _UNSET else policy
        next_user_message_id = (
            record.user_message_id if user_message_id is _UNSET else user_message_id
        )
        next_assistant_message_id = (
            record.assistant_message_id
            if assistant_message_id is _UNSET
            else assistant_message_id
        )
        next_workspace_root = (
            record.workspace_root if workspace_root is _UNSET else workspace_root
        )
        next_cwd = record.cwd if cwd is _UNSET else cwd
        updated_at = utc_now()

        with self._lock:
            self._connection.execute(
                """
                UPDATE conversation_turns
                SET
                    workspace_root = ?,
                    cwd = ?,
                    policy_json = ?,
                    route_kind = ?,
                    user_message_id = ?,
                    assistant_message_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_workspace_root,
                    next_cwd,
                    next_policy.model_dump_json(),
                    next_route_kind,
                    next_user_message_id,
                    next_assistant_message_id,
                    updated_at.isoformat(),
                    turn_id,
                ),
            )
            self._connection.commit()

        return record.model_copy(
            update={
                "workspace_root": next_workspace_root,
                "cwd": next_cwd,
                "policy": next_policy,
                "route_kind": next_route_kind,
                "user_message_id": next_user_message_id,
                "assistant_message_id": next_assistant_message_id,
                "updated_at": updated_at,
            }
        )

    def list_turn_records(
        self, conversation_id: str, limit: int = 100
    ) -> list[ConversationTurnRecord]:
        rows = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                mode,
                user_text,
                workspace_root,
                cwd,
                policy_json,
                route_kind,
                user_message_id,
                assistant_message_id,
                created_at,
                updated_at
            FROM conversation_turns
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows.reverse()
        return [self._row_to_turn_record(row) for row in rows]

    def append_item(self, item: ConversationItem) -> ConversationItem:
        with self._lock:
            self._insert_item_locked(item)
            self._connection.commit()
        return item

    def list_items(
        self, conversation_id: str, *, turn_id: str | None = None, limit: int = 500
    ) -> list[ConversationItem]:
        if turn_id:
            rows = self._fetchall(
                """
                SELECT
                    id,
                    conversation_id,
                    turn_id,
                    item_kind,
                    summary,
                    payload_json,
                    created_at
                FROM conversation_items
                WHERE conversation_id = ? AND turn_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, turn_id, limit),
            )
        else:
            rows = self._fetchall(
                """
                SELECT
                    id,
                    conversation_id,
                    turn_id,
                    item_kind,
                    summary,
                    payload_json,
                    created_at
                FROM conversation_items
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
        rows.reverse()
        return [self._row_to_item(row) for row in rows]

    def list_recent_messages(
        self, conversation_id: str, limit: int = 8
    ) -> list[ConversationMessage]:
        rows = self._fetchall(
            """
            SELECT id, role, content
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows.reverse()
        assets_by_message = self._list_assets_for_messages([row["id"] for row in rows])
        messages: list[ConversationMessage] = []
        for row in rows:
            content = row["content"]
            assets = assets_by_message.get(row["id"], [])
            if assets:
                attachment_lines = []
                for asset in assets:
                    detail = asset.analysis_summary or f"{asset.kind.value} attachment"
                    attachment_lines.append(f"- {asset.display_name}: {detail}")
                content = f"{content}\n\nAttached assets:\n" + "\n".join(attachment_lines)
            messages.append(ConversationMessage(role=row["role"], content=content))
        return messages

    def list_transcript(
        self, conversation_id: str, limit: int = 200
    ) -> list[TranscriptMessage]:
        rows = self._fetchall(
            """
            SELECT id, role, content, created_at, turn_id, evidence_packet_json
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows.reverse()
        message_ids = [row["id"] for row in rows]
        assets_by_message = self._list_assets_for_messages(message_ids)
        approvals_by_turn = self._list_current_approvals_for_conversation(conversation_id)
        return [
            TranscriptMessage(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                turn_id=row["turn_id"],
                assets=assets_by_message.get(row["id"], []),
                approval=(
                    approvals_by_turn.get(row["turn_id"])
                    if row["role"] == "assistant" and row["turn_id"]
                    else None
                ),
                evidence_packet=(
                    EvidencePacket.model_validate_json(row["evidence_packet_json"])
                    if row["evidence_packet_json"]
                    else None
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_conversation_memory(
        self, entry: ConversationMemoryEntry
    ) -> ConversationMemoryEntry:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversation_memories (
                    id,
                    conversation_id,
                    turn_id,
                    kind,
                    topic,
                    summary,
                    keywords_json,
                    source_domain,
                    asset_ids_json,
                    tool_name,
                    referent_title,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.conversation_id,
                    entry.turn_id,
                    entry.kind.value,
                    entry.topic,
                    entry.summary,
                    json.dumps(entry.keywords),
                    entry.source_domain.value if entry.source_domain else None,
                    json.dumps(entry.asset_ids),
                    entry.tool_name,
                    entry.referent_title,
                    entry.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        return entry

    def list_conversation_memories(
        self, conversation_id: str, limit: int = 12
    ) -> list[ConversationMemoryEntry]:
        rows = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                turn_id,
                kind,
                topic,
                summary,
                keywords_json,
                source_domain,
                asset_ids_json,
                tool_name,
                referent_title,
                created_at
            FROM conversation_memories
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        return [
            ConversationMemoryEntry(
                id=row["id"],
                conversation_id=row["conversation_id"],
                turn_id=row["turn_id"],
                kind=row["kind"],
                topic=row["topic"],
                summary=row["summary"],
                keywords=json.loads(row["keywords_json"] or "[]"),
                source_domain=row["source_domain"],
                asset_ids=json.loads(row["asset_ids_json"] or "[]"),
                tool_name=row["tool_name"],
                referent_title=row["referent_title"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_asset_record(
        self,
        *,
        asset_id: str,
        source_path: str,
        display_name: str,
        description: str | None,
        media_type: str | None,
        kind: AssetKind,
        byte_size: int | None,
        local_path: str | None,
        care_context: AssetCareContext,
        analysis_status: AssetAnalysisStatus,
        analysis_summary: str | None,
    ) -> AssetSummary:
        created_at = utc_now().isoformat()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO assets (
                    id,
                    source_path,
                    description,
                    created_at,
                    display_name,
                    media_type,
                    kind,
                    byte_size,
                    local_path,
                    care_context,
                    analysis_status,
                    analysis_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    source_path,
                    description,
                    created_at,
                    display_name,
                    media_type,
                    kind.value,
                    byte_size,
                    local_path,
                    care_context.value,
                    analysis_status.value,
                    analysis_summary,
                ),
            )
            self._connection.commit()
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        return asset

    def get_asset(self, asset_id: str) -> AssetSummary | None:
        row = self._fetchone(
            """
            SELECT
                id,
                source_path,
                description,
                created_at,
                display_name,
                media_type,
                kind,
                byte_size,
                local_path,
                care_context,
                analysis_status,
                analysis_summary
            FROM assets
            WHERE id = ?
            """,
            (asset_id,),
        )
        return self._row_to_asset_summary(row) if row else None

    def get_asset_local_path(self, asset_id: str) -> str | None:
        row = self._fetchone("SELECT local_path FROM assets WHERE id = ?", (asset_id,))
        if row is None:
            return None
        return row["local_path"]

    def list_assets(self, asset_ids: list[str]) -> list[AssetSummary]:
        if not asset_ids:
            return []
        placeholders = ", ".join("?" for _ in asset_ids)
        rows = self._fetchall(
            f"""
            SELECT
                id,
                source_path,
                description,
                created_at,
                display_name,
                media_type,
                kind,
                byte_size,
                local_path,
                care_context,
                analysis_status,
                analysis_summary
            FROM assets
            WHERE id IN ({placeholders})
            """,
            tuple(asset_ids),
        )
        by_id = {row["id"]: self._row_to_asset_summary(row) for row in rows}
        return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]

    def import_knowledge_pack(
        self, request: KnowledgePackImportRequest
    ) -> KnowledgePackImportResult:
        pack_id = new_id("pack")
        created_at = utc_now().isoformat()
        documents = request.documents or [
            KnowledgeDocumentInput(
                label=f"{request.name} Overview",
                text=f"Imported placeholder content from {request.source_path}.",
            )
        ]

        chunk_rows: list[tuple[str, TextChunk, list[float]]] = []
        for document in documents:
            chunks = self.chunker.chunk_document(document.label, document.text)
            embeddings = self.embedding_provider.embed_texts([chunk.text for chunk in chunks])
            for chunk, vector in zip(chunks, embeddings, strict=True):
                asset_id = new_id("asset")
                chunk_rows.append((asset_id, chunk, vector))

        with self._lock:
            self._connection.execute(
                """
                INSERT INTO knowledge_packs (
                    id, name, source_path, description, tags_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_id,
                    request.name,
                    request.source_path,
                    request.description,
                    json.dumps(request.tags),
                    created_at,
                ),
            )

            for index, (asset_id, chunk, vector) in enumerate(chunk_rows, start=1):
                chunk_id = f"{pack_id}_chunk_{index}"
                self._connection.execute(
                    """
                    INSERT INTO assets (
                        id,
                        source_path,
                        description,
                        created_at,
                        display_name,
                        media_type,
                        kind,
                        byte_size,
                        local_path,
                        care_context,
                        analysis_status,
                        analysis_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        request.source_path,
                        f"Imported knowledge chunk for {chunk.source_label}",
                        created_at,
                        chunk.display_label,
                        "text/plain",
                        AssetKind.DOCUMENT.value,
                        len(chunk.text.encode("utf-8")),
                        None,
                        AssetCareContext.GENERAL.value,
                        AssetAnalysisStatus.READY.value,
                        f"Knowledge chunk imported from {request.name}.",
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id,
                        knowledge_pack_id,
                        asset_id,
                        label,
                        text,
                        created_at,
                        chunk_index,
                        token_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        pack_id,
                        asset_id,
                        chunk.display_label,
                        chunk.text,
                        created_at,
                        chunk.chunk_index,
                        chunk.token_count,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO knowledge_chunks_fts (
                        chunk_id, knowledge_pack_id, asset_id, label, text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        pack_id,
                        asset_id,
                        chunk.display_label,
                        chunk.text,
                    ),
                )
                self._upsert_embedding(chunk_id, vector, created_at)

            self._connection.commit()

        return KnowledgePackImportResult(
            knowledge_pack_id=pack_id,
            imported_document_count=len(documents),
            queued_chunks=len(chunk_rows),
        )

    def ingest_assets(self, request: AssetIngestRequest) -> AssetIngestResult:
        asset_ids: list[str] = []
        with self._lock:
            for source_path in request.source_paths:
                asset_id = new_id("asset")
                path = Path(source_path)
                byte_size = path.stat().st_size if path.exists() else None
                media_type = _guess_media_type(source_path)
                kind = _guess_asset_kind(media_type, path.name)
                analysis_summary = _default_analysis_summary(
                    display_name=path.name or source_path,
                    media_type=media_type,
                    byte_size=byte_size,
                    kind=kind,
                    care_context=AssetCareContext.GENERAL,
                )
                self._connection.execute(
                    """
                    INSERT INTO assets (
                        id,
                        source_path,
                        description,
                        created_at,
                        display_name,
                        media_type,
                        kind,
                        byte_size,
                        local_path,
                        care_context,
                        analysis_status,
                        analysis_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        source_path,
                        request.description,
                        utc_now().isoformat(),
                        path.name or source_path,
                        media_type,
                        kind.value,
                        byte_size,
                        source_path,
                        AssetCareContext.GENERAL.value,
                        AssetAnalysisStatus.METADATA_ONLY.value,
                        analysis_summary,
                    ),
                )
                asset_ids.append(asset_id)
            self._connection.commit()

        return AssetIngestResult(asset_ids=asset_ids, queued_jobs=len(asset_ids))

    def search_library(self, request: LibrarySearchRequest) -> list[SearchResultItem]:
        tokens = self._tokenize(request.query)
        query_vector = self.embedding_provider.embed_texts([request.query])[0]

        lexical_rows = self._fts_search(tokens, request)
        if not lexical_rows:
            lexical_rows = self._fallback_search(tokens, request)

        lexical_candidates: dict[str, ChunkCandidate] = {}
        lexical_max = 0.0
        for row in lexical_rows:
            score = self._lexical_score(request.query, row["label"], row["text"])
            lexical_max = max(lexical_max, score)
            lexical_candidates[row["chunk_id"]] = ChunkCandidate(
                asset_id=row["asset_id"],
                chunk_id=row["chunk_id"],
                label=row["label"],
                text=row["text"],
                lexical_score=score,
            )

        semantic_candidates = self._semantic_search(query_vector, request)
        merged: dict[str, ChunkCandidate] = dict(lexical_candidates)

        for candidate in semantic_candidates:
            existing = merged.get(candidate.chunk_id)
            if existing is None:
                merged[candidate.chunk_id] = candidate
                continue
            existing.semantic_score = max(existing.semantic_score, candidate.semantic_score)
            existing.lexical_score = max(existing.lexical_score, candidate.lexical_score)

        results: list[SearchResultItem] = []
        for candidate in merged.values():
            lexical_norm = candidate.lexical_score / lexical_max if lexical_max > 0 else 0.0
            semantic_norm = max(candidate.semantic_score, 0.0)
            combined = (self.lexical_weight * lexical_norm) + (
                self.semantic_weight * semantic_norm
            )
            if combined <= 0:
                continue
            results.append(
                SearchResultItem(
                    asset_id=candidate.asset_id,
                    chunk_id=candidate.chunk_id,
                    label=candidate.label,
                    excerpt=candidate.text[:220],
                    score=round(combined, 6),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[: request.limit]

    def create_approval(
        self,
        conversation_id: str,
        turn_id: str,
        tool_name: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> ApprovalState:
        approval = ApprovalState(
            id=new_id("approval"),
            conversation_id=conversation_id,
            turn_id=turn_id,
            run_id=run_id,
            tool_name=tool_name,
            reason=reason,
            status="pending",
            payload=payload or {},
        )
        created_at = utc_now()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO approvals (
                    id, conversation_id, turn_id, run_id, tool_name, reason, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.conversation_id,
                    approval.turn_id,
                    approval.run_id,
                    approval.tool_name,
                    approval.reason,
                    approval.status,
                    json.dumps(approval.payload),
                    created_at.isoformat(),
                ),
            )
            self._insert_approval_item_locked(
                approval,
                summary=f"Pending approval for {tool_name}.",
                created_at=created_at,
            )
            self._connection.commit()
        return approval

    def get_approval(self, approval_id: str) -> ApprovalState | None:
        row = self._fetchone(
            """
            SELECT id, conversation_id, turn_id, run_id, tool_name, reason, status, payload_json, result_json
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        )
        return self._row_to_approval(row) if row else None

    def update_approval_payload(
        self,
        approval_id: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> ApprovalState:
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)

        next_turn_id = turn_id or approval.turn_id
        updated_at = utc_now()
        next_approval = approval.model_copy(update={"payload": payload, "turn_id": next_turn_id})
        with self._lock:
            self._connection.execute(
                "UPDATE approvals SET payload_json = ?, turn_id = ? WHERE id = ?",
                (json.dumps(payload), next_turn_id, approval_id),
            )
            self._insert_approval_item_locked(
                next_approval,
                summary=f"Updated pending approval for {approval.tool_name}.",
                created_at=updated_at,
                extra_payload={"previous_turn_id": approval.turn_id},
            )
            self._connection.commit()

        return next_approval

    def resolve_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalState:
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)

        status = "approved" if decision.action == "approve" else decision.action.value
        next_payload = approval.payload if payload is None else payload
        next_approval = approval.model_copy(update={"status": status, "payload": next_payload})
        with self._lock:
            self._connection.execute(
                "UPDATE approvals SET status = ?, payload_json = ? WHERE id = ?",
                (status, json.dumps(next_payload), approval_id),
            )
            self._insert_approval_item_locked(
                next_approval,
                summary=f"{approval.tool_name} marked {status}.",
                created_at=utc_now(),
            )
            self._connection.commit()

        return next_approval

    def finalize_approval(
        self, approval_id: str, status: str, result: dict[str, Any] | None = None
    ) -> ApprovalState:
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)

        executed_at = utc_now()
        next_approval = approval.model_copy(update={"status": status, "result": result})
        with self._lock:
            self._connection.execute(
                """
                UPDATE approvals
                SET status = ?, result_json = ?, executed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    executed_at.isoformat(),
                    approval_id,
                ),
            )
            self._insert_approval_item_locked(
                next_approval,
                summary=f"{approval.tool_name} finalized as {status}.",
                created_at=executed_at,
            )
            self._connection.commit()

        return next_approval

    def create_medical_session(self, conversation_id: str) -> MedicalSession:
        session = MedicalSession(id=new_id("med"), conversation_id=conversation_id)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO medical_sessions (id, conversation_id, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.conversation_id,
                    session.status,
                    session.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        return session

    def create_export(self, request: ExportRequest, status: str = "queued") -> ExportResult:
        export = ExportResult(
            export_id=new_id("export"),
            destination_path=request.destination_path,
            status=status,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO exports (
                    id, conversation_id, export_type, destination_path, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    export.export_id,
                    request.conversation_id,
                    request.export_type,
                    export.destination_path,
                    export.status,
                    utc_now().isoformat(),
                ),
            )
            self._connection.commit()
        return export

    def create_agent_run(
        self,
        conversation_id: str,
        turn_id: str,
        goal: str,
        scope_root: str,
        *,
        status: AgentRunStatus = AgentRunStatus.RUNNING,
        plan_steps: list[AgentRunStep] | None = None,
        executed_steps: list[AgentRunStep] | None = None,
        result_summary: str | None = None,
        artifact_ids: list[str] | None = None,
        approval_id: str | None = None,
    ) -> AgentRun:
        now = utc_now()
        run = AgentRun(
            id=new_id("run"),
            conversation_id=conversation_id,
            turn_id=turn_id,
            goal=goal,
            scope_root=scope_root,
            status=status,
            plan_steps=plan_steps or [],
            executed_steps=executed_steps or [],
            result_summary=result_summary,
            artifact_ids=artifact_ids or [],
            approval_id=approval_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO agent_runs (
                    id,
                    conversation_id,
                    turn_id,
                    goal,
                    scope_root,
                    status,
                    plan_steps_json,
                    executed_steps_json,
                    result_summary,
                    artifact_ids_json,
                    approval_id,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.conversation_id,
                    run.turn_id,
                    run.goal,
                    run.scope_root,
                    run.status.value,
                    json.dumps([step.model_dump(mode="json") for step in run.plan_steps]),
                    json.dumps([step.model_dump(mode="json") for step in run.executed_steps]),
                    run.result_summary,
                    json.dumps(run.artifact_ids),
                    run.approval_id,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                ),
            )
            self._insert_item_locked(
                ConversationItem(
                    id=new_id("item"),
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    kind=ConversationItemKind.AGENT_RUN,
                    summary=goal,
                    payload={
                        "run_id": run.id,
                        "status": run.status.value,
                        "scope_root": run.scope_root,
                        "approval_id": run.approval_id,
                    },
                    created_at=now,
                )
            )
            self._connection.commit()
        return run

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        row = self._fetchone(
            """
            SELECT
                id,
                conversation_id,
                turn_id,
                goal,
                scope_root,
                status,
                plan_steps_json,
                executed_steps_json,
                result_summary,
                artifact_ids_json,
                approval_id,
                created_at,
                updated_at
            FROM agent_runs
            WHERE id = ?
            """,
            (run_id,),
        )
        return self._row_to_agent_run(row) if row else None

    def list_agent_runs(self, conversation_id: str) -> list[AgentRun]:
        rows = self._fetchall(
            """
            SELECT
                id,
                conversation_id,
                turn_id,
                goal,
                scope_root,
                status,
                plan_steps_json,
                executed_steps_json,
                result_summary,
                artifact_ids_json,
                approval_id,
                created_at,
                updated_at
            FROM agent_runs
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        return [self._row_to_agent_run(row) for row in rows]

    def update_agent_run(
        self,
        run_id: str,
        *,
        scope_root: str | object = _UNSET,
        status: AgentRunStatus | str | object = _UNSET,
        plan_steps: list[AgentRunStep] | object = _UNSET,
        executed_steps: list[AgentRunStep] | object = _UNSET,
        result_summary: str | None | object = _UNSET,
        artifact_ids: list[str] | object = _UNSET,
        approval_id: str | None | object = _UNSET,
    ) -> AgentRun:
        run = self.get_agent_run(run_id)
        if run is None:
            raise KeyError(run_id)

        next_scope_root = run.scope_root if scope_root is _UNSET else str(scope_root)
        next_status = (
            run.status
            if status is _UNSET
            else (status if isinstance(status, AgentRunStatus) else AgentRunStatus(status))
        )
        next_plan_steps = run.plan_steps if plan_steps is _UNSET else list(plan_steps)
        next_executed_steps = (
            run.executed_steps if executed_steps is _UNSET else list(executed_steps)
        )
        next_result_summary = (
            run.result_summary if result_summary is _UNSET else result_summary
        )
        next_artifact_ids = run.artifact_ids if artifact_ids is _UNSET else list(artifact_ids)
        next_approval_id = run.approval_id if approval_id is _UNSET else approval_id
        updated_at = utc_now()

        with self._lock:
            self._connection.execute(
                """
                UPDATE agent_runs
                SET
                    scope_root = ?,
                    status = ?,
                    plan_steps_json = ?,
                    executed_steps_json = ?,
                    result_summary = ?,
                    artifact_ids_json = ?,
                    approval_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_scope_root,
                    next_status.value,
                    json.dumps([step.model_dump(mode="json") for step in next_plan_steps]),
                    json.dumps([step.model_dump(mode="json") for step in next_executed_steps]),
                    next_result_summary,
                    json.dumps(next_artifact_ids),
                    next_approval_id,
                    updated_at.isoformat(),
                    run_id,
                ),
            )
            self._insert_item_locked(
                ConversationItem(
                    id=new_id("item"),
                    conversation_id=run.conversation_id,
                    turn_id=run.turn_id,
                    kind=ConversationItemKind.AGENT_RUN,
                    summary=next_result_summary or run.goal,
                    payload={
                        "run_id": run.id,
                        "status": next_status.value,
                        "scope_root": next_scope_root,
                        "approval_id": next_approval_id,
                        "artifact_ids": next_artifact_ids,
                    },
                    created_at=updated_at,
                )
            )
            self._connection.commit()

        return run.model_copy(
            update={
                "scope_root": next_scope_root,
                "status": next_status,
                "plan_steps": next_plan_steps,
                "executed_steps": next_executed_steps,
                "result_summary": next_result_summary,
                "artifact_ids": next_artifact_ids,
                "approval_id": next_approval_id,
                "updated_at": updated_at,
            }
        )

    def create_note(self, title: str, content: str, kind: str = "note") -> Note:
        note = Note(
            id=new_id("note"),
            title=title,
            content=content,
            kind=kind,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO notes (id, title, content, kind, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    note.id,
                    note.title,
                    note.content,
                    note.kind,
                    note.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        return note

    def list_notes(self) -> list[Note]:
        rows = self._fetchall(
            "SELECT id, title, content, kind, created_at FROM notes ORDER BY created_at DESC"
        )
        return [
            Note(
                id=row["id"],
                title=row["title"],
                content=row["content"],
                kind=row["kind"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_task(
        self, title: str, details: str | None = None, status: str = "open"
    ) -> Task:
        task = Task(id=new_id("task"), title=title, details=details, status=status)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO tasks (id, title, details, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.title,
                    task.details,
                    task.status,
                    task.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        return task

    def list_tasks(self) -> list[Task]:
        rows = self._fetchall(
            "SELECT id, title, details, status, created_at FROM tasks ORDER BY created_at DESC"
        )
        return [
            Task(
                id=row["id"],
                title=row["title"],
                details=row["details"],
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_audit(self, event_type: str, details: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO audit_log (event_type, details_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    event_type,
                    json.dumps(details, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )
            self._connection.commit()

    def _backfill_missing_embeddings(self) -> None:
        rows = self._fetchall(
            """
            SELECT kc.chunk_id, kc.text
            FROM knowledge_chunks kc
            LEFT JOIN knowledge_chunk_embeddings ke ON ke.chunk_id = kc.chunk_id
            WHERE ke.chunk_id IS NULL
               OR ke.provider != ?
               OR ke.model != ?
               OR ke.dimensions != ?
            ORDER BY kc.id ASC
            """,
            (
                self.embedding_provider.provider_name,
                self.embedding_provider.model_id,
                self.embedding_provider.dimensions,
            ),
        )
        if not rows:
            return

        embeddings = self.embedding_provider.embed_texts([row["text"] for row in rows])
        created_at = utc_now().isoformat()
        with self._lock:
            for row, vector in zip(rows, embeddings, strict=True):
                self._upsert_embedding(row["chunk_id"], vector, created_at)
            self._connection.commit()

    def _upsert_embedding(self, chunk_id: str, vector: list[float], created_at: str) -> None:
        self._connection.execute(
            """
            INSERT INTO knowledge_chunk_embeddings (
                chunk_id, provider, model, dimensions, vector_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                dimensions = excluded.dimensions,
                vector_json = excluded.vector_json,
                created_at = excluded.created_at
            """,
            (
                chunk_id,
                self.embedding_provider.provider_name,
                self.embedding_provider.model_id,
                self.embedding_provider.dimensions,
                json.dumps(vector),
                created_at,
            ),
        )

    def _fts_search(self, tokens: list[str], request: LibrarySearchRequest) -> list[sqlite3.Row]:
        if not tokens:
            return []

        match_query = " OR ".join(tokens)
        sql = """
            SELECT asset_id, chunk_id, label, text
            FROM knowledge_chunks_fts
            WHERE knowledge_chunks_fts MATCH ?
        """
        params: list[Any] = [match_query]
        if request.enabled_knowledge_pack_ids:
            placeholders = ", ".join("?" for _ in request.enabled_knowledge_pack_ids)
            sql += f" AND knowledge_pack_id IN ({placeholders})"
            params.extend(request.enabled_knowledge_pack_ids)
        sql += f" LIMIT {self.candidate_limit}"

        try:
            return self._fetchall(sql, tuple(params))
        except sqlite3.OperationalError:
            return []

    def _fallback_search(
        self, tokens: list[str], request: LibrarySearchRequest
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT asset_id, chunk_id, label, text
            FROM knowledge_chunks
        """
        conditions: list[str] = []
        params: list[Any] = []

        if request.enabled_knowledge_pack_ids:
            placeholders = ", ".join("?" for _ in request.enabled_knowledge_pack_ids)
            conditions.append(f"knowledge_pack_id IN ({placeholders})")
            params.extend(request.enabled_knowledge_pack_ids)

        if tokens:
            token_conditions: list[str] = []
            for token in tokens:
                token_conditions.append("(LOWER(label) LIKE ? OR LOWER(text) LIKE ?)")
                like = f"%{token}%"
                params.extend([like, like])
            conditions.append("(" + " OR ".join(token_conditions) + ")")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += f" LIMIT {self.candidate_limit}"

        return self._fetchall(sql, tuple(params))

    def _semantic_search(
        self, query_vector: list[float], request: LibrarySearchRequest
    ) -> list[ChunkCandidate]:
        sql = """
            SELECT
                kc.asset_id,
                kc.chunk_id,
                kc.label,
                kc.text,
                ke.vector_json
            FROM knowledge_chunks kc
            JOIN knowledge_chunk_embeddings ke ON ke.chunk_id = kc.chunk_id
            WHERE ke.provider = ?
              AND ke.model = ?
        """
        params: list[Any] = [
            self.embedding_provider.provider_name,
            self.embedding_provider.model_id,
        ]

        if request.enabled_knowledge_pack_ids:
            placeholders = ", ".join("?" for _ in request.enabled_knowledge_pack_ids)
            sql += f" AND kc.knowledge_pack_id IN ({placeholders})"
            params.extend(request.enabled_knowledge_pack_ids)

        rows = self._fetchall(sql, tuple(params))
        candidates: list[ChunkCandidate] = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            score = self._cosine_similarity(query_vector, vector)
            candidates.append(
                ChunkCandidate(
                    asset_id=row["asset_id"],
                    chunk_id=row["chunk_id"],
                    label=row["label"],
                    text=row["text"],
                    semantic_score=score,
                )
            )

        candidates.sort(key=lambda item: item.semantic_score, reverse=True)
        return candidates[: self.candidate_limit]

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection.execute(sql, params).fetchall())

    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            title=row["title"],
            mode=AssistantMode(row["mode"]),
            created_at=row["created_at"],
            archived_at=row["archived_at"] if "archived_at" in row.keys() else None,
            workspace_binding=(
                WorkspaceBinding.model_validate_json(row["workspace_binding_json"])
                if "workspace_binding_json" in row.keys() and row["workspace_binding_json"]
                else None
            ),
            parent_conversation_id=(
                row["parent_conversation_id"]
                if "parent_conversation_id" in row.keys()
                else None
            ),
            forked_from_turn_id=(
                row["forked_from_turn_id"] if "forked_from_turn_id" in row.keys() else None
            ),
        )

    def _row_to_turn_record(self, row: sqlite3.Row) -> ConversationTurnRecord:
        return ConversationTurnRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            mode=AssistantMode(row["mode"]),
            user_text=row["user_text"],
            workspace_root=row["workspace_root"],
            cwd=row["cwd"],
            policy=TurnExecutionPolicy.model_validate_json(row["policy_json"]),
            route_kind=row["route_kind"],
            user_message_id=row["user_message_id"],
            assistant_message_id=row["assistant_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_item(self, row: sqlite3.Row) -> ConversationItem:
        return ConversationItem(
            id=row["id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            kind=ConversationItemKind(row["item_kind"]),
            summary=row["summary"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
        )

    def _row_to_approval(self, row: sqlite3.Row) -> ApprovalState:
        return ApprovalState(
            id=row["id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            run_id=row["run_id"] if "run_id" in row.keys() else None,
            tool_name=row["tool_name"],
            reason=row["reason"],
            status=row["status"],
            payload=json.loads(row["payload_json"] or "{}"),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
        )

    def _row_to_agent_run(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=row["id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            goal=row["goal"],
            scope_root=row["scope_root"],
            status=AgentRunStatus(row["status"]),
            plan_steps=[AgentRunStep.model_validate(item) for item in json.loads(row["plan_steps_json"] or "[]")],
            executed_steps=[
                AgentRunStep.model_validate(item)
                for item in json.loads(row["executed_steps_json"] or "[]")
            ],
            result_summary=row["result_summary"],
            artifact_ids=json.loads(row["artifact_ids_json"] or "[]"),
            approval_id=row["approval_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_asset_summary(self, row: sqlite3.Row) -> AssetSummary:
        content_url = None
        preview_url = None
        local_path = row["local_path"] if "local_path" in row.keys() else None
        kind_value = row["kind"] if "kind" in row.keys() and row["kind"] else AssetKind.OTHER.value
        if local_path:
            content_url = f"/v1/assets/{row['id']}/content"
            if kind_value in {AssetKind.IMAGE.value, AssetKind.VIDEO.value}:
                preview_url = content_url
        return AssetSummary(
            id=row["id"],
            display_name=row["display_name"] or Path(row["source_path"]).name or row["id"],
            source_path=row["source_path"],
            kind=AssetKind(kind_value),
            media_type=row["media_type"] if "media_type" in row.keys() else None,
            byte_size=row["byte_size"] if "byte_size" in row.keys() else None,
            care_context=AssetCareContext(
                row["care_context"]
                if "care_context" in row.keys() and row["care_context"]
                else AssetCareContext.GENERAL.value
            ),
            analysis_status=AssetAnalysisStatus(
                row["analysis_status"]
                if "analysis_status" in row.keys() and row["analysis_status"]
                else AssetAnalysisStatus.METADATA_ONLY.value
            ),
            analysis_summary=row["analysis_summary"] if "analysis_summary" in row.keys() else None,
            content_url=content_url,
            preview_url=preview_url,
            created_at=row["created_at"],
        )

    def _default_fork_title(self, title: str | None) -> str:
        if title and title.strip():
            return f"{title.strip()} (fork)"
        return "Forked conversation"

    def _copy_timestamp_factory(self, start: Any):
        current = start

        def _next():
            nonlocal current
            current = current + timedelta(microseconds=1)
            return current

        return _next

    def _remap_item_payload(
        self,
        payload: dict[str, Any],
        *,
        turn_id_map: dict[str, str],
        message_id_map: dict[str, str],
        approval_id_map: dict[str, str],
        run_id_map: dict[str, str],
    ) -> dict[str, Any]:
        remapped = dict(payload)
        scalar_mappings = {
            "turn_id": turn_id_map,
            "previous_turn_id": turn_id_map,
            "message_id": message_id_map,
            "approval_id": approval_id_map,
            "run_id": run_id_map,
        }
        for key, mapping in scalar_mappings.items():
            value = remapped.get(key)
            if isinstance(value, str) and value in mapping:
                remapped[key] = mapping[value]
        nested_approval = remapped.get("approval")
        if isinstance(nested_approval, dict):
            nested = dict(nested_approval)
            if isinstance(nested.get("id"), str) and nested["id"] in approval_id_map:
                nested["id"] = approval_id_map[nested["id"]]
            if isinstance(nested.get("turn_id"), str) and nested["turn_id"] in turn_id_map:
                nested["turn_id"] = turn_id_map[nested["turn_id"]]
            if isinstance(nested.get("run_id"), str) and nested["run_id"] in run_id_map:
                nested["run_id"] = run_id_map[nested["run_id"]]
            remapped["approval"] = nested
        return remapped

    def _list_assets_for_messages(
        self, message_ids: list[str]
    ) -> dict[str, list[AssetSummary]]:
        if not message_ids:
            return {}
        placeholders = ", ".join("?" for _ in message_ids)
        rows = self._fetchall(
            f"""
            SELECT
                cma.message_id,
                a.id,
                a.source_path,
                a.description,
                a.created_at,
                a.display_name,
                a.media_type,
                a.kind,
                a.byte_size,
                a.local_path,
                a.care_context,
                a.analysis_status,
                a.analysis_summary
            FROM conversation_message_assets cma
            JOIN assets a ON a.id = cma.asset_id
            WHERE cma.message_id IN ({placeholders})
            ORDER BY a.created_at ASC
            """,
            tuple(message_ids),
        )
        assets_by_message: dict[str, list[AssetSummary]] = {}
        for row in rows:
            assets_by_message.setdefault(row["message_id"], []).append(
                self._row_to_asset_summary(row)
            )
        return assets_by_message

    def _list_current_approvals_for_conversation(
        self, conversation_id: str
    ) -> dict[str, ApprovalState]:
        rows = self._fetchall(
            """
            SELECT turn_id, payload_json
            FROM conversation_items
            WHERE conversation_id = ? AND item_kind = ?
            ORDER BY created_at ASC
            """,
            (conversation_id, ConversationItemKind.APPROVAL.value),
        )
        latest_by_approval_id: dict[str, ApprovalState] = {}
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            approval = None
            if isinstance(payload.get("approval"), dict):
                approval = ApprovalState.model_validate(payload["approval"])
            else:
                approval_id = payload.get("approval_id")
                if isinstance(approval_id, str):
                    approval = self.get_approval(approval_id)
            if approval is None:
                continue
            latest_by_approval_id[approval.id] = approval

        approvals_by_turn: dict[str, ApprovalState] = {}
        for approval in latest_by_approval_id.values():
            approvals_by_turn[approval.turn_id] = approval
        return approvals_by_turn

    def _insert_approval_item_locked(
        self,
        approval: ApprovalState,
        *,
        summary: str,
        created_at: Any,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "approval_id": approval.id,
            "tool_name": approval.tool_name,
            "status": approval.status,
            "reason": approval.reason,
            "run_id": approval.run_id,
            "approval": approval.model_dump(mode="json"),
        }
        if extra_payload:
            payload.update(extra_payload)
        self._insert_item_locked(
            ConversationItem(
                id=new_id("item"),
                conversation_id=approval.conversation_id,
                turn_id=approval.turn_id,
                kind=ConversationItemKind.APPROVAL,
                summary=summary,
                payload=payload,
                created_at=created_at,
            )
        )

    def _insert_item_locked(self, item: ConversationItem) -> None:
        self._connection.execute(
            """
            INSERT INTO conversation_items (
                id,
                conversation_id,
                turn_id,
                item_kind,
                summary,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.conversation_id,
                item.turn_id,
                item.kind.value,
                item.summary,
                json.dumps(item.payload),
                item.created_at.isoformat(),
            ),
        )

    def _summarize_item_text(self, text: str, limit: int = 180) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "…"

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [token for token in tokens if len(token) > 1]

    def _lexical_score(self, query: str, label: str, text: str) -> float:
        tokens = self._tokenize(query)
        query_text = query.lower()
        label_text = label.lower()
        body_text = text.lower()

        label_overlap = sum(1 for token in tokens if token in label_text)
        body_overlap = sum(1 for token in tokens if token in body_text)
        exact_label_phrase = 1.0 if label_text and label_text in query_text else 0.0
        score = float((label_overlap * 2.0) + body_overlap + (exact_label_phrase * 3.0))

        guidance_intent = any(
            phrase in query_text
            for phrase in {
                "teach me",
                "show me how",
                "walk me through",
                "help me understand",
                "explain how",
                "how do i",
                "how to",
                "prepare",
            }
        )
        if guidance_intent:
            if "guidance" in label_text:
                score += 4.0
            if "guidance" in body_text:
                score += 1.5
            if "checklist" in label_text:
                score -= 2.0
            if "template" in label_text:
                score -= 1.5

        checklist_intent = any(
            phrase in query_text
            for phrase in {
                "checklist",
                "before departure",
                "for tomorrow",
                "pack",
                "departure",
            }
        )
        if checklist_intent and "checklist" in label_text:
            score += 3.0

        return score

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)


def _guess_media_type(source_path: str) -> str | None:
    suffix = Path(source_path).suffix.lower()
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix in {".webp"}:
        return "image/webp"
    if suffix in {".gif"}:
        return "image/gif"
    if suffix in {".mp4"}:
        return "video/mp4"
    if suffix in {".mov"}:
        return "video/quicktime"
    if suffix in {".webm"}:
        return "video/webm"
    if suffix in {".pdf"}:
        return "application/pdf"
    if suffix in {".mp3"}:
        return "audio/mpeg"
    if suffix in {".wav"}:
        return "audio/wav"
    if suffix in {".txt", ".md"}:
        return "text/plain"
    return None


def _guess_asset_kind(media_type: str | None, source_name: str) -> AssetKind:
    if media_type:
        if media_type.startswith("image/"):
            return AssetKind.IMAGE
        if media_type.startswith("video/"):
            return AssetKind.VIDEO
        if media_type.startswith("audio/"):
            return AssetKind.AUDIO
        if media_type.startswith("text/") or media_type == "application/pdf":
            return AssetKind.DOCUMENT
    suffix = Path(source_name).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return AssetKind.IMAGE
    if suffix in {".mp4", ".mov", ".webm"}:
        return AssetKind.VIDEO
    if suffix in {".pdf", ".txt", ".md"}:
        return AssetKind.DOCUMENT
    if suffix in {".mp3", ".wav"}:
        return AssetKind.AUDIO
    return AssetKind.OTHER


def _format_byte_size(byte_size: int | None) -> str:
    if byte_size is None:
        return "unknown size"
    if byte_size < 1024:
        return f"{byte_size} B"
    if byte_size < 1024 * 1024:
        return f"{byte_size / 1024:.1f} KB"
    return f"{byte_size / (1024 * 1024):.1f} MB"


def _default_analysis_summary(
    *,
    display_name: str,
    media_type: str | None,
    byte_size: int | None,
    kind: AssetKind,
    care_context: AssetCareContext,
) -> str:
    type_label = media_type or kind.value
    size_label = _format_byte_size(byte_size)
    if kind == AssetKind.IMAGE and care_context == AssetCareContext.MEDICAL:
        return (
            f"Attached medical image {display_name} ({type_label}, {size_label}). "
            "Metadata captured locally; specialist medical vision analysis has not run yet."
        )
    if kind == AssetKind.IMAGE:
        return (
            f"Attached image {display_name} ({type_label}, {size_label}). "
            "Metadata captured locally; detailed vision analysis has not run yet."
        )
    if kind == AssetKind.VIDEO:
        return (
            f"Attached video {display_name} ({type_label}, {size_label}). "
            "Metadata captured locally; local tracking or sampled review has not run yet."
        )
    return f"Attached file {display_name} ({type_label}, {size_label})."
