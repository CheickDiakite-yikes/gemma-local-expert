from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engine.models.sources import resolve_model_id, resolve_model_source


class EmbeddingProvider(Protocol):
    provider_name: str
    model_id: str
    dimensions: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(slots=True)
class HashEmbeddingProvider:
    dimensions: int = 128
    provider_name: str = "local-hash"
    model_id: str = "local-hash-ngrams-v1"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        lowered = text.lower()
        tokens = re.findall(r"[a-z0-9]+", lowered)

        for token in tokens:
            self._accumulate(vector, token, weight=1.0)
            if len(token) >= 3:
                for size in range(3, min(len(token), 5) + 1):
                    for start in range(0, len(token) - size + 1):
                        self._accumulate(vector, token[start : start + size], weight=0.35)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _accumulate(self, vector: list[float], feature: str, *, weight: float) -> None:
        slot = hash(feature) % self.dimensions
        vector[slot] += weight


class MLXEmbeddingGemmaProvider:
    provider_name = "mlx"

    def __init__(
        self,
        model_id: str = "embeddinggemma-300m",
        model_source: str | None = None,
        max_length: int = 512,
    ) -> None:
        self._configured_model_name = model_id
        self._configured_source = model_source
        self.model_id = resolve_model_id(model_source, model_id)
        self.dimensions = 768
        self.max_length = max_length
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[object, object]] = {}
        resolved_source = resolve_model_source(model_source, model_id)
        if resolved_source is not None:
            self._update_dimensions_from_config(resolved_source)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model, processor = self._load_model()
        batch = processor(
            texts,
            return_tensors="mlx",
            padding=True,
            truncation=True,
            max_length=self.max_length,
        )

        try:
            output = model(**batch)
        except TypeError as exc:
            if "unexpected keyword argument 'input_ids'" not in str(exc):
                raise
            output = model(
                inputs=batch["input_ids"],
                attention_mask=batch.get("attention_mask"),
            )

        embeddings = getattr(output, "text_embeds", None)
        if embeddings is None:
            raise RuntimeError(
                f"Embedding model `{self.model_id}` did not return `text_embeds`."
            )
        return embeddings.tolist()

    def _load_model(self) -> tuple[object, object]:
        resolved_source = resolve_model_source(
            self._configured_source,
            self._configured_model_name,
        )
        if not resolved_source:
            raise RuntimeError(
                "No embedding model source is configured. Set "
                "FIELD_ASSISTANT_EMBEDDING_MODEL_SOURCE or provide a locally cached "
                "EmbeddingGemma model."
            )

        with self._lock:
            cached = self._cache.get(resolved_source)
            if cached is not None:
                return cached

            from mlx_embeddings import load

            model, processor = load(resolved_source)
            hidden_size = getattr(getattr(model, "config", None), "hidden_size", None)
            if isinstance(hidden_size, int) and hidden_size > 0:
                self.dimensions = hidden_size
            self._cache[resolved_source] = (model, processor)
            return model, processor

    def _update_dimensions_from_config(self, source: str) -> None:
        source_path = Path(source).expanduser()
        config_path = source_path / "config.json"
        if not config_path.exists():
            return

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        hidden_size = config.get("hidden_size")
        if isinstance(hidden_size, int) and hidden_size > 0:
            self.dimensions = hidden_size
