"""Persistence for completed transaction review records."""

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from pydantic import TypeAdapter

from bookkeeping_app.domain_contracts import ReviewRecord, ReviewResolution, UserId

RECORD_LIST = TypeAdapter(list[ReviewRecord])


class ReviewRecordStore(Protocol):
    def record(self, record: ReviewRecord) -> ReviewRecord: ...
    def get(self, transaction_id: UUID) -> ReviewRecord | None: ...
    def list_for_user(
        self, user_id: UserId, resolution: ReviewResolution | None = None
    ) -> tuple[ReviewRecord, ...]: ...


class InMemoryReviewRecordStore:
    def __init__(self, records: tuple[ReviewRecord, ...] = ()) -> None:
        self._records = {record.transaction_id: record for record in records}
        self._lock = RLock()

    def record(self, record: ReviewRecord) -> ReviewRecord:
        with self._lock:
            existing = self._records.get(record.transaction_id)
            if existing is not None:
                return existing
            self._records[record.transaction_id] = record
            return record

    def get(self, transaction_id: UUID) -> ReviewRecord | None:
        with self._lock:
            return self._records.get(transaction_id)

    def list_for_user(
        self, user_id: UserId, resolution: ReviewResolution | None = None
    ) -> tuple[ReviewRecord, ...]:
        with self._lock:
            records = (
                record
                for record in self._records.values()
                if record.user_id == user_id
                and (resolution is None or record.resolution is resolution)
            )
            return tuple(sorted(records, key=lambda item: str(item.transaction_id)))


class FileReviewRecordStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    def record(self, record: ReviewRecord) -> ReviewRecord:
        with self._lock:
            records = self._load()
            existing = next(
                (
                    item
                    for item in records
                    if item.transaction_id == record.transaction_id
                ),
                None,
            )
            if existing is not None:
                return existing
            records.append(record)
            self._save(records)
            return record

    def get(self, transaction_id: UUID) -> ReviewRecord | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._load()
                    if item.transaction_id == transaction_id
                ),
                None,
            )

    def list_for_user(
        self, user_id: UserId, resolution: ReviewResolution | None = None
    ) -> tuple[ReviewRecord, ...]:
        with self._lock:
            return InMemoryReviewRecordStore(tuple(self._load())).list_for_user(
                user_id, resolution
            )

    def _load(self) -> list[ReviewRecord]:
        if not self._path.exists():
            return []
        return RECORD_LIST.validate_json(self._path.read_text(encoding="utf-8"))

    def _save(self, records: list[ReviewRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [
                record.model_dump(mode="json", exclude_computed_fields=True)
                for record in records
            ],
            indent=2,
        )
        descriptor, name = tempfile.mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        temporary_path = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)
