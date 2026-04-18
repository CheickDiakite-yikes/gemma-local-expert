from engine.ingestion.chunking import DocumentChunker


def test_chunker_splits_long_document() -> None:
    chunker = DocumentChunker(max_chars=120, overlap_sentences=1, min_chunk_chars=40)
    text = (
        "Sentence one explains the visit plan. "
        "Sentence two captures the checklist details and travel prep. "
        "Sentence three covers supply risks and batteries. "
        "Sentence four records follow-up notes for tomorrow."
    )

    chunks = chunker.chunk_document("Visit Plan", text)

    assert len(chunks) >= 2
    assert chunks[0].display_label.startswith("Visit Plan")
    assert chunks[0].token_count > 0
