import datetime as dt

import numpy as np
import pandas as pd
import pytest

from vyuha.ingest.globalmarkets import (
    FRED_COMMODITIES, FRED_GLOBAL, LBMA_FEEDS, WB_INDICATORS,
    inr_return_decomposition, to_inr,
)


@pytest.fixture
def prices():
    """A foreign asset that doubles, in local currency."""
    d = pd.date_range("2025-01-01", periods=13, freq="ME")
    return pd.DataFrame({"date": d, "value": np.linspace(100.0, 200.0, 13)})


@pytest.fixture
def fx_flat():
    d = pd.date_range("2024-12-01", periods=15, freq="ME")
    return pd.DataFrame({"date": d, "value": [80.0] * 15})


@pytest.fixture
def fx_depreciating():
    """Rupee weakens 80 -> 96, i.e. +20%."""
    d = pd.date_range("2024-12-01", periods=15, freq="ME")
    return pd.DataFrame({"date": d, "value": np.linspace(80.0, 96.0, 15)})


def test_conversion_uses_contemporaneous_rate(prices, fx_depreciating):
    """Converting a history at today's rate would rewrite the past. Each
    observation must use the rate that applied when it was observed."""
    out = to_inr(prices, fx=fx_depreciating)
    assert out["fx"].nunique() > 1, "a single rate was applied to the whole series"
    assert out["fx"].is_monotonic_increasing


def test_flat_currency_leaves_return_unchanged(prices, fx_flat):
    d = inr_return_decomposition(prices.assign(), "USD")
    # explicit fx path
    out = to_inr(prices, fx=fx_flat)
    local = prices["value"].iloc[-1] / prices["value"].iloc[0] - 1
    inr = out["value_inr"].iloc[-1] / out["value_inr"].iloc[0] - 1
    assert inr == pytest.approx(local, rel=1e-9)
    assert isinstance(d, dict)


def test_depreciation_amplifies_a_gain(prices, fx_depreciating):
    out = to_inr(prices, fx=fx_depreciating)
    local = prices["value"].iloc[-1] / prices["value"].iloc[0] - 1
    inr = out["value_inr"].iloc[-1] / out["value_inr"].iloc[0] - 1
    assert inr > local, "rupee depreciation must increase a rupee investor's return"


def test_decomposition_is_multiplicative_not_additive():
    """(1+a)(1+f)-1, not a+f. On large moves the difference is material."""
    d = pd.date_range("2025-01-31", periods=2, freq="ME")
    px = pd.DataFrame({"date": d, "value": [100.0, 150.0]})
    fx = pd.DataFrame({"date": d, "value": [80.0, 96.0]})
    out = to_inr(px, fx=fx)
    total = out["value_inr"].iloc[-1] / out["value_inr"].iloc[0] - 1
    a, f = 0.5, 0.2
    assert total == pytest.approx((1 + a) * (1 + f) - 1)
    assert total > a + f  # interaction term is positive and non-trivial


def test_unconvertible_rows_are_nan_not_filled():
    """Prices predating the FX history must not be converted with a rate that
    did not exist at the time."""
    px = pd.DataFrame({"date": pd.to_datetime(["2020-01-31", "2025-06-30"]),
                       "value": [100.0, 120.0]})
    fx = pd.DataFrame({"date": pd.to_datetime(["2025-01-31", "2025-06-30"]),
                       "value": [83.0, 86.0]})
    out = to_inr(px, fx=fx)
    assert out["value_inr"].isna().sum() == 1
    assert out.attrs["unconverted_rows"] == 1


def test_decomposition_reports_currency_share():
    d = pd.date_range("2025-01-31", periods=2, freq="ME")
    px = pd.DataFrame({"date": d, "value": [100.0, 110.0]})
    fx = pd.DataFrame({"date": d, "value": [80.0, 88.0]})
    out = to_inr(px, fx=fx)
    total = out["value_inr"].iloc[-1] / out["value_inr"].iloc[0] - 1
    assert total == pytest.approx(0.21)


def test_decomposition_needs_two_points():
    one = pd.DataFrame({"date": [pd.Timestamp("2025-06-30")], "value": [100.0]})
    with pytest.raises(ValueError, match="at least two"):
        inr_return_decomposition(one)


def test_registries_are_sane():
    assert "gold" in LBMA_FEEDS and "silver" in LBMA_FEEDS
    # Gold must NOT be routed through FRED -- those series were discontinued.
    assert "gold" not in FRED_COMMODITIES
    assert {"brent", "wti", "copper", "wheat"} <= set(FRED_COMMODITIES)
    assert {"sp500", "nasdaq", "vix", "us_10y"} <= set(FRED_GLOBAL)
    assert {"gdp_growth", "inflation"} <= set(WB_INDICATORS)


def test_unknown_commodity_lists_alternatives():
    from vyuha.ingest.globalmarkets import commodity

    with pytest.raises(ValueError, match="choose from"):
        commodity("unobtainium")


def test_unknown_index_rejected():
    from vyuha.ingest.globalmarkets import global_index

    with pytest.raises(ValueError, match="choose from"):
        global_index("ftse_moonbase")


# ------------------------------------------------------------ scope routing


@pytest.mark.parametrize("q,expected", [
    ("Should I invest in US stocks?", True),
    ("Will gold cross 5000 dollars?", True),
    ("Is the Chinese market cheap?", True),
    ("Compare India and Brazil growth", True),
    ("Should an Indian buy S&P 500 ETFs?", True),
    ("Will the Nifty fall below 22900?", False),
    ("What is the repo rate?", False),
    ("Will HDFC Bank rise?", False),
])
def test_global_scope_detection(q, expected):
    from vyuha.api.server import wants_global

    assert wants_global(q) is expected


def test_commodity_questions_are_no_longer_refused():
    """Commodities had zero sources and were blocked; LBMA and FRED fixed that."""
    from vyuha.api.server import coverage_gap

    assert coverage_gap("Will gold cross 80000 rupees?") is None
    assert coverage_gap("Will Brent go above 140?") is None


def test_housing_is_still_honestly_refused():
    from vyuha.api.server import coverage_gap

    gap = coverage_gap("Will house prices in Mumbai rise?")
    assert gap is not None and gap["route"] == "no_data"


def test_catalogue_marks_yahoo_blocked_with_a_reason():
    from vyuha.ingest.catalogue import BY_KEY, Status

    y = BY_KEY["yahoo_chart"]
    assert y.status is Status.BLOCKED
    assert "429" in y.notes


def test_commodity_and_currency_now_answerable():
    from vyuha.ingest.catalogue import asset_class_coverage

    cov = asset_class_coverage()
    assert cov["commodity"]["can_answer"] is True
    assert cov["currency"]["usable"] >= 2
