from __future__ import annotations

from engine.contracts.api import ConversationTurnRequest, LibrarySearchRequest, SearchResultItem
from engine.persistence.repositories import PersistenceStore


class RetrievalService:
    def __init__(self, store: PersistenceStore) -> None:
        self.store = store

    def search(self, request: LibrarySearchRequest) -> list[SearchResultItem]:
        return self.store.search_library(request)

    def retrieve_for_turn(self, turn: ConversationTurnRequest) -> list[SearchResultItem]:
        request = LibrarySearchRequest(
            query=turn.text,
            enabled_knowledge_pack_ids=turn.enabled_knowledge_pack_ids,
            limit=3,
        )
        return self.search(request)
