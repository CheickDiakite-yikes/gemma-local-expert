from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str = "Field Assistant Engine"
    environment: str = "development"
    api_version: str = "v1"
    database_path: str = "data/field-assistant.db"
    asset_storage_dir: str = "data/uploads"

    default_assistant_model: str = "gemma-4-e4b-it"
    assistant_model_source: str | None = None
    default_embedding_model: str = "embeddinggemma-300m"
    embedding_model_source: str | None = None
    default_translation_model: str = "translategemma-4b"
    default_vision_model: str = "paligemma-2"
    vision_model_source: str | None = None
    default_tracking_model: str = "sam3.1"
    tracking_model_source: str | None = None
    default_medical_model: str = "medgemma-1.5-4b"
    medical_model_source: str | None = None
    default_function_model: str = "functiongemma-270m-it"

    assistant_backend: str = "mock"
    specialist_backend: str = "auto"
    tracking_backend: str = "auto"
    assistant_max_tokens: int = 220
    specialist_max_tokens: int = 180
    tracking_resolution: int = 384
    tracking_detect_every: int = 15
    video_sample_frames: int = 4
    assistant_temperature: float = 0.2
    assistant_top_p: float = 0.95
    conversation_history_limit: int = 8
    enable_function_gemma: bool = False
    enable_medical_mode: bool = True
    max_stream_chunk_chars: int = 180
    ingestion_chunk_max_chars: int = 420
    ingestion_chunk_overlap_sentences: int = 1
    ingestion_chunk_min_chars: int = 120
    retrieval_lexical_weight: float = 0.35
    retrieval_semantic_weight: float = 0.65
    retrieval_candidate_limit: int = 24
    embedding_backend: str = "hash"
    embedding_dimensions: int = 128
    embedding_max_length: int = 512


def load_settings() -> Settings:
    return Settings(
        environment=os.getenv("FIELD_ASSISTANT_ENV", "development"),
        database_path=os.getenv("FIELD_ASSISTANT_DB_PATH", "data/field-assistant.db"),
        asset_storage_dir=os.getenv("FIELD_ASSISTANT_ASSET_STORAGE_DIR", "data/uploads"),
        default_assistant_model=os.getenv(
            "FIELD_ASSISTANT_ASSISTANT_MODEL_NAME", "gemma-4-e4b-it"
        ),
        assistant_model_source=os.getenv(
            "FIELD_ASSISTANT_ASSISTANT_MODEL_SOURCE",
            os.getenv("FIELD_ASSISTANT_MODEL_SOURCE"),
        ),
        assistant_backend=os.getenv("FIELD_ASSISTANT_ASSISTANT_BACKEND", "mock"),
        default_embedding_model=os.getenv(
            "FIELD_ASSISTANT_EMBEDDING_MODEL_NAME", "embeddinggemma-300m"
        ),
        embedding_model_source=os.getenv("FIELD_ASSISTANT_EMBEDDING_MODEL_SOURCE"),
        default_vision_model=os.getenv("FIELD_ASSISTANT_VISION_MODEL_NAME", "paligemma-2"),
        vision_model_source=os.getenv("FIELD_ASSISTANT_VISION_MODEL_SOURCE"),
        default_tracking_model=os.getenv("FIELD_ASSISTANT_TRACKING_MODEL_NAME", "sam3.1"),
        tracking_model_source=os.getenv("FIELD_ASSISTANT_TRACKING_MODEL_SOURCE"),
        default_medical_model=os.getenv(
            "FIELD_ASSISTANT_MEDICAL_MODEL_NAME", "medgemma-1.5-4b"
        ),
        medical_model_source=os.getenv("FIELD_ASSISTANT_MEDICAL_MODEL_SOURCE"),
        assistant_max_tokens=int(os.getenv("FIELD_ASSISTANT_ASSISTANT_MAX_TOKENS", "220")),
        specialist_backend=os.getenv("FIELD_ASSISTANT_SPECIALIST_BACKEND", "auto"),
        tracking_backend=os.getenv("FIELD_ASSISTANT_TRACKING_BACKEND", "auto"),
        specialist_max_tokens=int(
            os.getenv("FIELD_ASSISTANT_SPECIALIST_MAX_TOKENS", "180")
        ),
        tracking_resolution=int(
            os.getenv("FIELD_ASSISTANT_TRACKING_RESOLUTION", "384")
        ),
        tracking_detect_every=int(
            os.getenv("FIELD_ASSISTANT_TRACKING_DETECT_EVERY", "15")
        ),
        video_sample_frames=int(
            os.getenv("FIELD_ASSISTANT_VIDEO_SAMPLE_FRAMES", "4")
        ),
        assistant_temperature=float(
            os.getenv("FIELD_ASSISTANT_ASSISTANT_TEMPERATURE", "0.2")
        ),
        assistant_top_p=float(os.getenv("FIELD_ASSISTANT_ASSISTANT_TOP_P", "0.95")),
        conversation_history_limit=int(
            os.getenv("FIELD_ASSISTANT_CONVERSATION_HISTORY_LIMIT", "8")
        ),
        ingestion_chunk_max_chars=int(
            os.getenv("FIELD_ASSISTANT_INGESTION_CHUNK_MAX_CHARS", "420")
        ),
        ingestion_chunk_overlap_sentences=int(
            os.getenv("FIELD_ASSISTANT_INGESTION_CHUNK_OVERLAP_SENTENCES", "1")
        ),
        ingestion_chunk_min_chars=int(
            os.getenv("FIELD_ASSISTANT_INGESTION_CHUNK_MIN_CHARS", "120")
        ),
        retrieval_lexical_weight=float(
            os.getenv("FIELD_ASSISTANT_RETRIEVAL_LEXICAL_WEIGHT", "0.35")
        ),
        retrieval_semantic_weight=float(
            os.getenv("FIELD_ASSISTANT_RETRIEVAL_SEMANTIC_WEIGHT", "0.65")
        ),
        retrieval_candidate_limit=int(
            os.getenv("FIELD_ASSISTANT_RETRIEVAL_CANDIDATE_LIMIT", "24")
        ),
        embedding_backend=os.getenv("FIELD_ASSISTANT_EMBEDDING_BACKEND", "hash"),
        embedding_dimensions=int(os.getenv("FIELD_ASSISTANT_EMBEDDING_DIMENSIONS", "128")),
        embedding_max_length=int(os.getenv("FIELD_ASSISTANT_EMBEDDING_MAX_LENGTH", "512")),
        enable_function_gemma=os.getenv(
            "FIELD_ASSISTANT_ENABLE_FUNCTION_GEMMA", "false"
        ).lower()
        in {"1", "true", "yes"},
        enable_medical_mode=os.getenv(
            "FIELD_ASSISTANT_ENABLE_MEDICAL_MODE", "true"
        ).lower()
        in {"1", "true", "yes"},
    )
