from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssistantMode(str, Enum):
    GENERAL = "general"
    FIELD = "field"
    RESEARCH = "research"
    MEDICAL = "medical"


class ResponseStyle(str, Enum):
    CONCISE = "concise"
    NORMAL = "normal"
    DETAILED = "detailed"


class AssetKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    OTHER = "other"


class AssetCareContext(str, Enum):
    GENERAL = "general"
    MEDICAL = "medical"


class AssetAnalysisStatus(str, Enum):
    METADATA_ONLY = "metadata_only"
    READY = "ready"
    FAILED = "failed"


class StreamEventType(str, Enum):
    ASSISTANT_DELTA = "assistant.delta"
    ASSISTANT_MESSAGE_COMPLETED = "assistant.message.completed"
    CITATION_ADDED = "citation.added"
    TURN_STATUS = "turn.status"
    TOOL_PROPOSED = "tool.proposed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    APPROVAL_REQUIRED = "approval.required"
    WARNING = "warning"
    ERROR = "error"


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ResponsePreferences(StrictModel):
    style: ResponseStyle = ResponseStyle.CONCISE
    citations: bool = True
    audio_reply: bool = False


class Conversation(StrictModel):
    id: str
    title: str | None = None
    mode: AssistantMode = AssistantMode.GENERAL
    created_at: datetime = Field(default_factory=utc_now)


class ConversationSummary(StrictModel):
    id: str
    title: str | None = None
    mode: AssistantMode = AssistantMode.GENERAL
    created_at: datetime = Field(default_factory=utc_now)
    last_activity_at: datetime = Field(default_factory=utc_now)
    last_message_preview: str | None = None


class ConversationMessage(StrictModel):
    role: str
    content: str


class AssetSummary(StrictModel):
    id: str
    display_name: str
    source_path: str
    kind: AssetKind = AssetKind.OTHER
    media_type: str | None = None
    byte_size: int | None = None
    care_context: AssetCareContext = AssetCareContext.GENERAL
    analysis_status: AssetAnalysisStatus = AssetAnalysisStatus.METADATA_ONLY
    analysis_summary: str | None = None
    content_url: str | None = None
    preview_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class TranscriptMessage(StrictModel):
    id: str
    role: str
    content: str
    turn_id: str | None = None
    assets: list[AssetSummary] = Field(default_factory=list)
    approval: ApprovalState | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ConversationCreateRequest(StrictModel):
    title: str | None = None
    mode: AssistantMode = AssistantMode.GENERAL


class ConversationTurnRequest(StrictModel):
    conversation_id: str
    mode: AssistantMode = AssistantMode.GENERAL
    text: str
    asset_ids: list[str] = Field(default_factory=list)
    enabled_knowledge_pack_ids: list[str] = Field(default_factory=list)
    response_preferences: ResponsePreferences = Field(default_factory=ResponsePreferences)
    medical_session_id: str | None = None


class SearchResultItem(StrictModel):
    asset_id: str
    chunk_id: str
    label: str
    excerpt: str
    score: float


class ConversationStreamEvent(StrictModel):
    type: StreamEventType
    conversation_id: str
    turn_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentInput(StrictModel):
    label: str
    text: str


class KnowledgePackImportRequest(StrictModel):
    name: str
    source_path: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    documents: list[KnowledgeDocumentInput] = Field(default_factory=list)


class KnowledgePackImportResult(StrictModel):
    knowledge_pack_id: str
    imported_document_count: int
    queued_chunks: int


class AssetIngestRequest(StrictModel):
    source_paths: list[str]
    description: str | None = None


class AssetIngestResult(StrictModel):
    asset_ids: list[str]
    queued_jobs: int


class AssetUploadResponse(StrictModel):
    asset: AssetSummary


class LibrarySearchRequest(StrictModel):
    query: str
    enabled_knowledge_pack_ids: list[str] = Field(default_factory=list)
    limit: int = 5


class LibrarySearchResult(StrictModel):
    results: list[SearchResultItem]


class TranslationRequest(StrictModel):
    text: str | None = None
    asset_id: str | None = None
    source_language: str
    target_language: str


class TranslationResult(StrictModel):
    translated_text: str
    model: str


class ApprovalDecision(StrictModel):
    action: ApprovalAction
    edited_payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalState(StrictModel):
    id: str
    conversation_id: str
    turn_id: str
    tool_name: str
    reason: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None


class Note(StrictModel):
    id: str
    title: str
    content: str
    kind: str = "note"
    created_at: datetime = Field(default_factory=utc_now)


class Task(StrictModel):
    id: str
    title: str
    details: str | None = None
    status: str = "open"
    created_at: datetime = Field(default_factory=utc_now)


class MedicalSession(StrictModel):
    id: str
    conversation_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: str = "active"


class ExportRequest(StrictModel):
    conversation_id: str
    export_type: str
    destination_path: str


class ExportResult(StrictModel):
    export_id: str
    destination_path: str
    status: str


class ToolDescriptor(StrictModel):
    name: str
    requires_confirmation: bool
    namespace: str = "general"
