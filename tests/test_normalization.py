from bookkeeping_app.normalization import normalize_merchant


def test_normalize_merchant_removes_noise() -> None:
    assert normalize_merchant("  AMZN Mktp US*AB12C  ") == "amzn mktp us ab12c"


def test_normalize_merchant_returns_none_for_none_input() -> None:
    assert normalize_merchant(None) is None


def test_normalize_merchant_returns_none_for_blank_input() -> None:
    assert normalize_merchant("   ") is None


def test_normalize_merchant_returns_none_for_punctuation_only_input() -> None:
    assert normalize_merchant("***---###") is None
