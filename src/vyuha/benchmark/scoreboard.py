"""Where Vyuha stands, against the only comparisons that are honest.

There is no leaderboard for "Indian market forecasting systems". Aladdin
publishes no accuracy figures, brokerages publish selected calls, and no public
benchmark for this market exists at all. So "how do we compare" has to be
answered with reference points that are real, sourced, and carefully caveated.

THE COMPARABILITY PROBLEM

Brier scores are NOT directly comparable across question sets. A forecaster
answering "will this coin land heads" and one answering "will the RBI cut in
December" can post identical Brier scores having done entirely different work.
The forecasting literature states this explicitly, and any comparison that
ignores it is marketing.

Two things ARE comparable across sets, and both are reported here:

  skill score vs base rate   1 - BS/BS_base. Normalises for how predictable
                             the questions were. A forecaster who cannot beat
                             the base rate has added nothing, whatever its
                             raw Brier.
  head-to-head vs the market the option-implied probability answers the SAME
                             question at the SAME moment. This is the only
                             strictly fair comparison available, and it is a
                             hard one.

The published figures below are context for reading a number, not a ladder to
climb.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True, frozen=True)
class Reference:
    name: str
    brier: float
    source: str
    note: str = ""


#: Published Brier scores, with sources. Retrieved 2026-09-28. Each is on its
#: OWN question set -- mostly geopolitical and general-knowledge questions,
#: not markets -- so they bound what good looks like rather than defining a
#: target Vyuha can be ranked against.
REFERENCES: tuple[Reference, ...] = (
    Reference(
        "Always saying 50%", 0.25, "arithmetic",
        "The floor. A forecaster scoring near this has learned nothing.",
    ),
    Reference(
        "Human crowd (Halawi et al. 2024)", 0.149, "arXiv 2507.04562",
        "General crowd forecasting on Metaculus-style questions.",
    ),
    Reference(
        "o3, direct prediction", 0.1352, "arXiv 2507.04562",
        "A frontier model forecasting unaided. Roughly crowd level.",
    ),
    Reference(
        "Metaculus community prediction", 0.126, "metaculus.com track record",
        "Recency-weighted median of all forecasters, evaluated at all times.",
    ),
    Reference(
        "Karger et al. 2025 crowd", 0.121, "arXiv 2507.04562",
        "A stronger crowd baseline on a different question set.",
    ),
    Reference(
        "Metaculus proprietary ensemble", 0.107, "Metaculus FAQ",
        "Performance-weighted and extremised -- the same construction Vyuha "
        "uses. Questions resolved in 2021.",
    ),
    Reference(
        "Superforecaster median", 0.10, "ForecastBench",
        "The practical ceiling for human forecasting.",
    ),
)


@dataclass(slots=True)
class Standing:
    n_resolved: int = 0
    brier: float = float("nan")
    base_rate: float = float("nan")
    base_rate_brier: float = float("nan")
    skill_vs_base_rate: float = float("nan")
    calibration_error: float = float("nan")
    resolution: float = float("nan")
    vs_market: dict[str, Any] = field(default_factory=dict)
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = ""
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


#: Below this, a Brier score is mostly noise.
MIN_FOR_A_NUMBER = 30
#: Below this, comparing to published figures is meaningless.
MIN_FOR_COMPARISON = 100


def standing(track, member: str = "__council__") -> Standing:
    """Vyuha's current position, with every caveat attached."""
    from vyuha.council.scoring import expected_calibration_error, murphy_decomposition

    rows = [r for r in track.rows
            if r.get("member") == member and r.get("kind") == "binary"]
    s = Standing(n_resolved=len(rows))

    if not rows:
        s.verdict = (
            "No resolved questions yet. Every number below would be invented. "
            "The daily loop poses questions at 1-7 day horizons, so the first "
            "real figures arrive within about a week."
        )
        return s

    probs = np.array([r["p"] for r in rows], float)
    outcomes = np.array([bool(r["y"]) for r in rows])

    s.brier = float(np.mean((probs - outcomes.astype(float)) ** 2))
    s.base_rate = float(outcomes.mean())
    s.base_rate_brier = float(np.mean((s.base_rate - outcomes.astype(float)) ** 2))
    s.skill_vs_base_rate = (
        float(1 - s.brier / s.base_rate_brier) if s.base_rate_brier > 0 else float("nan")
    )
    s.calibration_error = expected_calibration_error(probs, outcomes)
    d = murphy_decomposition(probs, outcomes)
    s.resolution = d["resolution"]

    s.comparisons = [
        {
            "name": r.name, "their_brier": r.brier, "our_brier": s.brier,
            "difference": round(s.brier - r.brier, 4),
            "source": r.source, "note": r.note,
            # Stated on every row so no single line can be quoted as a ranking.
            "comparable": False,
        }
        for r in REFERENCES
    ]

    if s.n_resolved < MIN_FOR_A_NUMBER:
        s.verdict = (
            f"{s.n_resolved} resolved questions. Too few for the Brier score to "
            f"mean much -- it needs about {MIN_FOR_A_NUMBER} before it stops "
            "being noise, and roughly 100 before comparison to anything else "
            "is worth doing."
        )
    elif s.skill_vs_base_rate < 0:
        s.verdict = (
            f"Brier {s.brier:.4f}, which is WORSE than simply always predicting "
            f"the base rate of {s.base_rate:.0%} (skill {s.skill_vs_base_rate:+.1%}). "
            "On this evidence the council is adding nothing over a constant."
        )
    elif s.skill_vs_base_rate < 0.05:
        s.verdict = (
            f"Brier {s.brier:.4f}, essentially indistinguishable from predicting "
            f"the base rate (skill {s.skill_vs_base_rate:+.1%})."
        )
    else:
        s.verdict = (
            f"Brier {s.brier:.4f}, beating the base rate by "
            f"{s.skill_vs_base_rate:.1%} over {s.n_resolved} questions. "
            "That is genuine skill on THIS question set."
        )

    s.caveats = [
        "Brier scores are not comparable across question sets. The published "
        "figures above are on general-knowledge and geopolitical questions, "
        "not markets, so they bound what good looks like rather than ranking "
        "anyone.",
        "Vyuha's questions are largely self-posed and short-horizon, which "
        "makes them a different and probably easier set than Metaculus's.",
        "The only strictly fair comparison is against the option-implied "
        "probability on the same question at the same moment -- see "
        "benchmark/compare.py.",
    ]
    if s.n_resolved < MIN_FOR_COMPARISON:
        s.caveats.insert(0, (
            f"Only {s.n_resolved} resolved questions; at least "
            f"{MIN_FOR_COMPARISON} before any comparison carries weight."
        ))
    return s


