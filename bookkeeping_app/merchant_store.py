"""User-scoped, file-backed store for explicitly confirmed merchant names."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from bookkeeping_app.normalization import normalize_merchant

_PATH_LOCKS_GUARD = RLock()
_PATH_LOCKS: dict[Path, RLock] = {}
try:
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None


def _lock_for(path: Path) -> RLock:
    key = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, RLock())


class MerchantConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    source_description: str
    confirmed_merchant: str
    action: Literal["confirmation", "correction"] = "confirmation"
    active: bool = True


class MerchantLookup(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["not_found", "matched", "ambiguous"]
    merchant: str | None = None
    evidence: tuple[MerchantConfirmation, ...] = ()


class FileMerchantStore:
    """Append-history JSON storage with per-process and advisory file locks.

    Cross-process write coordination is available where ``fcntl`` exists
    (macOS/Linux). On other platforms callers must ensure a single writer.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        # Shared between instances in this process. This does not coordinate
        # writers in separate processes; see module/class contract.
        self._lock = _lock_for(path)

    def confirm(self, user_id: UUID, source_description: str, merchant: str, *, correction: bool = False, allow_conflict: bool = True) -> MerchantConfirmation:
        description, confirmed = source_description.strip(), merchant.strip()
        key = normalize_merchant(description)
        if not key or not confirmed:
            raise ValueError("source description and confirmed merchant must not be blank")
        with self._lock, self._file_lock(exclusive=True):
            records = self._load()
            current = [r for r in records if r.user_id == user_id and normalize_merchant(r.source_description) == key and r.active]
            if not correction and any(r.confirmed_merchant.casefold() == confirmed.casefold() for r in current):
                return next(r for r in current if r.confirmed_merchant.casefold() == confirmed.casefold())
            if current and not correction and not allow_conflict:
                raise ValueError("conflicting mapping requires explicit correction")
            if correction:
                records = [
                    r.model_copy(update={"active": False})
                    if r.user_id == user_id
                    and r.active
                    and normalize_merchant(r.source_description) == key
                    else r
                    for r in records
                ]
            record = MerchantConfirmation(user_id=user_id, source_description=description, confirmed_merchant=confirmed, action="correction" if correction else "confirmation")
            records.append(record)
            self._save(records)
            return record

    def lookup(self, user_id: UUID, source_description: str | None) -> MerchantLookup:
        key = normalize_merchant(source_description)
        if not key:
            return MerchantLookup(status="not_found")
        with self._lock, self._file_lock(exclusive=False):
            found = tuple(r for r in self._load() if r.active and r.user_id == user_id and normalize_merchant(r.source_description) == key)
        names = {r.confirmed_merchant.casefold() for r in found}
        if not found:
            return MerchantLookup(status="not_found")
        if len(names) > 1:
            return MerchantLookup(status="ambiguous", evidence=found)
        return MerchantLookup(status="matched", merchant=found[0].confirmed_merchant, evidence=found)

    def history(self, user_id: UUID) -> tuple[MerchantConfirmation, ...]:
        with self._lock, self._file_lock(exclusive=False):
            return tuple(r for r in self._load() if r.user_id == user_id)

    @contextmanager
    def _file_lock(self, *, exclusive: bool):
        if fcntl is None:
            yield
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_name(self._path.name + ".lock")
        with lock_path.open("a", encoding="utf-8") as handle:
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(handle.fileno(), operation)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> list[MerchantConfirmation]:
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [MerchantConfirmation.model_validate(item) for item in json.loads(text)]

    def _save(self, records: list[MerchantConfirmation]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump([r.model_dump(mode="json") for r in records], stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self._path)
        finally:
            Path(name).unlink(missing_ok=True)
