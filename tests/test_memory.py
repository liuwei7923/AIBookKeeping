from pathlib import Path
from uuid import UUID

from bookkeeping_app.memory import (
    build_memory_item,
    import_categorization_memory_csv,
    infer_direction,
    load_categorization_memory,
    normalize_merchant,
    parse_memory_csv,
    save_categorization_memory,
)

WEI_USER_ID = UUID("8a802680-06be-4815-986b-58b88392acfc")
JIA_USER_ID = UUID("0c050ed3-d41b-468c-9c29-e9e6da905c04")


def test_normalize_merchant_removes_noise() -> None:
    assert normalize_merchant("  AMZN Mktp US*AB12C  ") == "amzn mktp us ab12c"


def test_infer_direction_uses_amount_sign() -> None:
    assert infer_direction(-10.0) == "debit"
    assert infer_direction(25.0) == "credit"
    assert infer_direction(None) is None


def test_build_memory_item_supports_optional_original_category() -> None:
    item = build_memory_item(
        user_id=WEI_USER_ID,
        merchant="Electrify America",
        amount="-7.00",
        corrected_category="Electric Vehicle Charging",
        statement="ELECTRIFY AMERICA 65RESTON VA",
        notes="EV charging merchant",
    )

    assert item.original_category is None
    assert item.corrected_category == "Electric Vehicle Charging"
    assert item.statement == "ELECTRIFY AMERICA 65RESTON VA"
    assert item.normalized_merchant == "electrify america"
    assert item.direction == "debit"


def test_load_and_save_categorization_memory_round_trip(tmp_path: Path) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    item = build_memory_item(
        user_id=WEI_USER_ID,
        merchant="Whole Foods",
        amount=-42.19,
        corrected_category="Groceries",
        original_category=None,
    )

    save_categorization_memory([item], memory_path)
    loaded = load_categorization_memory(WEI_USER_ID, memory_path)

    assert len(loaded) == 1
    assert loaded[0].merchant == "Whole Foods"
    assert loaded[0].corrected_category == "Groceries"
    assert loaded[0].original_category is None


def test_parse_memory_csv_supports_final_category_only() -> None:
    csv_text = (
        "merchant,amount,category,original statement\n"
        "Electrify America,-7.0,Electric Vehicle Charging,ELECTRIFY AMERICA 65RESTON VA\n"
    )

    items = parse_memory_csv(csv_text, WEI_USER_ID)

    assert len(items) == 1
    assert items[0].merchant == "Electrify America"
    assert items[0].statement == "ELECTRIFY AMERICA 65RESTON VA"
    assert items[0].corrected_category == "Electric Vehicle Charging"
    assert items[0].original_category is None


def test_import_categorization_memory_csv_appends_to_store(tmp_path: Path) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    csv_text = "merchant,amount,category\nWhole Foods,-42.19,Groceries\n"

    result = import_categorization_memory_csv(csv_text, WEI_USER_ID, memory_path)
    loaded = load_categorization_memory(WEI_USER_ID, memory_path)

    assert result == {"imported": 1, "skipped": 0}
    assert len(loaded) == 1
    assert loaded[0].merchant == "Whole Foods"


def test_parse_memory_csv_accepts_corrected_category_column() -> None:
    csv_text = (
        "merchant,amount,corrected_category,statement\n"
        "Whole Foods,-42.19,Groceries,WHOLEFDS SAN JOSE\n"
    )

    items = parse_memory_csv(csv_text, WEI_USER_ID)

    assert len(items) == 1
    assert items[0].corrected_category == "Groceries"
    assert items[0].statement == "WHOLEFDS SAN JOSE"


def test_memory_store_filters_users_and_preserves_shared_file(tmp_path: Path) -> None:
    memory_path = tmp_path / "categorization_memory.json"

    import_categorization_memory_csv(
        "merchant,category\nWei Market,Groceries\n",
        WEI_USER_ID,
        memory_path,
    )
    import_categorization_memory_csv(
        "merchant,category\nJia Cafe,Coffee\n",
        JIA_USER_ID,
        memory_path,
    )

    wei_items = load_categorization_memory(WEI_USER_ID, memory_path)
    jia_items = load_categorization_memory(JIA_USER_ID, memory_path)

    assert [item.merchant for item in wei_items] == ["Wei Market"]
    assert [item.merchant for item in jia_items] == ["Jia Cafe"]
