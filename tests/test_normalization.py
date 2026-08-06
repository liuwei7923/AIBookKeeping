from bookkeeping_app.normalization import normalize_merchant, normalize_statement


def test_normalize_merchant_removes_noise() -> None:
    assert normalize_merchant("  AMZN Mktp US*AB12C  ") == "amzn mktp us ab12c"


def test_normalize_statement_removes_noise() -> None:
    assert (
        normalize_statement("STARBUCKS  STORE #1234!!")
        == "starbucks store 1234"
    )
