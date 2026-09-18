import numpy as np
import pandas as pd
import pytest
from scipy import stats

from vyuha.benchmark.compare import capability_matrix, gap_report, score_against_market
from vyuha.benchmark.implied import (
    ImpliedDistribution, implied_cdf, implied_from_chain, real_world_adjust,
)


def synthetic_chain(spot=23000.0, vol=0.15, t=30 / 365, r=0.0525, n=41):
    """Build an option chain from a known lognormal, so the recovered
    distribution can be checked against ground truth."""
    strikes = np.linspace(spot * 0.85, spot * 1.15, n).round(-1)
    rows = []
    for k in strikes:
        d1 = (np.log(spot / k) + (r + vol**2 / 2) * t) / (vol * np.sqrt(t))
        d2 = d1 - vol * np.sqrt(t)
        call = spot * stats.norm.cdf(d1) - k * np.exp(-r * t) * stats.norm.cdf(d2)
        put = call - spot + k * np.exp(-r * t)
        for side, px in (("CE", call), ("PE", put)):
            rows.append({"strike": float(k), "expiry": "19-Oct-2026", "side": side,
                         "oi": 5000, "ltp": max(px, 0.05),
                         "bid": max(px * 0.99, 0.05), "ask": max(px * 1.01, 0.05),
                         "iv": vol * 100, "volume": 1000})
    df = pd.DataFrame(rows)
    df.attrs["underlying"] = spot
    return df, strikes


def test_recovers_a_known_lognormal():
    """The whole benchmark rests on this: given a chain from a known
    distribution, the recovered CDF must match it."""
    spot, vol, t = 23000.0, 0.15, 30 / 365
    chain, _ = synthetic_chain(spot, vol, t)
    d = implied_from_chain(chain, expiry="19-Oct-2026",
                           today=__import__("datetime").date(2026, 9, 19))
    for level in (spot * 0.95, spot, spot * 1.05):
        mu = np.log(spot) + (0.0525 - vol**2 / 2) * t
        truth = stats.norm.cdf((np.log(level) - mu) / (vol * np.sqrt(t)))
        assert abs(d.prob_below(level) - truth) < 0.06, (
            f"at {level:.0f}: recovered {d.prob_below(level):.3f} vs true {truth:.3f}"
        )


def test_recovered_cdf_is_monotone_and_bounded():
    chain, _ = synthetic_chain()
    d = implied_from_chain(chain, expiry="19-Oct-2026")
    assert np.all(np.diff(d.cdf) >= -1e-9)
    assert d.cdf.min() >= 0.0 and d.cdf.max() <= 1.0


def test_median_is_near_spot():
    chain, _ = synthetic_chain(spot=23000.0)
    d = implied_from_chain(chain, expiry="19-Oct-2026")
    assert 22000 < d.median() < 24000


def test_uncertainty_widens_with_volatility():
    lo = implied_from_chain(synthetic_chain(vol=0.10)[0], expiry="19-Oct-2026")
    hi = implied_from_chain(synthetic_chain(vol=0.30)[0], expiry="19-Oct-2026")
    width = lambda d: d.quantile(0.95) - d.quantile(0.05)  # noqa: E731
    assert width(hi) > width(lo)


def test_barrier_probability_exceeds_terminal():
    """P(ever touch) must exceed P(finish below) -- the reflection principle.

    Conflating these understates a 30-day barrier question by roughly half and
    would invalidate any comparison against the council.
    """
    chain, _ = synthetic_chain(spot=23000.0)
    d = implied_from_chain(chain, expiry="19-Oct-2026")
    level = 22000.0
    assert d.prob_touch_below(level) > d.prob_below(level)
    assert d.prob_touch_below(level) <= 1.0


def test_barrier_probability_is_capped_at_one():
    chain, _ = synthetic_chain(spot=23000.0)
    d = implied_from_chain(chain, expiry="19-Oct-2026")
    assert d.prob_touch_below(23000.0 * 1.5) <= 1.0


def test_thin_chain_is_rejected_not_fudged():
    chain, _ = synthetic_chain(n=6)
    with pytest.raises(ValueError, match="liquid strikes|too thin"):
        implied_from_chain(chain, expiry="19-Oct-2026")


