"""JSON file-backed adapter for the Memory Store seam."""

import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from threading import RLock

from pydantic import TypeAdapter

from bookkeeping_app.domain_contracts import CanonicalTransaction
from bookkeeping_app.memory._operations import (
    find_relevant_transactions,
    list_transactions,
    record_commands,
)
from bookkeeping_app.memory.contracts import (
    MemoryListQuery,
    MemoryPage,
    MemoryQuery,
    MemoryWriteResult,
    RecordTrustedCommand,
)

TRANSACTION_LIST = TypeAdapter(list[CanonicalTransaction])


class FileMemoryStore:
    """Single-process JSON adapter with atomic file replacement on writes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    def record_trusted(
        self,
        commands: Sequence[RecordTrustedCommand],
    ) -> MemoryWriteResult:
        with self._lock:
            transactions = self._load()
            updated, result = record_commands(transactions, commands)
            self._save(updated)
            return result

    def find_relevant(
        self,
        query: MemoryQuery,
    ) -> tuple[CanonicalTransaction, ...]:
        with self._lock:
            return find_relevant_transactions(self._load(), query)

    def list_for_user(self, query: MemoryListQuery) -> MemoryPage:
        with self._lock:
            return list_transactions(self._load(), query)

    def _load(self) -> list[CanonicalTransaction]:
        if not self._path.exists():
            return []
        return TRANSACTION_LIST.validate_json(self._path.read_text(encoding="utf-8"))

    def _save(self, transactions: Sequence[CanonicalTransaction]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [transaction.model_dump(mode="json") for transaction in transactions],
            indent=2,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)
