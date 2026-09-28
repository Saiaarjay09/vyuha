"""Tests for the features an ordinary person actually uses.

These exist because 1,121 lines of working risk code -- covariance, VaR,
factor model, liquidity -- were unreachable from the interface, and 14,400
mutual fund NAVs were fetched daily and used by nothing. Capability nobody can
reach is not capability.
"""

from __future__ import annotations

import pytest

from vyuha.api.server import classify, parse_goal
from vyuha.portfolio import BUCKETS, analyse_text, parse_holdings
from vyuha.portfolio import classify as classify_holding
from vyuha.projection import plan_goal

# ---------------------------------------------------------- parsing


@pytest.mark.parametrize("text,n,total", [
    ("I have 8 lakh in HDFC Bank, 5 lakh in Reliance and 3 lakh in gold", 3, 1_600_000),
    ("5 lakh in FD and 2 lakh in a midcap fund", 2, 700_000),
    ("I hold 50000 in gold", 1, 50_000),
])
def test_parses_plain_english_holdings(text, n, total):
    h = parse_holdings(text)
    assert len(h) == n
    assert sum(x.value for x in h) == pytest.approx(total)


@pytest.mark.parametrize("name,bucket", [
    ("HDFC Bank", "large_cap"), ("Reliance", "large_cap"),
    ("gold", "gold"), ("sovereign gold bond", "gold"),
    ("FD", "debt"), ("PPF", "debt"), ("liquid fund", "debt"),
    ("midcap fund", "mid_small_cap"), ("small cap fund", "mid_small_cap"),
    ("nifty bees", "index_fund"), ("US stocks", "international"),
    ("cash", "cash"),
])
def test_classifies_holdings(name, bucket):
    assert classify_holding(name)[0] == bucket


def test_unknown_holdings_are_flagged_not_silently_assumed():
    """A wrong guess must be visible. Silently treating an unknown as large-cap
    would understate risk without telling anyone."""
    bucket, guessed = classify_holding("Zyxco Industries")
    assert bucket == "large_cap" and guessed is True
    a = analyse_text("4 lakh in Zyxco Industries")
    assert a.unrecognised == ["Zyxco Industries"]
    assert any("Could not identify" in c for c in a.caveats)


# -------------------------------------------------------- analysis


@pytest.fixture
def book():
    return analyse_text(
        "8 lakh in HDFC Bank, 5 lakh in Reliance, 4 lakh in a midcap fund, "
        "3 lakh in gold and 2 lakh in FD")


def test_connects_the_risk_engine_to_real_holdings(book):
    assert book.total == pytest.approx(2_200_000)
    assert book.stress and book.liquidity
    assert book.concentration["effective_n"] > 1


def test_stress_losses_are_ordered_worst_first(book):
    losses = [s["loss"] for s in book.stress]
    assert losses == sorted(losses)
    assert book.stress[0]["loss"] < 0


def test_a_concentrated_book_is_riskier_than_a_spread_one():
    conc = analyse_text("20 lakh in Reliance")
    spread = analyse_text("5 lakh in Reliance, 5 lakh in gold, "
                          "5 lakh in FD and 5 lakh in a nifty index fund")
    assert conc.concentration["top1_pct"] > spread.concentration["top1_pct"]
    assert conc.annual_vol > spread.annual_vol


def test_gold_and_debt_cushion_an_equity_crash():
    """Gold usually rises when equities fall; a book holding it should lose
    less in a crisis than one that does not."""
    equity = analyse_text("10 lakh in Reliance")
    mixed = analyse_text("5 lakh in Reliance and 5 lakh in gold")
    worst_e = min(s["loss_pct"] for s in equity.stress)
    worst_m = min(s["loss_pct"] for s in mixed.stress)
    assert worst_m > worst_e


def test_midcaps_are_hit_harder_than_large_caps():
    """IL&FS: mid and small caps fell roughly three times as far."""
    large = analyse_text("10 lakh in HDFC Bank")
    mid = analyse_text("10 lakh in a midcap fund")
    assert min(s["loss_pct"] for s in mid.stress) < min(s["loss_pct"] for s in large.stress)


def test_approximation_is_always_disclosed(book):
    joined = " ".join(book.caveats)
    assert "cannot be priced" in joined
    assert "assumed" in joined.lower()


def test_empty_input_is_handled():
    a = analyse_text("hello there")
    assert a.holdings == [] and a.caveats


def test_every_bucket_has_complete_characteristics():
    for name, b in BUCKETS.items():
        assert {"label", "beta", "vol", "cap_segment", "adv_inr", "note"} <= set(b)
        assert b["note"], name


# ------------------------------------------------------------ goals


def test_goal_reports_both_an_even_chance_and_a_safe_one():
    """The naive answer -- compound the median return backwards -- has about a
    50% chance of working, which is a poor basis for a plan you cannot redo."""
    g = plan_goal(10_000_000, 15, n_sims=2000)
    assert g.monthly_for_80pct > g.monthly_required
    assert g.monthly_required > 0


def test_longer_horizon_needs_less_per_month():
    short = plan_goal(10_000_000, 10, n_sims=1500)
    long = plan_goal(10_000_000, 20, n_sims=1500)
    assert long.monthly_required < short.monthly_required


def test_goal_restates_the_target_in_todays_money():
    """A crore in fifteen years is not a crore."""
    g = plan_goal(10_000_000, 15, n_sims=1000)
    assert g.target_in_todays_money < g.target * 0.7
    assert any("buys today" in c for c in g.caveats)


def test_safer_asset_needs_more_saving():
    eq = plan_goal(5_000_000, 15, asset="indian_equity", n_sims=1500)
    fd = plan_goal(5_000_000, 15, asset="fixed_deposit", n_sims=1500)
    assert fd.monthly_required > eq.monthly_required


def test_goal_rejects_nonsense():
    with pytest.raises(ValueError):
        plan_goal(-1, 10)
    with pytest.raises(ValueError):
        plan_goal(1_000_000, 99)


@pytest.mark.parametrize("q,target,years", [
    ("I want 1 crore in 15 years", 10_000_000, 15),
    ("I need to save 50 lakh in 10 years for my daughter", 5_000_000, 10),
    ("target 25 lakh over 8 years", 2_500_000, 8),
])
def test_parses_goals(q, target, years):
    g = parse_goal(q)
    assert g and g["target"] == pytest.approx(target) and g["years"] == pytest.approx(years)


# --------------------------------------------------------- routing


@pytest.mark.parametrize("q,route", [
    ("I have 8 lakh in HDFC Bank and 3 lakh in gold", "portfolio"),
    ("I want 1 crore in 15 years", "goal"),
    ("What is the NAV of Parag Parikh Flexi Cap fund", "fund"),
    ("If I invest 5 lakh in equity for 7 years", "projection"),
    ("Will the Nifty fall below 22900 in the next 30 days?", "council"),
    ("what is the repo rate", "data"),
])
def test_routes_to_the_right_answer(q, route):
    assert classify(q) == route


def test_goal_and_projection_are_distinguished():
    """Both carry an amount and a horizon. The difference is which end is
    known: a goal names the destination, a projection names the stake."""
    assert classify("I want 1 crore in 15 years") == "goal"
    assert classify("If I invest 5 lakh for 15 years") == "projection"
