"""Proper scoring rules and per-member track records.

A council whose members are never scored is a focus group. Every forecast here
is graded with a *strictly proper* rule -- one where a forecaster minimises
expected loss only by reporting what it actually believes, so there is no
incentive to hedge to 50% or to grandstand at 99%.

  Brier score       (p - y)^2, bounded [0, 1], lower is better
  log score         -log p_outcome, unbounded, punishes confident errors hard
  pinball loss      quantile forecasts; averaged over quantiles it is a
                    discrete approximation to CRPS

The track record then feeds two things: pooling weights, and each member's
*bias correction* -- the systematic log-odds offset it applies relative to
outcomes. A permabear that is right about direction but always 15 points too
pessimistic is valuable once that 15 points is subtracted.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

EPS = 1e-6


def clamp(p: float, eps: float = EPS) -> float:
    return min(max(p, eps), 1.0 - eps)


def logit(p: float) -> float:
    p = clamp(p)
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------- scoring rules


def brier_score(p: float, outcome: bool) -> float:
    return float((clamp(p) - float(outcome)) ** 2)


def log_score(p: float, outcome: bool) -> float:
    p = clamp(p)
    return float(-math.log(p if outcome else 1 - p))


def multicategory_brier(dist: dict[str, float], outcome: str) -> float:
    """Sum of squared errors across all categories (the Brier generalisation)."""
    return float(sum((v - (1.0 if k == outcome else 0.0)) ** 2 for k, v in dist.items()))


def multicategory_log_score(dist: dict[str, float], outcome: str) -> float:
    return float(-math.log(clamp(dist.get(outcome, 0.0))))


def pinball_loss(quantile: float, predicted: float, actual: float) -> float:
    d = actual - predicted
    return float(max(quantile * d, (quantile - 1) * d))


def crps_from_quantiles(
    quantile_values: dict[str, float] | dict[float, float], actual: float
) -> float:
    """Mean pinball loss across quantiles -- a consistent estimator of CRPS,
    up to a scaling that is constant for a fixed quantile grid."""
    items = [(float(q), float(v)) for q, v in quantile_values.items()]
    if not items:
        return float("nan")
    return float(np.mean([pinball_loss(q, v, actual) for q, v in items]))


def interval_coverage(
    quantile_values: dict[str, float], actual: float, lo: float = 0.05, hi: float = 0.95
) -> bool | None:
    low, high = quantile_values.get(str(lo)), quantile_values.get(str(hi))
    if low is None or high is None:
        return None
    return bool(low <= actual <= high)


# ------------------------------------------------------------------ calibration


def calibration_curve(
    probs: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> pd.DataFrame:
    """Predicted vs realised frequency per probability bin.

    A well-calibrated forecaster's points sit on the 45-degree line: when it
    says 70%, the thing happens 70% of the time.
    """
    df = pd.DataFrame({"p": np.asarray(probs, float), "y": np.asarray(outcomes, float)})
    edges = np.linspace(0, 1, n_bins + 1)
    df["bin"] = pd.cut(df["p"], edges, include_lowest=True)
    out = df.groupby("bin", observed=True).agg(
        n=("y", "size"), mean_predicted=("p", "mean"), observed_freq=("y", "mean")
    )
    out["gap"] = out["observed_freq"] - out["mean_predicted"]
    return out.reset_index()


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> float:
    c = calibration_curve(probs, outcomes, n_bins)
    if c.empty:
        return float("nan")
    w = c["n"] / c["n"].sum()
    return float((w * c["gap"].abs()).sum())


def murphy_decomposition(
    probs: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> dict[str, float]:
    """Brier = reliability - resolution + uncertainty.

    reliability  how far off calibration is (lower better)
    resolution   how much the forecasts actually discriminate (higher better)
    uncertainty  the base rate's own variance -- nothing anyone can do about it

    Two forecasters with the same Brier score can be completely different:
    one calibrated but uninformative, one informative but overconfident.
    """
    p = np.asarray(probs, float)
    y = np.asarray(outcomes, float)
    if p.size == 0:
        return {"reliability": np.nan, "resolution": np.nan, "uncertainty": np.nan, "brier": np.nan}
    base = float(y.mean())
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)

    rel = res = 0.0
    for b in range(n_bins):
        m = idx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        pb, yb = float(p[m].mean()), float(y[m].mean())
        rel += nb * (pb - yb) ** 2
        res += nb * (yb - base) ** 2
    n = p.size
    return {
        "reliability": rel / n,
        "resolution": res / n,
        "uncertainty": base * (1 - base),
        "brier": float(np.mean((p - y) ** 2)),
        "base_rate": base,
        "n": int(n),
    }


# --------------------------------------------------------------- track records


@dataclass(slots=True)
class MemberRecord:
    member: str
    n: int = 0
    mean_brier: float = float("nan")
    mean_log_score: float = float("nan")
    mean_crps: float = float("nan")
    ece: float = float("nan")
    bias_logit: float = 0.0        # systematic over/under-statement, in log-odds
    resolution: float = float("nan")
    reliability: float = float("nan")
    skill_vs_base_rate: float = float("nan")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


class TrackRecord:
    """Append-only ledger of (forecast, outcome) pairs, with derived skill.

    Persisted as JSONL so a record survives restarts and can be inspected or
    audited outside Python.
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.rows: list[dict] = []
        if self.path and self.path.exists():
            self.rows = [json.loads(ln) for ln in self.path.read_text().splitlines() if ln.strip()]

    def record(
        self,
        member: str,
        question_id: str,
        *,
        probability: float | None = None,
        distribution: dict[str, float] | None = None,
        quantile_values: dict[str, float] | None = None,
        outcome_binary: bool | None = None,
        outcome_category: str | None = None,
        outcome_value: float | None = None,
        resolved_at: dt.datetime | None = None,
    ) -> None:
        row: dict = {
            "member": member,
            "question_id": question_id,
            "resolved_at": (resolved_at or dt.datetime.now(dt.UTC)).isoformat(),
        }
        if probability is not None and outcome_binary is not None:
            row.update(
                kind="binary", p=float(probability), y=bool(outcome_binary),
                brier=brier_score(probability, outcome_binary),
                log_score=log_score(probability, outcome_binary),
            )
        elif distribution and outcome_category is not None:
            row.update(
                kind="categorical", dist=distribution, y=outcome_category,
                brier=multicategory_brier(distribution, outcome_category),
                log_score=multicategory_log_score(distribution, outcome_category),
            )
        elif quantile_values and outcome_value is not None:
            row.update(
                kind="numeric", qv=quantile_values, y=float(outcome_value),
                crps=crps_from_quantiles(quantile_values, outcome_value),
                covered_90=interval_coverage(quantile_values, outcome_value),
            )
        else:
            raise ValueError("forecast and outcome types do not match")

        self.rows.append(row)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")

    # ------------------------------------------------------------------ derive

    def members(self) -> list[str]:
        return sorted({r["member"] for r in self.rows})

    def score(self, member: str, half_life: float | None = None) -> MemberRecord:
        """Summarise a member's skill.

        With ``half_life`` (in number of resolved questions) older results are
        down-weighted, so a member that recently improved is not held to its
        cold-start performance forever.
        """
        rows = [r for r in self.rows if r["member"] == member]
        rec = MemberRecord(member=member, n=len(rows))
        if not rows:
            return rec

        binary = [r for r in rows if r.get("kind") == "binary"]
        cat = [r for r in rows if r.get("kind") == "categorical"]
        num = [r for r in rows if r.get("kind") == "numeric"]

        def wmean(vals: list[float], k: int) -> float:
            if not vals:
                return float("nan")
            if half_life is None:
                return float(np.mean(vals))
            ages = np.arange(k - 1, -1, -1)[-len(vals):]
            w = 0.5 ** (ages / half_life)
            return float(np.average(vals, weights=w))

        briers = [r["brier"] for r in binary + cat if "brier" in r]
        logs = [r["log_score"] for r in binary + cat if "log_score" in r]
        crps = [r["crps"] for r in num if "crps" in r]
        rec.mean_brier = wmean(briers, len(briers))
        rec.mean_log_score = wmean(logs, len(logs))
        rec.mean_crps = wmean(crps, len(crps))

        if binary:
            ps = [r["p"] for r in binary]
            ys = [r["y"] for r in binary]
            rec.ece = expected_calibration_error(ps, ys)
            d = murphy_decomposition(ps, ys)
            rec.resolution, rec.reliability = d["resolution"], d["reliability"]
            base = float(np.mean(ys))
            base_brier = base * (1 - base)
            rec.skill_vs_base_rate = (
                float(1 - rec.mean_brier / base_brier) if base_brier > 0 else float("nan")
            )
            # Calibration-in-the-large: how far the forecaster's average
            # log-odds sits from the log-odds of what actually happened.
            #
            # The obvious formulation -- mean(logit(p) - logit(y)) -- is wrong,
            # and wrong in a way that quietly poisons pooling. logit of a 0/1
            # outcome is +/-13.8 after clamping, so that average is dominated
            # by the clamp constant and the base rate rather than by the
            # forecaster, and a perfectly calibrated member picks up a large
            # spurious bias whenever the base rate is not 0.5.
            rec.bias_logit = float(np.mean([logit(p) for p in ps]) - logit(base))
        return rec

    def all_scores(self, half_life: float | None = None) -> pd.DataFrame:
        recs = [self.score(m, half_life).to_dict() for m in self.members()]
        return pd.DataFrame(recs).set_index("member") if recs else pd.DataFrame()

    def weights(
        self, members: Iterable[str], eta: float = 8.0, floor: float = 0.02,
        half_life: float | None = 40.0,
    ) -> dict[str, float]:
        """Performance weights via exponentiated negative loss (Hedge).

        ``eta`` controls how aggressively past skill is rewarded. ``floor``
        guarantees every member keeps a voice, which matters because the whole
        point of a bias-diverse council is that the currently-worst member is
        the one that catches the regime change.

        Members with no track record get the mean weight -- new personas are
        neither punished nor privileged.
        """
        members = list(members)
        if not members:
            return {}
        losses: dict[str, float] = {}
        for m in members:
            r = self.score(m, half_life)
            loss = r.mean_brier if not math.isnan(r.mean_brier) else r.mean_crps
            if loss is not None and not math.isnan(loss) and r.n > 0:
                losses[m] = loss

        if not losses:
            return {m: 1.0 / len(members) for m in members}

        # Normalise losses so eta means the same thing across question types.
        vals = np.array(list(losses.values()))
        lo, hi = vals.min(), vals.max()
        span = hi - lo if hi > lo else 1.0
        default = float(np.mean(vals))

        raw = {}
        for m in members:
            loss = losses.get(m, default)
            raw[m] = math.exp(-eta * (loss - lo) / span)

        total = sum(raw.values())
        w = {m: v / total for m, v in raw.items()}

        # Apply the floor, then renormalise the remainder.
        n = len(members)
        if floor * n >= 1.0:
            return {m: 1.0 / n for m in members}
        slack = 1.0 - floor * n
        return {m: floor + slack * w[m] for m in members}

    def bias_corrections(self, members: Iterable[str], shrink: float = 0.5) -> dict[str, float]:
        """Per-member log-odds bias, shrunk toward zero.

        Shrinkage matters: with 20 resolved questions the estimated bias is
        mostly noise, and over-correcting turns a useful contrarian into a
        me-too. ``shrink`` scales the correction; the effective shrinkage also
        grows with sample size via n/(n+10).
        """
        out = {}
        for m in members:
            r = self.score(m)
            if r.n < 5 or math.isnan(r.bias_logit):
                out[m] = 0.0
            else:
                out[m] = float(shrink * r.bias_logit * (r.n / (r.n + 10)))
        return out
