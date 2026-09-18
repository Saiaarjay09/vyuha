"""Stress testing against India's own crisis history.

Parametric risk models fail in precisely the moments you built them for:
correlations that sat at 0.3 for three years go to 0.9, liquidity that was
never a constraint becomes the only constraint, and a distribution fitted to
calm markets assigns a probability of 1-in-10,000-years to something that has
happened four times since 2008.

So Vyuha stresses against events that actually occurred in this market. The
scenarios below are calibrated from the historical record; every one carries
its date range so you can re-derive the shocks from data rather than trusting
the numbers typed here.

These are *approximations* of headline moves, not exact replays. Use
``replay_historical`` with real price history when you have it -- a true replay
of the actual return path always beats a stylised shock vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True, frozen=True)
class Scenario:
    """A named stress. Shocks are fractional returns: -0.20 is a 20% fall."""

    key: str
    name: str
    description: str
    period: str = ""
    equity_shock: float = 0.0
    midcap_extra: float = 0.0        # additional shock to mid/small caps
    rate_shock_bp: float = 0.0       # parallel G-sec move, basis points
    credit_spread_bp: float = 0.0    # corporate spread widening
    inr_shock: float = 0.0           # +ve = INR depreciation vs USD
    oil_shock: float = 0.0           # fractional move in Brent
    vol_multiplier: float = 1.0      # multiplier on realised vol
    correlation_to: float | None = None  # correlations forced toward this level
    liquidity_haircut: float = 0.0   # fraction of normal volume still available
    tags: tuple[str, ...] = field(default_factory=tuple)
    lesson: str = ""


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "gfc_2008", "Global Financial Crisis", period="2008-01 to 2009-03",
        description="Global deleveraging. Nifty fell ~60% peak to trough, FII "
                    "outflows were the largest on record, INR fell past 50.",
        equity_shock=-0.55, midcap_extra=-0.15, rate_shock_bp=-150,
        credit_spread_bp=400, inr_shock=0.22, oil_shock=-0.70,
        vol_multiplier=3.5, correlation_to=0.90, liquidity_haircut=0.55,
        tags=("global", "systemic"),
        lesson="Diversification across Indian sectors provided almost no protection. "
               "Everything correlated to one factor: global risk appetite.",
    ),
    Scenario(
        "taper_tantrum_2013", "Taper Tantrum", period="2013-05 to 2013-09",
        description="Fed signalled QE tapering. India was singled out among the "
                    "'Fragile Five' on its current account deficit; INR fell from "
                    "55 to 68 and the RBI defended it with an emergency rate spike.",
        equity_shock=-0.12, midcap_extra=-0.10, rate_shock_bp=300,
        credit_spread_bp=150, inr_shock=0.20, oil_shock=0.05,
        vol_multiplier=2.2, correlation_to=0.75, liquidity_haircut=0.30,
        tags=("external", "currency", "rates"),
        lesson="The canonical India-specific stress: an external funding shock hits "
               "the currency and rates far harder than equities. An equity-only risk "
               "model would have called this a mild correction.",
    ),
    Scenario(
        "demonetisation_2016", "Demonetisation", period="2016-11 to 2017-01",
        description="86% of currency by value withdrawn overnight. A policy shock "
                    "with no market precedent and no warning.",
        equity_shock=-0.08, midcap_extra=-0.06, rate_shock_bp=-50,
        inr_shock=0.03, vol_multiplier=1.8, liquidity_haircut=0.20,
        tags=("policy", "domestic", "idiosyncratic"),
        lesson="No statistical model could have anticipated this, and that is the "
               "point. It is the strongest argument in this repository for keeping a "
               "policy-literate human, or persona, in the loop.",
    ),
    Scenario(
        "ilfs_2018", "IL&FS Credit Freeze", period="2018-09 to 2019-03",
        description="IL&FS default froze NBFC funding. A liquidity and credit event "
                    "concentrated in financials and mid-caps.",
        equity_shock=-0.14, midcap_extra=-0.22, rate_shock_bp=50,
        credit_spread_bp=250, inr_shock=0.08, vol_multiplier=2.0,
        correlation_to=0.70, liquidity_haircut=0.45,
        tags=("credit", "domestic", "sectoral"),
        lesson="Mid and small caps fell roughly three times as far as large caps. Any "
               "model treating 'Indian equity' as one exposure missed the entire event.",
    ),
    Scenario(
        "covid_crash_2020", "COVID-19 Crash", period="2020-02 to 2020-03",
        description="Fastest bear market in Indian history: -38% in about five weeks, "
                    "with circuit breakers triggered market-wide.",
        equity_shock=-0.38, midcap_extra=-0.10, rate_shock_bp=-100,
        credit_spread_bp=300, inr_shock=0.07, oil_shock=-0.65,
        vol_multiplier=4.0, correlation_to=0.95, liquidity_haircut=0.60,
        tags=("global", "systemic", "fast"),
        lesson="Speed itself is a risk. A monthly-rebalanced hedge was useless; VaR "
               "models on 250-day windows updated far too slowly to matter.",
    ),
    Scenario(
        "adani_2023", "Single-Name Governance Shock", period="2023-01 to 2023-03",
        description="A short-seller report triggered a ~70% fall in a large group's "
                    "shares, with index and banking-sector contagion.",
        equity_shock=-0.05, midcap_extra=-0.08, credit_spread_bp=80,
        vol_multiplier=1.6, liquidity_haircut=0.35,
        tags=("idiosyncratic", "governance", "concentration"),
        lesson="Concentration risk in Indian indices is real -- a handful of groups "
               "carry meaningful index weight. Name-level stress is not optional here.",
    ),
    Scenario(
        "oil_shock_hypo", "Hypothetical Oil Spike", period="hypothetical",
        description="Brent to $150 on a supply disruption. India imports >85% of its "
                    "crude, so this hits the current account, fiscal position, "
                    "inflation and currency simultaneously.",
        equity_shock=-0.18, midcap_extra=-0.07, rate_shock_bp=150,
        credit_spread_bp=120, inr_shock=0.15, oil_shock=0.90,
        vol_multiplier=2.3, correlation_to=0.75, liquidity_haircut=0.25,
        tags=("commodity", "hypothetical", "external"),
        lesson="India's single largest macro vulnerability, and one that transmits "
               "through four channels at once.",
    ),
    Scenario(
        "monsoon_failure_hypo", "Monsoon Failure", period="hypothetical",
        description="Rainfall 25% below normal. Food inflation spikes, rural demand "
                    "collapses, and the RBI is forced to hold or tighten into weakness.",
        equity_shock=-0.10, midcap_extra=-0.08, rate_shock_bp=100,
        inr_shock=0.05, vol_multiplier=1.5,
        tags=("weather", "hypothetical", "domestic"),
        lesson="A climate variable that propagates all the way to the policy rate. "
               "Few risk systems anywhere model weather as a financial factor; in "
               "India it is not optional.",
    ),
    Scenario(
        "fpi_exodus_hypo", "Sustained FPI Exodus", period="hypothetical",
        description="Twelve months of persistent foreign outflows on a global "
                    "risk-off regime, partially absorbed by domestic SIP flows.",
        equity_shock=-0.22, midcap_extra=-0.12, rate_shock_bp=120,
        credit_spread_bp=150, inr_shock=0.12, vol_multiplier=2.0,
        correlation_to=0.80, liquidity_haircut=0.40,
        tags=("flows", "hypothetical"),
        lesson="Tests the load-bearing assumption of the current Indian bull case: "
               "that domestic flows can absorb any foreign selling.",
    ),
)

BY_KEY: dict[str, Scenario] = {s.key: s for s in SCENARIOS}


# ------------------------------------------------------------------- applying


def apply_scenario(
    positions: pd.DataFrame, scenario: Scenario, beta_col: str = "beta",
) -> pd.DataFrame:
    """Shock a position book.

    ``positions`` needs ``value`` (market value, INR) and should carry whichever
    of ``beta``, ``cap_segment``, ``duration``, ``credit_spread_dv01``,
    ``fx_exposure`` and ``oil_beta`` apply. Missing columns are treated as zero
    exposure -- and the count of such omissions is reported, because unmodelled
    exposure is the most dangerous kind.
    """
    p = positions.copy()
    if "value" not in p.columns:
        raise ValueError("positions needs a 'value' column")

    beta = p[beta_col] if beta_col in p.columns else pd.Series(1.0, index=p.index)
    eq = beta * scenario.equity_shock

    if "cap_segment" in p.columns:
        extra = p["cap_segment"].str.lower().isin(["mid", "small", "midcap", "smallcap"])
        eq = eq + extra.astype(float) * scenario.midcap_extra

    p["equity_pnl"] = p["value"] * eq

    # Bond price move ≈ -duration * Δy (+ convexity correction if provided).
    dy = scenario.rate_shock_bp / 10_000.0
    if "duration" in p.columns:
        conv = p["convexity"] if "convexity" in p.columns else 0.0
        p["rates_pnl"] = p["value"] * (-p["duration"].fillna(0) * dy + 0.5 * conv * dy**2)
    else:
        p["rates_pnl"] = 0.0

    if "credit_spread_dv01" in p.columns:
        p["credit_pnl"] = -p["credit_spread_dv01"].fillna(0) * scenario.credit_spread_bp
    else:
        p["credit_pnl"] = 0.0

    if "fx_exposure" in p.columns:
        p["fx_pnl"] = p["fx_exposure"].fillna(0) * scenario.inr_shock
    else:
        p["fx_pnl"] = 0.0

    if "oil_beta" in p.columns:
        p["oil_pnl"] = p["value"] * p["oil_beta"].fillna(0) * scenario.oil_shock
    else:
        p["oil_pnl"] = 0.0

    pnl_cols = ["equity_pnl", "rates_pnl", "credit_pnl", "fx_pnl", "oil_pnl"]
    p["total_pnl"] = p[pnl_cols].sum(axis=1)
    p["pnl_pct"] = p["total_pnl"] / p["value"].replace(0, np.nan)
    return p


def run_all(
    positions: pd.DataFrame, scenarios: tuple[Scenario, ...] = SCENARIOS
) -> pd.DataFrame:
    """Every scenario against one book, worst first."""
    total = float(positions["value"].sum())
    rows = []
    for sc in scenarios:
        shocked = apply_scenario(positions, sc)
        pnl = float(shocked["total_pnl"].sum())
        worst = shocked.nsmallest(1, "total_pnl")
        rows.append({
            "scenario": sc.key, "name": sc.name,
            "pnl": pnl,
            "pnl_pct": pnl / total if total else np.nan,
            "equity_pnl": float(shocked["equity_pnl"].sum()),
            "rates_pnl": float(shocked["rates_pnl"].sum()),
            "credit_pnl": float(shocked["credit_pnl"].sum()),
            "fx_pnl": float(shocked["fx_pnl"].sum()),
            "oil_pnl": float(shocked["oil_pnl"].sum()),
            "worst_position": worst.index[0] if len(worst) else None,
            "worst_position_pnl": float(worst["total_pnl"].iloc[0]) if len(worst) else np.nan,
            "liquidity_haircut": sc.liquidity_haircut,
            "tags": ",".join(sc.tags),
        })
    return pd.DataFrame(rows).sort_values("pnl").reset_index(drop=True)


def unmodelled_exposures(positions: pd.DataFrame) -> list[str]:
    """Which risk axes this book carries no data for.

    Called out loudly because a stress test silently treating missing duration
    as zero duration will report a bond portfolio as immune to rate moves.
    """
    axes = {
        "beta": "equity market", "duration": "interest rate",
        "credit_spread_dv01": "credit spread", "fx_exposure": "currency",
        "oil_beta": "oil", "cap_segment": "size/liquidity segment",
    }
    return [label for col, label in axes.items() if col not in positions.columns]


def replay_historical(
    returns: pd.DataFrame, weights: pd.Series, start: str, end: str
) -> dict[str, Any]:
    """Replay an actual historical window against current weights.

    Strictly better than a stylised shock vector when you have the data: it
    preserves the real path, the real correlation dynamics and the real
    sequence of daily moves, which is what determines whether a stop or a
    margin call triggers.
    """
    window = returns.loc[start:end]
    if window.empty:
        raise ValueError(f"no return data between {start} and {end}")
    w = weights.reindex(window.columns).fillna(0.0)
    port = window @ w
    cum = (1 + port).cumprod()
    dd = cum / cum.cummax() - 1
    return {
        "start": start, "end": end, "n_days": len(window),
        "total_return": float(cum.iloc[-1] - 1),
        "max_drawdown": float(dd.min()),
        "worst_day": float(port.min()),
        "best_day": float(port.max()),
        "realised_vol_ann": float(port.std(ddof=1) * np.sqrt(252)),
        "days_beyond_2pct": int((port.abs() > 0.02).sum()),
        "path": port,
    }
