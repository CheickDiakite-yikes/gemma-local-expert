from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from engine.api.dependencies import ServiceContainer
from engine.api.routes import (
    approvals,
    assets,
    conversations,
    exports,
    ingest,
    knowledge_packs,
    library,
    medical,
    notes,
    system,
    tasks,
    translate,
)
from engine.audit.service import AuditService
from engine.config.settings import Settings, load_settings
from engine.ingestion.chunking import DocumentChunker
from engine.models.gateway import ModelGateway
from engine.models.runtime import MLXAssistantRuntime, MockAssistantRuntime
from engine.models.video import FFmpegVideoRuntime, MLXSamVideoRuntime, MetadataVideoRuntime
from engine.models.vision import MLXVisionRuntime, MetadataVisionRuntime, TesseractVisionRuntime
from engine.orchestrator.prompting import PromptBuilder
from engine.orchestrator.service import OrchestratorService
from engine.persistence.migrations import apply_migrations
from engine.persistence.repositories import SQLiteStore
from engine.policy.service import PolicyService
from engine.retrieval.embeddings import HashEmbeddingProvider, MLXEmbeddingGemmaProvider
from engine.retrieval.service import RetrievalService
from engine.routing.service import RouterService
from engine.tools.registry import ToolRegistry
from engine.tools.runtime import ToolRuntime


def build_container(settings: Settings | None = None) -> ServiceContainer:
    resolved_settings = settings or load_settings()
    apply_migrations(resolved_settings.database_path)
    chunker = DocumentChunker(
        max_chars=resolved_settings.ingestion_chunk_max_chars,
        overlap_sentences=resolved_settings.ingestion_chunk_overlap_sentences,
        min_chunk_chars=resolved_settings.ingestion_chunk_min_chars,
    )
    if resolved_settings.embedding_backend == "mlx":
        embedding_provider = MLXEmbeddingGemmaProvider(
            model_id=resolved_settings.default_embedding_model,
            model_source=resolved_settings.embedding_model_source,
            max_length=resolved_settings.embedding_max_length,
        )
    elif resolved_settings.embedding_backend == "hash":
        embedding_provider = HashEmbeddingProvider(
            dimensions=resolved_settings.embedding_dimensions
        )
    else:
        raise ValueError(
            f"Unsupported embedding backend: {resolved_settings.embedding_backend}"
        )

    store = SQLiteStore(
        resolved_settings.database_path,
        chunker=chunker,
        embedding_provider=embedding_provider,
        lexical_weight=resolved_settings.retrieval_lexical_weight,
        semantic_weight=resolved_settings.retrieval_semantic_weight,
        candidate_limit=resolved_settings.retrieval_candidate_limit,
    )
    store.seed_demo_content()
    tools = ToolRegistry()
    router = RouterService(tools)
    policy = PolicyService(tools, medical_mode_enabled=resolved_settings.enable_medical_mode)
    retrieval = RetrievalService(store)
    models = ModelGateway(resolved_settings)
    runtime = (
        MLXAssistantRuntime()
        if resolved_settings.assistant_backend == "mlx"
        else MockAssistantRuntime()
    )
    if resolved_settings.specialist_backend == "mlx":
        vision_runtime = MLXVisionRuntime(allow_remote=True)
    elif resolved_settings.specialist_backend == "auto":
        vision_runtime = MLXVisionRuntime(allow_remote=False)
    elif resolved_settings.specialist_backend == "ocr":
        vision_runtime = TesseractVisionRuntime()
    elif resolved_settings.specialist_backend == "mock":
        vision_runtime = MetadataVisionRuntime()
    else:
        raise ValueError(
            f"Unsupported specialist backend: {resolved_settings.specialist_backend}"
        )
    if resolved_settings.tracking_backend == "mlx":
        video_runtime = MLXSamVideoRuntime(
            allow_remote=True,
            artifact_root=resolved_settings.asset_storage_dir,
        )
    elif resolved_settings.tracking_backend == "auto":
        video_runtime = MLXSamVideoRuntime(
            allow_remote=False,
            artifact_root=resolved_settings.asset_storage_dir,
        )
    elif resolved_settings.tracking_backend == "ffmpeg":
        video_runtime = FFmpegVideoRuntime(artifact_root=resolved_settings.asset_storage_dir)
    elif resolved_settings.tracking_backend == "mock":
        video_runtime = MetadataVideoRuntime()
    else:
        raise ValueError(
            f"Unsupported tracking backend: {resolved_settings.tracking_backend}"
        )
    prompt_builder = PromptBuilder()
    tool_runtime = ToolRuntime(
        store,
        asset_storage_dir=resolved_settings.asset_storage_dir,
    )
    audit = AuditService(store)
    orchestrator = OrchestratorService(
        settings=resolved_settings,
        store=store,
        router=router,
        policy=policy,
        retrieval=retrieval,
        models=models,
        runtime=runtime,
        vision_runtime=vision_runtime,
        video_runtime=video_runtime,
        prompt_builder=prompt_builder,
        tool_runtime=tool_runtime,
        audit=audit,
    )
    return ServiceContainer(
        settings=resolved_settings,
        store=store,
        tools=tools,
        router=router,
        policy=policy,
        retrieval=retrieval,
        models=models,
        runtime=runtime,
        vision_runtime=vision_runtime,
        video_runtime=video_runtime,
        prompt_builder=prompt_builder,
        tool_runtime=tool_runtime,
        audit=audit,
        orchestrator=orchestrator,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Field Assistant Engine", version="0.1.0")
    app.state.container = build_container(settings)

    app.include_router(system.router)
    app.include_router(conversations.router)
    app.include_router(assets.router)
    app.include_router(knowledge_packs.router)
    app.include_router(ingest.router)
    app.include_router(library.router)
    app.include_router(notes.router)
    app.include_router(tasks.router)
    app.include_router(translate.router)
    app.include_router(approvals.router)
    app.include_router(medical.router)
    app.include_router(exports.router)

    web_chat_dir = Path(__file__).resolve().parents[2] / "apps" / "web-chat"
    if web_chat_dir.exists():
        app.mount("/chat", StaticFiles(directory=web_chat_dir, html=True), name="chat")

    return app
