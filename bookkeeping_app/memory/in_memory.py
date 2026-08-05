"""In-memory adapter for the Memory Store seam."""

from collections.abc import Sequence
from threading import RLock

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


class InMemoryMemoryStore:
    """Process-local adapter that implements production Memory Store semantics."""

    def __init__(
        self,
        transactions: Sequence[CanonicalTransaction] = (),
    ) -> None:
        self._transactions = list(transactions)
        self._lock = RLock()

    def record_trusted(
        self,
        commands: Sequence[RecordTrustedCommand],
    ) -> MemoryWriteResult:
        with self._lock:
            updated, result = record_commands(self._transactions, commands)
            self._transactions = updated
            return result

    def find_relevant(
        self,
        query: MemoryQuery,
    ) -> tuple[CanonicalTransaction, ...]:
        with self._lock:
            return find_relevant_transactions(self._transactions, query)

    def list_for_user(self, query: MemoryListQuery) -> MemoryPage:
        with self._lock:
            return list_transactions(self._transactions, query)
