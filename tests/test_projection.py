import numpy as np
import pytest

from vyuha.api.server import classify, parse_projection
from vyuha.projection import (
    ASSET_SOURCES,
    FIXED_RATE_ASSETS,
    TAX_RULES,
    block_bootstrap,
    project,
)

# ------------------------------------------------------------- bootstrap


def test_block_bootstrap_shape_and_membership():
    r = np.array([0.01, -0.02, 0.03, 0.00, -0.01] * 40)
    out = block_bootstrap(r, n_months=60, n_sims=100, block=12)
    assert out.shape == (100, 60)
    assert set(np.unique(out)).issubset(set(np.unique(r)))


def test_block_bootstrap_preserves_clustering():
    """Blocks must keep runs together. iid sampling destroys the clustering
    that makes a real drawdown deep rather than merely frequent, which flatters
    the result in exactly the direction that matters."""
    rng = np.random.default_rng(0)
    calm = rng.normal(0.01, 0.005, 300)
    crash = rng.normal(-0.06, 0.01, 60)
    series = np.concatenate([calm[:150], crash, calm[150:]])

    blocked = block_bootstrap(series, 120, 4000, block=12, rng=np.random.default_rng(1))
    iid = block_bootstrap(series, 120, 4000, block=1, rng=np.random.default_rng(1))

    def worst_dd(paths):
        c = np.cumprod(1 + paths, axis=1)
        return (c / np.maximum.accumulate(c, axis=1) - 1).min(axis=1)

    assert worst_dd(blocked).mean() < worst_dd(iid).mean(), (
        "block sampling must produce deeper drawdowns than iid"
    )


def test_short_series_falls_back_to_smaller_blocks():
    r = np.array([0.01, -0.01, 0.02, 0.0, 0.01, -0.02, 0.03, 0.01])
    out = block_bootstrap(r, n_months=12, n_sims=10, block=12)
    assert out.shape == (10, 12)


# --------------------------------------------------------------- projection


@pytest.fixture(scope="module")
def eq():
    return project(500_000, 7, "indian_equity", n_sims=4000)


def test_returns_a_distribution_not_a_number(eq):
    """The headline defence: never a single figure."""
    p = eq.percentiles
    assert p["p5"] < p["p25"] < p["p50"] < p["p75"] < p["p95"]
    assert p["p95"] > p["p5"] * 1.5, "the range must be visibly wide"


def test_value_erodes_monotonically_through_tax_and_inflation(eq):
    """Headline >= after tax >= after tax and inflation. Presenting post-tax
    and real separately invited reading them as alternatives."""
    assert eq.percentiles["p50"] >= eq.post_tax_percentiles["p50"]
    assert eq.post_tax_percentiles["p50"] >= eq.net_real_percentiles["p50"]


def test_downside_probabilities_are_reported(eq):
    for v in (eq.prob_loss, eq.prob_below_inflation, eq.prob_below_fd):
        assert 0.0 <= v <= 1.0
    assert eq.prob_below_inflation >= eq.prob_loss, (
        "beating inflation is a higher bar than merely not losing money"
    )


def test_equity_carries_real_loss_risk(eq):
    """A projection that shows equity as risk-free over 7 years is wrong."""
    assert eq.prob_loss > 0.02
    assert eq.max_drawdown_median < -0.05


def test_fixed_deposit_has_no_loss_risk():
    fd = project(500_000, 5, "fixed_deposit", n_sims=2000)
    assert fd.prob_loss == 0.0
    assert fd.percentiles["p50"] > 500_000


def test_longer_horizon_improves_the_odds():
    short = project(100_000, 2, "indian_equity", n_sims=4000)
    long = project(100_000, 20, "indian_equity", n_sims=4000)
    assert long.prob_loss < short.prob_loss


