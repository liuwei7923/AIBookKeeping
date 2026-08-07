"""Process-local transaction review session state."""

from threading import RLock
from uuid import UUID

from bookkeeping_app.review.contracts import TransactionItem, TransactionItemQuery


class EphemeralReviewSession:
    """Hold review items until the application process exits."""

    def __init__(self, items: tuple[TransactionItem, ...] = ()) -> None:
        self._items = {item.transaction_id: item for item in items}
        self._lock = RLock()

    def add(self, items: list[TransactionItem]) -> None:
        with self._lock:
            for item in items:
                self._items.setdefault(item.transaction_id, item)

    def list_for_user(self, query: TransactionItemQuery) -> tuple[TransactionItem, ...]:
        with self._lock:
            items = (
                item
                for item in self._items.values()
                if item.user_id == query.user_id
                and (query.resolution is None or item.resolution is query.resolution)
            )
            return tuple(sorted(items, key=lambda item: str(item.transaction_id)))

    def get(self, transaction_id: UUID) -> TransactionItem | None:
        with self._lock:
            return self._items.get(transaction_id)

    def replace(self, item: TransactionItem) -> None:
        with self._lock:
            if item.transaction_id not in self._items:
                raise KeyError(item.transaction_id)
            self._items[item.transaction_id] = item

    def list_all(self) -> tuple[TransactionItem, ...]:
        """Return all items for tests and local diagnostics."""
        with self._lock:
            return tuple(
                sorted(self._items.values(), key=lambda item: str(item.transaction_id))
            )
