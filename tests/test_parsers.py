from decimal import Decimal

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
            "amount": Decimal("1234.50"),
            "merchant": None,
            "category": "Shopping",
            "statement": "Amazon",
        }
    ]


def test_parse_csv_transactions_treats_statement_column_as_description() -> None:
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
            "statement": "WHOLEFDS SAN JOSE",
        }
    ]


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
            "statement": "TARGET T-2581 SAN JOSE CA",
        }
    ]


def test_parse_csv_transactions_preserves_merchant_column() -> None:
    csv_text = (
        "date,merchant,description,amount,category\n"
        "2026-03-02,Whole Foods,WHOLEFDS SAN JOSE,-42.19,Groceries\n"
    )

    transactions = parse_csv_transactions(csv_text)

    assert transactions[0]["merchant"] == "Whole Foods"
    assert transactions[0]["statement"] == "WHOLEFDS SAN JOSE"


def test_parse_csv_transactions_parses_chase_statement_shape() -> None:
    csv_text = (
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "03/01/2026,03/02/2026,WHOLEFDS MKT 10234 SAN JOSE CA,Groceries,Sale,-42.19,Weekly groceries\n"
    )

    transactions = parse_csv_transactions(csv_text)

    assert transactions[0]["date"] == "03/01/2026"
    assert transactions[0]["post_date"] == "03/02/2026"
    assert transactions[0]["statement"] == "WHOLEFDS MKT 10234 SAN JOSE CA"
    assert transactions[0]["merchant"] is None
    assert transactions[0]["amount"] == Decimal("-42.19")
    assert transactions[0]["category"] == "Groceries"
    assert transactions[0]["type"] == "Sale"
    assert transactions[0]["memo"] == "Weekly groceries"


def test_parse_transactions_normalizes_amount_and_fields() -> None:
    raw_text = '[{"date":"2026-03-01","amount":"-12.50","merchant":" Starbucks ","category":" Coffee "}]'

    transactions = parse_transactions(raw_text)

    assert transactions == [
        {
            "date": "2026-03-01",
            "amount": Decimal("-12.50"),
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


def test_posted_date_only_is_used_as_transaction_date() -> None:
    csv_text = "Post Date,Description,Amount\n03/03/2026,POS MARKET,-1.20\n"
    transactions = parse_csv_transactions(csv_text)
    assert transactions[0]["date"] == "03/03/2026"


def test_description_only_fingerprints_differ_by_description() -> None:
    from uuid import UUID

    from bookkeeping_app.ingestion import build_canonical_transactions

    user_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    rows = [
        {"date": "2026-03-02", "description": "POS MARKET A", "amount": -1.20},
        {"date": "2026-03-02", "description": "POS MARKET B", "amount": -1.20},
    ]
    result = build_canonical_transactions(rows, user_id=user_id)
    fingerprints = [item.fingerprint for item in result.canonical_transactions]
    assert len(set(fingerprints)) == 2


def test_category_review_input_includes_description_for_description_only_rows() -> None:
    result = build_category_review_input(
        [
            {
                "date": "2026-03-02",
                "amount": -1.2,
                "merchant": None,
                "description": "POS MARKET",
                "category": None,
            }
        ]
    )
    assert '"description": "POS MARKET"' in result