def render(s: Standing) -> str:
    """A text scoreboard that cannot be mistaken for a ranking."""
    lines = ["VYUHA — WHERE IT STANDS", "=" * 58, ""]
    if not s.n_resolved:
        return "\n".join(lines + [s.verdict])

    lines += [
        f"  resolved questions       {s.n_resolved}",
        f"  Brier score              {s.brier:.4f}   (0 perfect, 0.25 = coin flip)",
        f"  base rate of YES         {s.base_rate:.1%}",
        f"  skill vs base rate       {s.skill_vs_base_rate:+.1%}"
        "   <- the comparable number",
        f"  calibration error        {s.calibration_error:.4f}",
        f"  resolution               {s.resolution:.4f}   (higher = more discriminating)",
        "",
        "  FOR CONTEXT ONLY — different question sets, NOT a ranking",
    ]
    for c in sorted(s.comparisons, key=lambda x: -x["their_brier"]):
        mark = "▲" if c["difference"] < 0 else "▼"
        lines.append(
            f"    {c['name']:36} {c['their_brier']:.4f}  {mark} "
            f"{abs(c['difference']):.4f}"
        )
    lines += ["", f"  {s.verdict}", ""]
    for c in s.caveats:
        lines.append(f"  · {c}")
    return "\n".join(lines)