def test_sip_invests_more_than_it_starts_with():
    sip = project(10_000, 10, "indian_equity", mode="sip", n_sims=2000)
    assert sip.total_invested == pytest.approx(10_000 * 120)
    assert sip.percentiles["p50"] > 0


def test_sip_and_lumpsum_differ():
    a = project(120_000, 10, "indian_equity", mode="lumpsum", n_sims=2000)
    b = project(1_000, 10, "indian_equity", mode="sip", n_sims=2000)
    assert a.total_invested == pytest.approx(b.total_invested)
    assert a.percentiles["p50"] != b.percentiles["p50"]


def test_provenance_is_always_stated(eq):
    assert eq.sample_start and eq.sample_end
    assert eq.sample_years > 20
    assert eq.data_source
    assert any("resampling history" in c for c in eq.caveats)


def test_short_horizon_gets_an_explicit_warning():
    r = project(100_000, 1, "indian_equity", n_sims=1000)
    assert any("coin toss" in c for c in r.caveats)


def test_inflation_assumption_is_surfaced(eq):
    assert 0.0 < eq.inflation_assumed < 0.20
    assert any("Inflation assumed" in c for c in eq.caveats)


def test_tax_note_accompanies_any_tax_applied(eq):
    assert eq.tax_note
    assert any("verify current rules" in c for c in eq.caveats)


def test_rejects_nonsense_inputs():
    with pytest.raises(ValueError, match="amount must be positive"):
        project(-100, 5)
    with pytest.raises(ValueError, match="years must be"):
        project(1000, 0)
    with pytest.raises(ValueError, match="years must be"):
        project(1000, 99)


def test_unknown_asset_lists_alternatives():
    with pytest.raises(ValueError, match="bootstrappable assets"):
        project(1000, 5, "magic_beans")


def test_every_asset_has_tax_treatment():
    for a in set(ASSET_SOURCES) | set(FIXED_RATE_ASSETS):
        assert a in TAX_RULES, f"{a} has no tax rule"
        assert TAX_RULES[a]["note"]


# ------------------------------------------------------------------ parsing


@pytest.mark.parametrize("q,amount,years,asset,mode", [
    ("If I invest 5 lakh in equity for 5 years", 500_000, 5, "indian_equity", "lumpsum"),
    ("10000 monthly SIP in nifty for 15 years", 10_000, 15, "indian_equity", "sip"),
    ("2 crore in gold over 3 years", 20_000_000, 3, "gold", "lumpsum"),
    ("50000 in fixed deposit for 10 years", 50_000, 10, "fixed_deposit", "lumpsum"),
    ("₹1,00,000 in US stocks for 8 years", 100_000, 8, "us_equity", "lumpsum"),
])
def test_parses_plain_english(q, amount, years, asset, mode):
    got = parse_projection(q)
    assert got is not None, q
    assert got["amount"] == pytest.approx(amount)
    assert got["years"] == pytest.approx(years)
    assert got["asset"] == asset
    assert got["mode"] == mode


def test_months_are_converted_to_years():
    assert parse_projection("2 lakh in gold for 18 months")["years"] == pytest.approx(1.5)


def test_refuses_to_invent_a_missing_horizon():
    """An assumed horizon changes the answer more than almost anything else."""
    assert parse_projection("should I invest 5 lakh in equity") is None


def test_refuses_without_an_amount():
    assert parse_projection("invest in equity for 5 years") is None


def test_forecast_questions_are_not_hijacked():
    """'below 22,900 in the next 30 days' has a number and a horizon but is a
    question about an event, not a balance."""
    assert classify("Will the Nifty 50 fall below 22900 in the next 30 days?") == "council"
    assert classify("Will gold cross 5000 dollars in 2 years?") == "council"


def test_projection_questions_route_correctly():
    for q in ["If I invest 5 lakh in equity for 5 years what will I get?",
              "50000 in fixed deposit for 10 years",
              "10000 monthly SIP in nifty for 15 years"]:
        assert classify(q) == "projection", q
