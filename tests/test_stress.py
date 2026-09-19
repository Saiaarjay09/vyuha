import pandas as pd
import pytest

from vyuha.risk.liquidity import concentration, days_to_liquidate, liquidity_adjusted_var
from vyuha.risk.stress import BY_KEY, SCENARIOS, apply_scenario, run_all, unmodelled_exposures


@pytest.fixture
def book():
    return pd.DataFrame(
        {
            "value": [10e6, 5e6, 3e6, 2e6],
            "beta": [0.9, 1.3, 1.1, 0.7],
            "cap_segment": ["large", "mid", "small", "large"],
            "duration": [0.0, 0.0, 0.0, 4.5],
            "fx_exposure": [0.0, 0.0, 1e6, 0.0],
        },
        index=["RELIANCE", "MIDCO", "SMALLCO", "GSEC2030"],
    )


def test_every_scenario_has_a_lesson_and_a_period():
    for s in SCENARIOS:
        assert s.lesson and len(s.lesson) > 30
        assert s.period
        assert s.description


def test_crisis_scenarios_lose_money(book):
    for key in ("gfc_2008", "covid_crash_2020", "ilfs_2018"):
        assert apply_scenario(book, BY_KEY[key])["total_pnl"].sum() < 0


def test_midcaps_are_hit_harder_in_a_credit_event(book):
    """IL&FS is the case study: mid/small fell roughly 3x large."""
    out = apply_scenario(book, BY_KEY["ilfs_2018"])
    assert out.loc["SMALLCO", "pnl_pct"] < out.loc["RELIANCE", "pnl_pct"]


def test_duration_drives_the_bond_leg(book):
    """Taper tantrum: +300bp. The bond must lose, the equities must not via rates."""
    out = apply_scenario(book, BY_KEY["taper_tantrum_2013"])
    assert out.loc["GSEC2030", "rates_pnl"] < 0
    assert out.loc["RELIANCE", "rates_pnl"] == 0.0


def test_run_all_sorts_worst_first(book):
    res = run_all(book)
    assert len(res) == len(SCENARIOS)
    assert res["pnl"].is_monotonic_increasing


def test_unmodelled_exposures_are_named_not_silently_zeroed(book):
    missing = unmodelled_exposures(book)
    assert "credit spread" in missing
    assert "oil" in missing
    assert "equity market" not in missing


def test_days_to_liquidate_flags_illiquid_positions():
    pos = pd.Series({"LIQUID": 1e6, "ILLIQUID": 5e7})
    adv = pd.Series({"LIQUID": 5e8, "ILLIQUID": 1e6})
    out = days_to_liquidate(pos, adv, participation=0.2)
    assert out.loc["LIQUID", "days_to_liquidate"] < 1
    assert out.loc["ILLIQUID", "days_to_liquidate"] > 30


def test_position_with_no_volume_data_is_treated_as_untradeable():
    out = days_to_liquidate(pd.Series({"X": 1e6}), pd.Series({"X": 0.0}))
    assert bool(out.loc["X", "untradeable"]) is True


def test_liquidity_adjustment_only_ever_increases_var():
    base = 0.03
    adj = liquidity_adjusted_var(base, days=9.0, daily_vol=0.015)
    assert adj["liquidity_adjusted_var"] > base
    assert adj["liquidity_premium"] > 0
    assert adj["horizon_adjusted_var"] == pytest.approx(base * 3.0)


def test_concentration_detects_a_single_name_book():
    conc = concentration(pd.Series({"A": 100.0, "B": 1.0, "C": 1.0}))
    assert conc["top1_pct"] > 0.9
    assert conc["effective_n"] < 1.5


def test_equal_weight_book_has_effective_n_equal_to_count():
    conc = concentration(pd.Series({c: 10.0 for c in "ABCDE"}))
    assert conc["effective_n"] == pytest.approx(5.0)