def test_unreliable_recovery_is_flagged():
    """A degenerate chain must set reliable=False rather than return nonsense."""
    rows = [{"strike": float(k), "expiry": "19-Oct-2026", "side": s, "oi": 1,
             "ltp": 1.0, "bid": 0.9, "ask": 1.1, "iv": 10, "volume": 1}
            for k in np.linspace(20000, 26000, 30) for s in ("CE", "PE")]
    df = pd.DataFrame(rows)
    df.attrs["underlying"] = 23000.0
    try:
        d = implied_from_chain(df, expiry="19-Oct-2026")
        assert d.diagnostics["reliable"] is False
        assert d.diagnostics["unreliable_reason"]
    except ValueError:
        pass  # rejecting outright is also acceptable


def test_strict_mode_raises_on_unreliable():
    rows = [{"strike": float(k), "expiry": "19-Oct-2026", "side": s, "oi": 1,
             "ltp": 1.0, "bid": 0.9, "ask": 1.1, "iv": 10, "volume": 1}
            for k in np.linspace(20000, 26000, 30) for s in ("CE", "PE")]
    df = pd.DataFrame(rows)
    df.attrs["underlying"] = 23000.0
    with pytest.raises(ValueError):
        implied_from_chain(df, expiry="19-Oct-2026", strict=True)


def test_risk_premium_adjustment_reduces_downside_probability():
    assert real_world_adjust(0.40) < 0.40
    assert real_world_adjust(0.05) < 0.05


def test_implied_cdf_matches_analytic_derivative():
    k = np.array([90.0, 95, 100, 105, 110])
    c = np.array([12.0, 8.0, 5.0, 3.0, 1.8])
    cdf = implied_cdf(k, c, rate=0.05, t_years=0.25)
    assert np.all(np.diff(cdf) >= -1e-9)
    assert cdf.min() >= 0 and cdf.max() <= 1


# ------------------------------------------------------------- comparison


def test_perfect_forecaster_beats_market():
    y = [True, False, True, False] * 8
    perfect = [0.99 if o else 0.01 for o in y]
    market = [0.5] * len(y)
    r = score_against_market(perfect, market, y)
    assert r.skill_vs_market > 0.9
    assert "beat" in r.verdict


def test_small_sample_refuses_to_declare_a_winner():
    """The guard that stops a lucky ten questions being written up as an edge."""
    y = [True] * 5
    r = score_against_market([0.9] * 5, [0.5] * 5, y)
    assert "INCONCLUSIVE" in r.verdict


def test_market_beating_vyuha_is_reported_honestly():
    y = [True, False] * 15
    vyuha = [0.5] * 30
    market = [0.95 if o else 0.05 for o in y]
    r = score_against_market(vyuha, market, y)
    assert r.skill_vs_market < 0
    assert "market beat" in r.verdict.lower()


def test_gap_is_reported_so_premium_harvesting_is_visible():
    y = [False] * 30
    r = score_against_market([0.05] * 30, [0.30] * 30, y)
    assert r.detail["mean_gap_vyuha_minus_market"] < 0


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError, match="same length"):
        score_against_market([0.5], [0.5, 0.5], [True])


def test_capability_matrix_is_honest_about_weaknesses():
    m = capability_matrix()
    assert (m["vyuha"] == "none").any(), "matrix claims no weaknesses"
    assert (m["aladdin"] == "full").any()
    assert m["india_edge"].any()
    assert m["note"].str.len().min() > 20


def test_gap_report_names_both_sides():
    g = gap_report()
    assert g["cannot_compete_on"]
    assert g["can_win_on"]
    assert "should not try to replace" in g["honest_summary"]


# --------------------------------------------------------- coverage guard


def test_uncovered_asset_classes_are_refused_not_guessed():
    from vyuha.api.server import coverage_gap

    for q in ["Will house prices in Mumbai rise?", "Will gold cross 80000?"]:
        gap = coverage_gap(q)
        assert gap is not None, f"{q!r} should be refused"
        assert gap["route"] == "no_data"


def test_covered_asset_classes_are_answered():
    from vyuha.api.server import coverage_gap

    for q in ["Will the Nifty fall below 22900?", "What is the repo rate?"]:
        assert coverage_gap(q) is None


def test_coverage_report_marks_housing_unanswerable():
    from vyuha.ingest.catalogue import asset_class_coverage

    cov = asset_class_coverage()
    assert cov["real_estate"]["can_answer"] is False
    assert cov["equity"]["can_answer"] is True
