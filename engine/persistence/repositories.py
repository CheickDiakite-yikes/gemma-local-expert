from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass
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
    ConversationMessage,
    ConversationMemoryEntry,
    ConversationSummary,
    ConversationCreateRequest,
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

    def list_conversations(self, limit: int = 50) -> list[ConversationSummary]: ...

    def delete_conversation(self, conversation_id: str) -> bool: ...

    def ensure_conversation(
        self, conversation_id: str, mode: AssistantMode = AssistantMode.GENERAL
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
        self, approval_id: str, payload: dict[str, Any]
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
        conversation = Conversation(id=new_id("conv"), title=request.title, mode=request.mode)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversations (id, title, mode, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation.id,
                    conversation.title,
                    conversation.mode.value,
                    conversation.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = self._fetchone(
            "SELECT id, title, mode, created_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return self._row_to_conversation(row) if row else None

    def list_conversations(self, limit: int = 50) -> list[ConversationSummary]:
        rows = self._fetchall(
            """
            SELECT
                c.id,
                c.title,
                c.mode,
                c.created_at,
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
            GROUP BY c.id, c.title, c.mode, c.created_at
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

    def ensure_conversation(
        self, conversation_id: str, mode: AssistantMode = AssistantMode.GENERAL
    ) -> Conversation:
        existing = self.get_conversation(conversation_id)
        if existing:
            return existing

        conversation = Conversation(id=conversation_id, mode=mode)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO conversations (id, title, mode, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation.id,
                    conversation.title,
                    conversation.mode.value,
                    conversation.created_at.isoformat(),
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
        approvals_by_turn = self._list_approvals_for_turns(
            [row["turn_id"] for row in rows if row["turn_id"]]
        )
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
                    utc_now().isoformat(),
                ),
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
        self, approval_id: str, payload: dict[str, Any]
    ) -> ApprovalState:
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)

        with self._lock:
            self._connection.execute(
                "UPDATE approvals SET payload_json = ? WHERE id = ?",
                (json.dumps(payload), approval_id),
            )
            self._connection.commit()

        return approval.model_copy(update={"payload": payload})

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
        with self._lock:
            self._connection.execute(
                "UPDATE approvals SET status = ?, payload_json = ? WHERE id = ?",
                (status, json.dumps(next_payload), approval_id),
            )
            self._connection.commit()

        return approval.model_copy(update={"status": status, "payload": next_payload})

    def finalize_approval(
        self, approval_id: str, status: str, result: dict[str, Any] | None = None
    ) -> ApprovalState:
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)

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
                    utc_now().isoformat(),
                    approval_id,
                ),
            )
            self._connection.commit()

        return approval.model_copy(update={"status": status, "result": result})

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

    def _list_approvals_for_turns(self, turn_ids: list[str]) -> dict[str, ApprovalState]:
        if not turn_ids:
            return {}

        placeholders = ", ".join("?" for _ in turn_ids)
        rows = self._fetchall(
            f"""
            SELECT id, conversation_id, turn_id, run_id, tool_name, reason, status, payload_json, result_json
            FROM approvals
            WHERE turn_id IN ({placeholders})
            ORDER BY created_at ASC
            """,
            tuple(turn_ids),
        )
        approvals_by_turn: dict[str, ApprovalState] = {}
        for row in rows:
            approvals_by_turn[row["turn_id"]] = self._row_to_approval(row)
        return approvals_by_turn

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

        return float((label_overlap * 2.0) + body_overlap + (exact_label_phrase * 3.0))

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
