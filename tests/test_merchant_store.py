from uuid import UUID

from bookkeeping_app.merchant_store import FileMerchantStore

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")
USER_B = UUID("550e8400-e29b-41d4-a716-446655440001")


def test_confirmation_exact_normalized_lookup_and_shared_store_isolation(tmp_path):
    path = tmp_path / "merchants.json"
    store = FileMerchantStore(path)
    store.confirm(USER_A, "CHASE COFFEE #42", "Northstar Cafe")
    assert FileMerchantStore(path).lookup(USER_A, " chase   coffee #42 ").merchant == "Northstar Cafe"
    assert store.lookup(USER_B, "CHASE COFFEE #42").status == "not_found"


def test_conflicts_are_ambiguous_until_explicit_correction_preserving_history(tmp_path):
    store = FileMerchantStore(tmp_path / "merchants.json")
    store.confirm(USER_A, "CHASE POS 123", "Cafe One")
    store.confirm(USER_A, "CHASE POS 123", "Cafe Two")
    assert store.lookup(USER_A, "CHASE POS 123").status == "ambiguous"
    store.confirm(USER_A, "CHASE POS 123", "Cafe Two", correction=True)
    assert store.lookup(USER_A, "CHASE POS 123").merchant == "Cafe Two"
    history = store.history(USER_A)
    assert len(history) == 3
    assert all(not item.active for item in history[:-1])
    assert history[-1].action == "correction" and history[-1].active


def test_correction_to_existing_active_value_resolves_conflict(tmp_path):
    store = FileMerchantStore(tmp_path / "merchants.json")
    store.confirm(USER_A, "CHASE POS 123", "Cafe One")
    store.confirm(USER_A, "CHASE POS 123", "Cafe Two")
    assert store.lookup(USER_A, "CHASE POS 123").status == "ambiguous"
    store.confirm(USER_A, "CHASE POS 123", "Cafe One", correction=True)
    result = store.lookup(USER_A, "CHASE POS 123")
    assert result.status == "matched" and result.merchant == "Cafe One"
    history = store.history(USER_A)
    assert sum(record.active for record in history) == 1
    assert history[-1].action == "correction"


def test_empty_lookup_duplicates_and_separate_conflict_evidence(tmp_path):
    store = FileMerchantStore(tmp_path / "merchants.json")
    assert store.lookup(USER_A, None).status == "not_found"
    store.confirm(USER_A, "CHASE MARKET", "Market")
    store.confirm(USER_A, "chase market", "Market")
    store.confirm(USER_A, "CHASE MARKET", "Other Market", correction=True)
    assert store.lookup(USER_A, "CHASE MARKET").status == "matched"
    assert len(store.history(USER_A)) == 2


def test_empty_existing_file_is_treated_as_empty_store(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("  \n", encoding="utf-8")
    store = FileMerchantStore(path)
    assert store.lookup(USER_A, "anything").status == "not_found"
    store.confirm(USER_A, "anything", "Known")
    assert FileMerchantStore(path).lookup(USER_A, "anything").merchant == "Known"


def test_instances_sharing_path_reload_before_each_write_and_preserve_users(tmp_path):
    path = tmp_path / "shared.json"
    writer_a, writer_b = FileMerchantStore(path), FileMerchantStore(path)
    writer_a.confirm(USER_A, "A DESCRIPTION", "Merchant A")
    writer_b.confirm(USER_B, "B DESCRIPTION", "Merchant B")
    reader = FileMerchantStore(path)
    assert reader.lookup(USER_A, "A DESCRIPTION").merchant == "Merchant A"
    assert reader.lookup(USER_B, "B DESCRIPTION").merchant == "Merchant B"


def test_legacy_records_with_conflicting_active_mapping_are_ambiguous(tmp_path):
    path = tmp_path / "merchants.json"
    store = FileMerchantStore(path)
    store.confirm(USER_A, "CHASE XYZ", "Store A")
    store.confirm(USER_B, "CHASE XYZ", "Store B")
    # The other user's record cannot turn this user's result into ambiguity.
    assert store.lookup(USER_A, "CHASE XYZ").merchant == "Store A"
