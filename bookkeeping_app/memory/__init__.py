"""Trusted categorization-memory interface and adapters."""

from bookkeeping_app.memory.contracts import (
    FingerprintConflictPolicy,
    MemoryListQuery,
    MemoryPage,
    MemoryQuery,
    MemoryStore,
    MemoryWriteItemResult,
    MemoryWriteResult,
    MemoryWriteStatus,
    RecordTrustedCommand,
)
from bookkeeping_app.memory.file_store import FileMemoryStore
from bookkeeping_app.memory.in_memory import InMemoryMemoryStore
from bookkeeping_app.memory.sql_store import SqlMemoryStore

__all__ = [
    "FileMemoryStore",
    "FingerprintConflictPolicy",
    "InMemoryMemoryStore",
    "MemoryListQuery",
    "MemoryPage",
    "MemoryQuery",
    "MemoryStore",
    "MemoryWriteItemResult",
    "MemoryWriteResult",
    "MemoryWriteStatus",
    "RecordTrustedCommand",
    "SqlMemoryStore",
]
