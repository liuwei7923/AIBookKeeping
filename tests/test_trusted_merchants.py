from pathlib import Path
from uuid import UUID

import pytest

from bookkeeping_app.domain_contracts import TrustedMerchantIdentification
from bookkeeping_app.trusted_merchants import (
    FileTrustedMerchantStore,
    InMemoryTrustedMerchantStore,
    TrustedMerchantWriteStatus,
)

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")
USER_B = UUID("550e8400-e29b-41d4-a716-446655440001")


def test_record_and_lookup_exact_normalized_description() -> None:
    store = InMemoryTrustedMerchantStore()
    store.confirm(
        user_id=USER_A,
        source_description="WHOLEFDS MKT 10234",
        merchant="Whole Foods",
    )

    result = store.lookup(user_id=USER_A, normalized_description="wholefds mkt 10234")

    assert result.status == "found"
    assert result.merchant == "Whole Foods"
    assert len(result) == 1


def test_lookup_is_user_scoped() -> None:
    store = InMemoryTrustedMerchantStore()
    store.confirm(
        user_id=USER_A, source_description="COFFEE SHOP", merchant="Coffee Shop"
    )
    store.confirm(
        user_id=USER_B, source_description="COFFEE SHOP", merchant="Other Cafe"
    )

    assert (
        store.lookup(user_id=USER_A, normalized_description="coffee shop").merchant
        == "Coffee Shop"
    )
    assert (
        store.lookup(user_id=USER_B, normalized_description="coffee shop").merchant
        == "Other Cafe"
    )


def test_duplicate_confirmation_is_idempotent() -> None:
    store = InMemoryTrustedMerchantStore()
    first = store.confirm(
        user_id=USER_A, source_description="TARGET", merchant="Target"
    )
    second = store.confirm(
        user_id=USER_A, source_description="TARGET", merchant="Target"
    )

    assert first.status == TrustedMerchantWriteStatus.CREATED
    assert second.status == TrustedMerchantWriteStatus.DUPLICATE
    assert len(store.lookup(user_id=USER_A, normalized_description="target")) == 1


def test_conflicting_confirmation_is_preserved_and_ambiguous() -> None:
    store = InMemoryTrustedMerchantStore()
    store.confirm(user_id=USER_A, source_description="ACME", merchant="Acme Market")
    result = store.confirm(
        user_id=USER_A, source_description="ACME", merchant="Acme Corp"
    )

    assert result.status == TrustedMerchantWriteStatus.CONFLICT
    lookup = store.lookup(user_id=USER_A, normalized_description="acme")
    assert lookup.ambiguous is True
    assert lookup.merchant is None
    assert len(lookup) == 2


def test_correction_resolves_mapping_and_preserves_history() -> None:
    store = InMemoryTrustedMerchantStore()
    store.confirm(user_id=USER_A, source_description="ACME", merchant="Acme Market")
    result = store.confirm(
        user_id=USER_A,
        source_description="ACME",
        merchant="Acme Corp",
        corrected=True,
    )

    lookup = store.lookup(user_id=USER_A, normalized_description="acme")
    assert result.status == TrustedMerchantWriteStatus.CORRECTED
    assert lookup.status == "found"
    assert lookup.merchant == "Acme Corp"
    history = store.history(user_id=USER_A)
    assert len(history) == 2
    assert any(not item.active for item in history)
    assert any(item.active and item.merchant == "Acme Corp" for item in history)


def test_file_store_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "trusted_merchants.json"
    store = FileTrustedMerchantStore(path)
    store.confirm(user_id=USER_A, source_description="TARGET", merchant="Target")

    restored = FileTrustedMerchantStore(path)
    assert (
        restored.lookup(user_id=USER_A, normalized_description="target").merchant
        == "Target"
    )


def test_file_store_missing_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    store = FileTrustedMerchantStore(path)
    assert (
        store.lookup(user_id=USER_A, normalized_description="target").identifications
        == ()
    )


def test_shared_store_isolation_on_writes(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    store_a = FileTrustedMerchantStore(path)
    store_a.confirm(user_id=USER_A, source_description="TARGET", merchant="Target A")

    store_b = FileTrustedMerchantStore(path)
    # New instance sees persisted data.
    assert (
        store_b.lookup(user_id=USER_A, normalized_description="target").merchant
        == "Target A"
    )
    # Other user absent.
    assert (
        store_b.lookup(user_id=USER_B, normalized_description="target").identifications
        == ()
    )


def test_record_model_object() -> None:
    store = InMemoryTrustedMerchantStore()
    identification = TrustedMerchantIdentification(
        user_id=USER_A,
        source_description="TARGET",
        normalized_description="target",
        merchant="Target",
    )
    result = store.record(identification)
    assert result.status == TrustedMerchantWriteStatus.CREATED
    assert store.get(user_id=USER_A, normalized_description="target") == "Target"


def test_empty_normalized_description_rejected() -> None:
    store = InMemoryTrustedMerchantStore()
    with pytest.raises(ValueError):
        store.confirm(user_id=USER_A, source_description="   ", merchant="Target")


def test_stale_file_instances_do_not_overwrite_each_other(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    first = FileTrustedMerchantStore(path)
    second = FileTrustedMerchantStore(path)

    first.confirm(user_id=USER_A, source_description="TARGET", merchant="Target A")
    second.confirm(user_id=USER_B, source_description="TARGET", merchant="Target B")

    restored = FileTrustedMerchantStore(path)
    assert (
        restored.lookup(user_id=USER_A, normalized_description="target").merchant
        == "Target A"
    )
    assert (
        restored.lookup(user_id=USER_B, normalized_description="target").merchant
        == "Target B"
    )


def test_empty_trusted_merchant_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    store = FileTrustedMerchantStore(path)
    assert (
        store.lookup(user_id=USER_A, normalized_description="target").identifications
        == ()
    )


def test_correction_to_already_active_mapping_appends_correction() -> None:
    store = InMemoryTrustedMerchantStore()
    store.confirm(user_id=USER_A, source_description="ACME", merchant="Acme Market")
    result = store.confirm(
        user_id=USER_A,
        source_description="ACME",
        merchant="Acme Market",
        corrected=True,
    )

    assert result.status is TrustedMerchantWriteStatus.CORRECTED
    assert (
        store.lookup(user_id=USER_A, normalized_description="acme").merchant
        == "Acme Market"
    )
    assert len(store.history(user_id=USER_A)) == 2


def test_caller_normalized_override_must_match_source() -> None:
    store = InMemoryTrustedMerchantStore()
    with pytest.raises(ValueError, match="must match"):
        store.confirm(
            user_id=USER_A,
            source_description="ACME MARKET",
            merchant="Acme",
            normalized_description="something else",
        )
