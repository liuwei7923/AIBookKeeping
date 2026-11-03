"""File-backed and in-memory storage for trusted merchant identifications."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from bookkeeping_app.domain_contracts import (
    TrustedMerchantIdentification,
    TrustedMerchantIdentificationSource,
)
from bookkeeping_app.normalization import normalize_merchant, sanitize_text


class TrustedMerchantLookupStatus(str):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


class TrustedMerchantWriteStatus(str):
    CREATED = "created"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class TrustedMerchantLookupResult:
    def __init__(
        self,
        *,
        user_id,
        normalized_description: str,
        identifications: Sequence[TrustedMerchantIdentification] = (),
    ) -> None:
        self.user_id = user_id
        self.normalized_description = normalized_description
        self.identifications = tuple(identifications)
        merchants = {item.merchant for item in self.identifications}
        if not self.identifications:
            self.status = TrustedMerchantLookupStatus.NOT_FOUND
            self.merchant = None
            self.ambiguous = False
        elif len(merchants) == 1:
            self.status = TrustedMerchantLookupStatus.FOUND
            self.merchant = next(iter(merchants))
            self.ambiguous = False
        else:
            self.status = TrustedMerchantLookupStatus.AMBIGUOUS
            self.merchant = None
            self.ambiguous = True

    @property
    def is_ambiguous(self) -> bool:
        return self.ambiguous

    @property
    def evidence(self) -> tuple[TrustedMerchantIdentification, ...]:
        return self.identifications

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.merchant == other
        if isinstance(other, TrustedMerchantLookupResult):
            return (
                self.user_id == other.user_id
                and self.normalized_description == other.normalized_description
                and self.identifications == other.identifications
            )
        if isinstance(other, (list, tuple)):
            return list(self.identifications) == list(other)
        return NotImplemented

    def __iter__(self):
        return iter(self.identifications)

    def __len__(self) -> int:
        return len(self.identifications)

    def __repr__(self) -> str:
        return (
            f"TrustedMerchantLookupResult(status={self.status!r}, "
            f"merchant={self.merchant!r}, count={len(self.identifications)})"
        )


class TrustedMerchantWriteResult:
    def __init__(
        self,
        *,
        status: str,
        identification: TrustedMerchantIdentification | None = None,
        conflicting: Sequence[TrustedMerchantIdentification] = (),
        reason: str | None = None,
    ) -> None:
        self.status = status
        self.identification = identification
        self.conflicting = tuple(conflicting)
        self.reason = reason

    def __repr__(self) -> str:
        return f"TrustedMerchantWriteResult(status={self.status!r})"


IDENTIFICATION_LIST = TypeAdapter(list[TrustedMerchantIdentification])


class _TrustedMerchantStoreCore:
    def __init__(self, identifications: Sequence[TrustedMerchantIdentification] = ()):
        self._identifications = list(identifications)
        self._lock = threading.RLock()

    def _normalize_description(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        if cleaned is None:
            return None
        normalized = normalize_merchant(cleaned)
        return normalized

    def _build_identification(
        self, *args: Any, **kwargs: Any
    ) -> TrustedMerchantIdentification:
        if args and isinstance(args[0], TrustedMerchantIdentification):
            return args[0]
        if "identification" in kwargs and isinstance(
            kwargs["identification"], TrustedMerchantIdentification
        ):
            return kwargs.pop("identification")

        user_id = kwargs.get("user_id", kwargs.get("user"))
        source_description = (
            kwargs.get("source_description")
            or kwargs.get("description")
            or kwargs.get("raw_description")
            or kwargs.get("statement")
        )
        if source_description is None and args:
            # positional: user_id, source_description, merchant
            if len(args) >= 1 and user_id is None:
                user_id = args[0]
            if len(args) >= 2 and source_description is None:
                source_description = args[1]
        merchant = kwargs.get("merchant") or kwargs.get("confirmed_merchant")
        if merchant is None and len(args) >= 3:
            merchant = args[2]
        if user_id is None or source_description is None or merchant is None:
            raise ValueError(
                "trusted merchant identification requires user_id, source_description, and merchant"
            )

        supplied_normalized = kwargs.get(
            "normalized_description", kwargs.get("normalized")
        )
        source_normalized = self._normalize_description(source_description)
        if source_normalized is None:
            raise ValueError("normalized_description must not be blank")
        if supplied_normalized is not None:
            normalized_override = self._normalize_description(supplied_normalized)
            if normalized_override is None:
                raise ValueError("normalized_description must not be blank")
            if normalized_override != source_normalized:
                raise ValueError(
                    "normalized_description must match the source description"
                )
            normalized_description = normalized_override
        else:
            normalized_description = source_normalized
        if normalized_description is None:
            raise ValueError("normalized_description must not be blank")

        corrected = bool(
            kwargs.get(
                "corrected",
                kwargs.get("is_correction", kwargs.get("correction", False)),
            )
        )
        source = (
            TrustedMerchantIdentificationSource.USER_CORRECTED
            if corrected
            else TrustedMerchantIdentificationSource.USER_CONFIRMED
        )
        if "source" in kwargs and kwargs["source"] is not None:
            source = kwargs["source"]

        normalized_merchant = kwargs.get("normalized_merchant")
        if normalized_merchant is None:
            normalized_merchant = normalize_merchant(merchant)

        return TrustedMerchantIdentification(
            user_id=user_id,
            source_description=source_description,
            normalized_description=normalized_description,
            merchant=merchant,
            normalized_merchant=normalized_merchant,
            source=source,
            transaction_id=kwargs.get("transaction_id"),
        )

    def record(self, *args: Any, **kwargs: Any) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def record_identification(
        self, *args: Any, **kwargs: Any
    ) -> TrustedMerchantWriteResult:
        with self._lock:
            identification = self._build_identification(*args, **kwargs)
            corrected = (
                bool(
                    kwargs.get(
                        "corrected",
                        kwargs.get("is_correction", kwargs.get("correction", False)),
                    )
                )
                or identification.source
                is TrustedMerchantIdentificationSource.USER_CORRECTED
            )
            existing = [
                item
                for item in self._identifications
                if item.user_id == identification.user_id
                and item.normalized_description == identification.normalized_description
                and item.active
            ]
            conflicting = existing
            if not corrected and any(
                item.merchant == identification.merchant for item in existing
            ):
                return TrustedMerchantWriteResult(
                    status=TrustedMerchantWriteStatus.DUPLICATE,
                    identification=identification,
                    conflicting=existing,
                    reason="duplicate trusted merchant identification",
                )
            if corrected:
                updated: list[TrustedMerchantIdentification] = []
                for item in self._identifications:
                    if (
                        item.user_id == identification.user_id
                        and item.normalized_description
                        == identification.normalized_description
                        and item.active
                    ):
                        updated.append(item.model_copy(update={"active": False}))
                    else:
                        updated.append(item)
                self._identifications = updated
                self._identifications.append(identification)
                return TrustedMerchantWriteResult(
                    status=TrustedMerchantWriteStatus.CORRECTED,
                    identification=identification,
                    conflicting=conflicting,
                    reason="corrected trusted merchant identification; prior history retained",
                )
            self._identifications.append(identification)
            if existing:
                return TrustedMerchantWriteResult(
                    status=TrustedMerchantWriteStatus.CONFLICT,
                    identification=identification,
                    conflicting=conflicting,
                    reason="conflicting trusted merchant identifications are preserved",
                )
            return TrustedMerchantWriteResult(
                status=TrustedMerchantWriteStatus.CREATED,
                identification=identification,
            )

    def record_confirmation(
        self, *args: Any, **kwargs: Any
    ) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def confirm(self, *args: Any, **kwargs: Any) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def add(self, *args: Any, **kwargs: Any) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def save(self, *args: Any, **kwargs: Any) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def record_trusted(self, *args: Any, **kwargs: Any) -> TrustedMerchantWriteResult:
        return self.record_identification(*args, **kwargs)

    def lookup(
        self,
        *args: Any,
        user_id: Any = None,
        normalized_description: str | None = None,
        **kwargs: Any,
    ) -> TrustedMerchantLookupResult:
        # Flexible argument handling.
        if user_id is None and args:
            user_id = args[0]
        if normalized_description is None and len(args) >= 2:
            normalized_description = args[1]
        if user_id is None:
            user_id = kwargs.get("user") or kwargs.get("owner_id")
        if normalized_description is None:
            normalized_description = (
                kwargs.get("normalized")
                or kwargs.get("description")
                or kwargs.get("source_description")
            )
        if normalized_description is not None:
            normalized = self._normalize_description(normalized_description)
            if normalized is not None:
                normalized_description = normalized
        if normalized_description is None:
            normalized_description = ""

        with self._lock:
            matches = [
                item
                for item in self._identifications
                if item.user_id == user_id
                and item.normalized_description == normalized_description
                and item.active
            ]
        return TrustedMerchantLookupResult(
            user_id=user_id,
            normalized_description=normalized_description,
            identifications=matches,
        )

    def find(
        self,
        *args: Any,
        user_id: Any = None,
        normalized_description: str | None = None,
        **kwargs: Any,
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.lookup(
            *args,
            user_id=user_id,
            normalized_description=normalized_description,
            **kwargs,
        ).identifications

    def find_exact(
        self, *args: Any, **kwargs: Any
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.find(*args, **kwargs)

    def find_by_normalized_description(
        self, *args: Any, **kwargs: Any
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.find(*args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> str | None:
        result = self.lookup(*args, **kwargs)
        return result.merchant

    def get_merchant(self, *args: Any, **kwargs: Any) -> str | None:
        return self.get(*args, **kwargs)

    def lookup_merchant(self, *args: Any, **kwargs: Any) -> str | None:
        return self.get(*args, **kwargs)

    def list_for_user(self, user_id: Any) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            return tuple(
                item for item in self._identifications if item.user_id == user_id
            )

    def all(self) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            return tuple(self._identifications)

    def history(self, user_id: Any) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            return tuple(
                item for item in self._identifications if item.user_id == user_id
            )


class InMemoryTrustedMerchantStore(_TrustedMerchantStoreCore):
    def __init__(self, identifications: Sequence[TrustedMerchantIdentification] = ()):
        super().__init__(identifications)


class FileTrustedMerchantStore:
    """File-backed trusted merchant store that reloads state for every operation.

    This avoids one long-lived instance silently overwriting records written by
    another instance. When ``fcntl`` is available, advisory file locking
    serializes cooperating processes; otherwise locking is in-process only and
    callers must use a single writer. Atomic replacement prevents torn file
    writes but does not by itself coordinate independent processes.
    """

    @property
    def cross_process_locking(self) -> bool:
        return self._fcntl is not None

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._lock = threading.RLock()
        try:
            import fcntl
        except ImportError:  # pragma: no cover - platform dependent
            self._fcntl = None
        else:
            self._fcntl = fcntl

    def _file_lock(self, exclusive: bool):
        @contextmanager
        def locked():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._path.with_name(self._path.name + ".lock")
            with lock_path.open("w", encoding="utf-8") as handle:
                if self._fcntl is not None:
                    self._fcntl.flock(
                        handle.fileno(),
                        self._fcntl.LOCK_EX if exclusive else self._fcntl.LOCK_SH,
                    )
                try:
                    yield
                finally:
                    if self._fcntl is not None:
                        self._fcntl.flock(handle.fileno(), self._fcntl.LOCK_UN)

        return locked()

    def _load(self) -> list[TrustedMerchantIdentification]:
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        try:
            return list(IDENTIFICATION_LIST.validate_json(text))
        except ValidationError as exc:
            raise ValueError("trusted merchant identification file is invalid") from exc

    def _save(self, records: Sequence[TrustedMerchantIdentification]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [item.model_dump(mode="json") for item in records],
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

    def _core(self) -> _TrustedMerchantStoreCore:
        return _TrustedMerchantStoreCore(self._load())

    def record_identification(
        self, *args: Any, **kwargs: Any
    ) -> TrustedMerchantWriteResult:
        with self._lock:
            with self._file_lock(exclusive=True):
                core = self._core()
                result = core.record_identification(*args, **kwargs)
                self._save(core._identifications)
                return result

    record = record_identification
    record_confirmation = record_identification
    confirm = record_identification
    add = record_identification
    save = record_identification
    record_trusted = record_identification

    def lookup(
        self,
        *args: Any,
        user_id: Any = None,
        normalized_description: str | None = None,
        **kwargs: Any,
    ) -> TrustedMerchantLookupResult:
        with self._lock:
            with self._file_lock(exclusive=False):
                core = self._core()
                return core.lookup(
                    *args,
                    user_id=user_id,
                    normalized_description=normalized_description,
                    **kwargs,
                )

    def find(
        self, *args: Any, **kwargs: Any
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.lookup(*args, **kwargs).identifications

    def find_exact(
        self, *args: Any, **kwargs: Any
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.find(*args, **kwargs)

    def find_by_normalized_description(
        self, *args: Any, **kwargs: Any
    ) -> tuple[TrustedMerchantIdentification, ...]:
        return self.find(*args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> str | None:
        return self.lookup(*args, **kwargs).merchant

    def get_merchant(self, *args: Any, **kwargs: Any) -> str | None:
        return self.get(*args, **kwargs)

    def lookup_merchant(self, *args: Any, **kwargs: Any) -> str | None:
        return self.get(*args, **kwargs)

    def list_for_user(self, user_id: Any) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            with self._file_lock(exclusive=False):
                core = self._core()
                return core.list_for_user(user_id)

    def history(self, user_id: Any) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            with self._file_lock(exclusive=False):
                core = self._core()
                return (
                    core.history(user_id)
                    if hasattr(core, "history")
                    else core.all()
                    and tuple(item for item in core.all() if item.user_id == user_id)
                )

    def all(self) -> tuple[TrustedMerchantIdentification, ...]:
        with self._lock:
            with self._file_lock(exclusive=False):
                core = self._core()
                return core.all()


# Backwards/alternative names.
TrustedMerchantStore = InMemoryTrustedMerchantStore
MerchantStore = InMemoryTrustedMerchantStore
MerchantIdentificationStore = InMemoryTrustedMerchantStore
TrustedMerchantIdentificationStore = InMemoryTrustedMerchantStore
FileMerchantStore = FileTrustedMerchantStore
FileMerchantIdentificationStore = FileTrustedMerchantStore
MerchantFileStore = FileTrustedMerchantStore
TrustedMerchantFileStore = FileTrustedMerchantStore
InMemoryMerchantStore = InMemoryTrustedMerchantStore
InMemoryMerchantIdentificationStore = InMemoryTrustedMerchantStore

__all__ = [
    "FileTrustedMerchantStore",
    "InMemoryTrustedMerchantStore",
    "TrustedMerchantIdentification",
    "TrustedMerchantLookupResult",
    "TrustedMerchantLookupStatus",
    "TrustedMerchantWriteResult",
    "TrustedMerchantWriteStatus",
]
