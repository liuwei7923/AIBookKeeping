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
            "merchant": "Amazon",
            "category": "Shopping",
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
            "amount": -42.19,
            "merchant": "WHOLEFDS SAN JOSE",
            "category": "Groceries",
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
            "amount": -27.51,
            "merchant": "TARGET T-2581 SAN JOSE CA",
            "category": None,
        }
    ]


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
