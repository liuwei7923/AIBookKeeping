"""Reserved SQL adapter for the Memory Store seam."""

from collections.abc import Sequence

from bookkeeping_app.domain_contracts import CanonicalTransaction
from bookkeeping_app.memory.contracts import (
    MemoryListQuery,
    MemoryPage,
    MemoryQuery,
    MemoryWriteResult,
    RecordTrustedCommand,
)


class SqlMemoryStore:
    """Declared SQL adapter; persistence implementation is intentionally deferred."""

    def __init__(self, connection_url: str) -> None:
        self.connection_url = connection_url

    def record_trusted(
        self,
        commands: Sequence[RecordTrustedCommand],
    ) -> MemoryWriteResult:
        raise NotImplementedError("SqlMemoryStore is not implemented yet")

    def find_relevant(
        self,
        query: MemoryQuery,
    ) -> tuple[CanonicalTransaction, ...]:
        raise NotImplementedError("SqlMemoryStore is not implemented yet")

    def list_for_user(self, query: MemoryListQuery) -> MemoryPage:
        raise NotImplementedError("SqlMemoryStore is not implemented yet")
