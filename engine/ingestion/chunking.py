from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    source_label: str
    display_label: str
    chunk_index: int
    text: str
    token_count: int


class DocumentChunker:
    def __init__(
        self,
        *,
        max_chars: int = 420,
        overlap_sentences: int = 1,
        min_chunk_chars: int = 120,
    ) -> None:
        self.max_chars = max_chars
        self.overlap_sentences = overlap_sentences
        self.min_chunk_chars = min_chunk_chars

    def chunk_document(self, label: str, text: str) -> list[TextChunk]:
        normalized = self._normalize(text)
        if len(normalized) <= self.max_chars:
            return [self._build_chunk(label, label, 1, normalized)]

        sentences = self._split_sentences(normalized)
        if len(sentences) <= 1:
            return self._sliding_window_chunks(label, normalized)

        chunks: list[TextChunk] = []
        current_sentences: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence) + (1 if current_sentences else 0)
            if current_sentences and current_length + sentence_length > self.max_chars:
                chunks.append(self._emit_chunk(label, chunks, current_sentences))
                overlap = current_sentences[-self.overlap_sentences :] if self.overlap_sentences else []
                current_sentences = overlap[:]
                current_length = self._joined_length(current_sentences)

            current_sentences.append(sentence)
            current_length = self._joined_length(current_sentences)

        if current_sentences:
            if chunks and current_length < self.min_chunk_chars:
                previous = chunks.pop()
                combined_text = f"{previous.text} {' '.join(current_sentences)}".strip()
                chunks.append(
                    self._build_chunk(
                        label,
                        previous.display_label,
                        previous.chunk_index,
                        combined_text,
                    )
                )
            else:
                chunks.append(self._emit_chunk(label, chunks, current_sentences))

        if len(chunks) == 1:
            only = chunks[0]
            return [
                TextChunk(
                    source_label=only.source_label,
                    display_label=label,
                    chunk_index=1,
                    text=only.text,
                    token_count=only.token_count,
                )
            ]
        return chunks

    def _emit_chunk(
        self, label: str, chunks: list[TextChunk], sentences: list[str]
    ) -> TextChunk:
        chunk_index = len(chunks) + 1
        display_label = f"{label} [chunk {chunk_index}]"
        return self._build_chunk(label, display_label, chunk_index, " ".join(sentences))

    def _build_chunk(
        self, source_label: str, display_label: str, chunk_index: int, text: str
    ) -> TextChunk:
        compact = self._normalize(text)
        return TextChunk(
            source_label=source_label,
            display_label=display_label,
            chunk_index=chunk_index,
            text=compact,
            token_count=len(compact.split()),
        )

    def _sliding_window_chunks(self, label: str, text: str) -> list[TextChunk]:
        window = self.max_chars
        stride = max(window - 80, 80)
        chunks: list[TextChunk] = []
        index = 0
        chunk_index = 1
        while index < len(text):
            segment = text[index : index + window].strip()
            if not segment:
                break
            display_label = label if len(text) <= window else f"{label} [chunk {chunk_index}]"
            chunks.append(self._build_chunk(label, display_label, chunk_index, segment))
            index += stride
            chunk_index += 1
        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        return re.split(r"(?<=[.!?])\s+", text)

    def _joined_length(self, sentences: list[str]) -> int:
        return len(" ".join(sentences))

    def _normalize(self, text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+\n", "\n", text)
        return text.strip()
