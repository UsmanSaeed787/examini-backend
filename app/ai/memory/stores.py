"""MemoryStore implementations.

- DatabaseMemoryStore: durable, backed by ai_memories (SQLAlchemy stays
  fully encapsulated here — nothing leaks through the interface).
- InProcessMemoryStore: dict-backed; the default SHORT_TERM backend and the
  test double. Same contract, zero infrastructure.

Both are synchronous (callers run them off the event loop, consistent with
the rest of the layer). Expired records are filtered on read and lazily
purged."""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.ai.memory.interfaces import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    freeze_content,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ttl_to_expiry(ttl_seconds: Optional[int]) -> Optional[datetime]:
    return _now() + timedelta(seconds=ttl_seconds) if ttl_seconds else None


def _matches_query(record: MemoryRecord, text: Optional[str]) -> bool:
    if not text:
        return True
    haystack = " ".join(str(v) for v in record.content.values()) + " " + (record.key or "")
    return text.lower() in haystack.lower()


class InProcessMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[tuple, List[MemoryRecord]] = {}

    @staticmethod
    def _bucket(scope: MemoryScope, scope_ref: str, user_id: UUID) -> tuple:
        return (scope.value, scope_ref, str(user_id))

    def append(self, record: MemoryRecord) -> MemoryRecord:
        stored = MemoryRecord(
            id=record.id or uuid.uuid4(),
            scope=record.scope,
            scope_ref=record.scope_ref,
            user_id=record.user_id,
            content=freeze_content(dict(record.content)),
            key=record.key,
            importance=record.importance,
            created_at=record.created_at or _now(),
            expires_at=record.expires_at,
        )
        bucket = self._bucket(record.scope, record.scope_ref, record.user_id)
        with self._lock:
            records = self._records.setdefault(bucket, [])
            if stored.key is not None:  # same key = upsert
                records[:] = [r for r in records if r.key != stored.key]
            records.append(stored)
        return stored

    def recall(self, query: MemoryQuery) -> Tuple[MemoryRecord, ...]:
        bucket = self._bucket(query.scope, query.scope_ref, query.user_id)
        now = _now()
        with self._lock:
            records = list(self._records.get(bucket, ()))
            live = [r for r in records if query.include_expired or not (r.expires_at and r.expires_at <= now)]
            self._records[bucket] = [r for r in records if not (r.expires_at and r.expires_at <= now)]
        if query.key is not None:
            live = [r for r in live if r.key == query.key]
        live = [r for r in live if _matches_query(r, query.query)]
        live.sort(key=lambda r: (r.created_at or now), reverse=True)
        return tuple(live[: query.limit])

    def forget(self, scope: MemoryScope, scope_ref: str, user_id: UUID, key: Optional[str] = None) -> int:
        bucket = self._bucket(scope, scope_ref, user_id)
        with self._lock:
            records = self._records.get(bucket, [])
            before = len(records)
            kept = [] if key is None else [r for r in records if r.key != key]
            self._records[bucket] = kept
            return before - len(kept)

    def clear_scope(self, scope: MemoryScope, scope_ref: str) -> int:
        removed = 0
        with self._lock:
            for bucket in list(self._records.keys()):
                if bucket[0] == scope.value and bucket[1] == scope_ref:
                    removed += len(self._records.pop(bucket))
        return removed


class DatabaseMemoryStore:
    def append(self, record: MemoryRecord) -> MemoryRecord:
        from app.ai.persistence.models import AIMemory
        from app.database import SessionLocal

        with SessionLocal() as db:
            row = None
            if record.key is not None:  # same key = upsert
                row = (
                    db.query(AIMemory)
                    .filter(
                        AIMemory.user_id == record.user_id,
                        AIMemory.scope == record.scope.value,
                        AIMemory.scope_ref == record.scope_ref,
                        AIMemory.key == record.key,
                    )
                    .first()
                )
            if row is None:
                row = AIMemory(
                    user_id=record.user_id,
                    scope=record.scope.value,
                    scope_ref=record.scope_ref,
                    key=record.key,
                )
                db.add(row)
            row.content = dict(record.content)
            row.importance = record.importance
            row.expires_at = record.expires_at
            row.updated_at = _now()
            db.commit()
            db.refresh(row)
            return _to_record(row)

    def recall(self, query: MemoryQuery) -> Tuple[MemoryRecord, ...]:
        from sqlalchemy import String, cast, or_

        from app.ai.persistence.models import AIMemory
        from app.database import SessionLocal

        with SessionLocal() as db:
            q = db.query(AIMemory).filter(
                AIMemory.user_id == query.user_id,
                AIMemory.scope == query.scope.value,
                AIMemory.scope_ref == query.scope_ref,
            )
            if not query.include_expired:
                q = q.filter(or_(AIMemory.expires_at.is_(None), AIMemory.expires_at > _now()))
            if query.key is not None:
                q = q.filter(AIMemory.key == query.key)
            if query.query:
                pattern = f"%{query.query}%"
                q = q.filter(
                    or_(cast(AIMemory.content, String).ilike(pattern), AIMemory.key.ilike(pattern))
                )
            rows = q.order_by(AIMemory.created_at.desc()).limit(query.limit).all()
            return tuple(_to_record(row) for row in rows)

    def forget(self, scope: MemoryScope, scope_ref: str, user_id: UUID, key: Optional[str] = None) -> int:
        from app.ai.persistence.models import AIMemory
        from app.database import SessionLocal

        with SessionLocal() as db:
            q = db.query(AIMemory).filter(
                AIMemory.user_id == user_id,
                AIMemory.scope == scope.value,
                AIMemory.scope_ref == scope_ref,
            )
            if key is not None:
                q = q.filter(AIMemory.key == key)
            removed = q.delete()
            db.commit()
            return removed

    def clear_scope(self, scope: MemoryScope, scope_ref: str) -> int:
        from app.ai.persistence.models import AIMemory
        from app.database import SessionLocal

        with SessionLocal() as db:
            removed = (
                db.query(AIMemory)
                .filter(AIMemory.scope == scope.value, AIMemory.scope_ref == scope_ref)
                .delete()
            )
            db.commit()
            return removed


def _to_record(row) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        scope=MemoryScope(row.scope),
        scope_ref=row.scope_ref,
        user_id=row.user_id,
        content=freeze_content(row.content),
        key=row.key,
        importance=float(row.importance or 0.0),
        created_at=row.created_at,
        expires_at=row.expires_at,
    )
