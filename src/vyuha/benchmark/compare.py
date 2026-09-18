"""Scoring Vyuha against the market, and against itself.

"Better than BlackRock" is not a measurable claim -- Aladdin is proprietary,
publishes no accuracy figures, and cannot be queried. What IS measurable is
whether a forecast beats a public, continuously-updating benchmark that real
money produces. For Indian index questions that benchmark is the option chain.

Three comparisons this module supports:

  vs market     council probability against the option-implied probability,
                both scored by Brier/log against what actually happened
  vs base rate  against the unconditional historical frequency. A forecaster
                that cannot beat "it happens 12% of the time" is adding nothing
  vs itself     the council's own calibration over time

The third is the one people skip and the first one that matters. A system can
beat the market on a handful of questions by luck; calibration over dozens is
much harder to fake.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from vyuha.council.scoring import brier_score, log_score, murphy_decomposition


@dataclass(slots=True)
class BenchmarkResult:
    n: int
    vyuha_brier: float
    market_brier: float
    base_rate_brier: float
    vyuha_log: float
    market_log: float
    skill_vs_market: float       # >0 means Vyuha beat the market
    skill_vs_base_rate: float
    verdict: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


def score_against_market(
    vyuha_probs: Sequence[float],
    market_probs: Sequence[float],
    outcomes: Sequence[bool],
    min_n: int = 20,
) -> BenchmarkResult:
    """Compare council forecasts to option-implied ones on resolved questions.

    ``skill_vs_market`` is the Brier skill score: 1 - BS_vyuha / BS_market.
    Positive means Vyuha was more accurate. Zero means indistinguishable.

    The ``verdict`` refuses to declare a winner below ``min_n`` questions,
    because with ten resolved questions the difference between a good
    forecaster and a lucky one is not visible. This is the guard that stops a
    small favourable sample being written up as an edge.
    """
    v = np.asarray(vyuha_probs, float)
    m = np.asarray(market_probs, float)
    y = np.asarray(outcomes, bool)
    if not (len(v) == len(m) == len(y)):
        raise ValueError("vyuha_probs, market_probs and outcomes must be the same length")
    n = len(y)
    if n == 0:
        raise ValueError("no resolved questions to score")

    base = float(y.mean())
    vb = float(np.mean([brier_score(p, o) for p, o in zip(v, y)]))
    mb = float(np.mean([brier_score(p, o) for p, o in zip(m, y)]))
    bb = float(np.mean([brier_score(base, o) for o in y]))
    vl = float(np.mean([log_score(p, o) for p, o in zip(v, y)]))
    ml = float(np.mean([log_score(p, o) for p, o in zip(m, y)]))

    skill_m = 1 - vb / mb if mb > 0 else float("nan")
    skill_b = 1 - vb / bb if bb > 0 else float("nan")

    if n < min_n:
        verdict = (
            f"INCONCLUSIVE - {n} resolved questions is too few to distinguish skill "
            f"from luck. Need at least {min_n}, and more like 100 to be confident."
        )
    elif skill_m > 0.05:
        verdict = f"Vyuha beat the option-implied benchmark by {skill_m:.1%} (Brier skill)."
    elif skill_m < -0.05:
        verdict = (
            f"The market beat Vyuha by {-skill_m:.1%}. The option chain is a strong "
            "benchmark -- this is the expected result until the council is tuned."
        )
    else:
        verdict = "Indistinguishable from the option-implied benchmark."

    return BenchmarkResult(
        n=n, vyuha_brier=vb, market_brier=mb, base_rate_brier=bb,
        vyuha_log=vl, market_log=ml,
        skill_vs_market=float(skill_m), skill_vs_base_rate=float(skill_b),
        verdict=verdict,
        detail={
            "base_rate": base,
            "vyuha_calibration": murphy_decomposition(v, y),
            "market_calibration": murphy_decomposition(m, y),
            "mean_vyuha_p": float(v.mean()),
            "mean_market_p": float(m.mean()),
            # If Vyuha is systematically below the market on downside questions
            # it may simply be harvesting the variance risk premium rather than
            # forecasting better. Worth knowing before claiming an edge.
            "mean_gap_vyuha_minus_market": float((v - m).mean()),
        },
    )


def capability_matrix() -> pd.DataFrame:
    """An honest feature comparison against Aladdin's documented capabilities.

    Compiled from BlackRock's own public descriptions of Aladdin. It is not a
    benchmark -- there is no way to run Aladdin -- it is a map of where a small
    open system can realistically compete and where it cannot.

    The useful reading is the ``india_edge`` column: the places where being
    small, local and transparent is an actual advantage rather than a
    consolation.
    """
    rows = [
        # capability, aladdin, vyuha, india_edge, note
        ("Multi-asset position keeping", "full", "none", False,
         "Aladdin is an operating system for a portfolio: trading, compliance, "
         "settlement. Vyuha is analytics only and should stay that way."),
        ("Licensed real-time market data", "full", "none", False,
         "Aladdin pays for direct exchange feeds. Vyuha uses public endpoints "
         "at throttled rates."),
        ("Global coverage", "full", "minimal", False,
         "Aladdin covers every major market. Vyuha covers India."),
        ("Order management / execution", "full", "none", False,
         "Out of scope by design."),
        ("Regulatory reporting", "full", "none", False,
         "UCITS, Solvency II, Form PF. Not attempted."),
        ("Decades of crisis history", "full", "partial", False,
         "Aladdin has 30+ years of positions through real crises."),

        ("Factor risk model", "full", "partial", True,
         "Vyuha's model includes a promoter-pledging/governance factor, which "
         "has no clean US analogue but has preceded many Indian mid-cap "
         "failures."),
        ("VaR + backtesting", "full", "full", False,
         "Kupiec, Christoffersen and Basel traffic light are standard and "
         "implemented here."),
        ("Stress scenarios", "full", "partial", True,
         "Vyuha's library is India-specific: demonetisation, IL&FS, taper "
         "tantrum, monsoon failure. Generic global scenarios miss these."),

        ("Indian alternative data", "unknown", "planned", True,
         "Power demand, GST e-way bills, UPI volumes, VAHAN registrations, IMD "
         "rainfall. A global vendor has little incentive to wire these up; for "
         "India they are causally connected to asset prices."),
        ("Circuit-limit / illiquidity modelling", "partial", "full", True,
         "A stock locked at its circuit cannot be sold at any price. Risk "
         "systems designed for developed markets largely ignore this."),
        ("Indian policy-shock awareness", "minimal", "partial", True,
         "Overnight duty changes, SEBI position limits, demonetisation. The "
         "policy persona reads for exactly this."),
        ("Monsoon -> food -> policy chain", "none", "planned", True,
         "Weather as a financial factor. Almost no risk system models it; in "
         "India it drives food inflation, the policy rate and equity multiples."),

        ("Calibrated probabilistic forecasts", "minimal", "full", True,
         "Aladdin quantifies risk; it does not publish scored, calibrated "
         "probability forecasts with tracked Brier scores."),
        ("Transparent, auditable reasoning", "none", "full", True,
         "Aladdin is a black box to its users. Every Vyuha verdict stores its "
         "evidence packet, every member's reasoning and a reproducible hash."),
        ("Disagreement as an output", "none", "full", True,
         "Aladdin returns a number. Vyuha returns a number plus how much its "
         "members disagreed, which is often the more useful half."),
        ("Cost", "~7 figures/yr", "free", True,
         "The decisive advantage for an individual or a small fund."),
        ("Inspectable and modifiable", "none", "full", True,
         "Apache 2.0. You can read every line that produced a number."),
    ]
    df = pd.DataFrame(rows, columns=["capability", "aladdin", "vyuha", "india_edge", "note"])
    return df


def gap_report() -> dict[str, Any]:
    """Where Vyuha is behind, where it can realistically win, and what is next."""
    m = capability_matrix()
    behind = m[(m["vyuha"].isin(["none", "minimal", "partial"])) & (~m["india_edge"])]
    edge = m[m["india_edge"]]
    return {
        "capabilities_compared": len(m),
        "structurally_behind": len(behind),
        "india_specific_edge": len(edge),
        "cannot_compete_on": behind["capability"].tolist(),
        "can_win_on": edge["capability"].tolist(),
        "honest_summary": (
            "Vyuha cannot and should not try to replace Aladdin. Aladdin is "
            "portfolio infrastructure -- trading, compliance, settlement, global "
            "coverage, licensed feeds. Competing there requires a company, not a "
            "repository. What a small Indian-focused system can genuinely do "
            "better is depth on India: alternative data that global vendors have "
            "no incentive to wire up, market structure that developed-market "
            "models ignore, policy shocks that statistical models cannot see, and "
            "transparency that a commercial black box cannot offer. Pick those "
            "fights and win them; do not pick the other one."
        ),
    }
