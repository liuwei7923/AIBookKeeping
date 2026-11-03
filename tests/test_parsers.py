from decimal import Decimal
from pathlib import Path

from bookkeeping_app.normalization import sanitize_text
from bookkeeping_app.openai_service import build_category_review_input
from bookkeeping_app.parsers import parse_csv_transactions, parse_transactions


def test_sanitize_text_removes_control_characters() -> None:
    assert sanitize_text("\x1b[118;1:3u2026-03-02") == "[118;1:3u2026-03-02"


def test_parse_csv_transactions_normalizes_common_columns() -> None:
    csv_text = (
        "Transaction Date,Amount,Description,Category\n"
        '2026-03-02,"$1,234.50",Amazon,Shopping\n'
    )

    transactions = parse_csv_transactions(csv_text)

    assert transactions == [
        {
            "date": "2026-03-02",
            "amount": 1234.5,
            "merchant": None,
            "category": "Shopping",
            "description": "Amazon",
        }
    ]


def test_parse_csv_transactions_treats_statement_column_as_merchant() -> None:
    csv_text = (
        "date,statement,amount,category\n"
        "2026-03-02,WHOLEFDS SAN JOSE,-42.19,Groceries\n"
    )

    transactions = parse_csv_transactions(csv_text)

    assert transactions == [
        {
            "date": "2026-03-02",
            "amount": Decimal("-42.19"),
            "merchant": None,
            "category": "Groceries",
            "description": "WHOLEFDS SAN JOSE",
        }
    ]


def test_parse_preserves_statement_when_merchant_is_present() -> None:
    row = parse_csv_transactions(
        "date,merchant,original statement,amount,category\n"
        "2026-03-02,Whole Foods,WHOLEFDS SAN JOSE,-42.19,Groceries\n"
    )[0]

    assert row["merchant"] == "Whole Foods"
    assert row["description"] == "WHOLEFDS SAN JOSE"


def test_parse_csv_transactions_supports_credit_card_export_headers() -> None:
    csv_text = (
        "Date of Transaction,Merchant Name or Transaction Description,$ Amount\n"
        "06/15,TARGET T-2581 SAN JOSE CA,-27.51\n"
    )

    transactions = parse_csv_transactions(csv_text)

    assert transactions == [
        {
            "date": "06/15",
            "amount": Decimal("-27.51"),
            "merchant": None,
            "category": None,
            "description": "TARGET T-2581 SAN JOSE CA",
        }
    ]


def test_synthetic_chase_csv_preserves_optional_source_fields_and_decimal_amount() -> (
    None
):
    csv_text = (
        Path(__file__).parent / "sample_csvs" / "synthetic_chase.csv"
    ).read_text()
    transaction = parse_csv_transactions(csv_text)[0]

    assert transaction == {
        "date": "03/02/2026",
        "amount": Decimal("-12.34"),
        "merchant": None,
        "category": "Food & Drink",
        "description": "POS PURCHASE COFFEE SHOP #123",
        "post_date": "03/03/2026",
        "type": "Sale",
        "memo": "synthetic fixture only",
    }


def test_decimal_amount_is_serialized_without_float_rounding_for_model_input() -> None:
    result = build_category_review_input(
        [
            {
                "date": "2026-03-02",
                "amount": Decimal("0.1000000000000000001"),
                "merchant": "Cafe",
                "category": None,
            }
        ]
    )
    assert '"amount": "0.1000000000000000001"' in result


def test_category_review_input_keeps_description_separate_from_merchant() -> None:
    result = build_category_review_input(
        [
            {
                "merchant": None,
                "description": "POS MARKET #12",
                "amount": Decimal("-1.20"),
            }
        ]
    )
    assert '"merchant": null' in result
    assert '"source_description": "POS MARKET #12"' in result


def test_parse_transactions_normalizes_amount_and_fields() -> None:
    raw_text = '[{"date":"2026-03-01","amount":"-12.50","merchant":" Starbucks ","category":" Coffee "}]'

    transactions = parse_transactions(raw_text)

    assert transactions == [
        {
            "date": "2026-03-01",
            "amount": -12.5,
            "merchant": "Starbucks",
            "category": "Coffee",
        }
    ]


def test_build_category_review_input_limits_history_examples() -> None:
    transactions = [
        {"date": "2026-03-01", "amount": -5.0, "merchant": "Coffee", "category": "Food"}
    ]
    history = [
        {"merchant": f"Merchant {index}", "category": "Sample"} for index in range(30)
    ]

    payload = build_category_review_input(transactions, history)

    assert '"transactions"' in payload
    assert payload.count('"merchant": "Merchant') == 20
