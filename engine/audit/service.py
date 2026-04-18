from __future__ import annotations

from engine.persistence.repositories import PersistenceStore


class AuditService:
    def __init__(self, store: PersistenceStore) -> None:
        self.store = store

    def record(self, event_type: str, **details: object) -> None:
        self.store.add_audit(event_type, dict(details))
