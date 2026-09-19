"""Opinion pooling.

Averaging forecasts is the obvious thing and it is subtly wrong. The classic
result (Satopaa et al. 2014; Baron et al. 2014) is that a simple average of
well-calibrated but *differently informed* forecasters is systematically
*under-confident*: each member hedges for the uncertainty it personally has,
and averaging preserves every one of those hedges even though collectively the
group knows more. The fix is to pool in log-odds space and then extremise.

Pipeline:

    1. bias-correct   shift each member's log-odds by its historical bias
    2. pool           weighted average in log-odds (= weighted geometric mean
                      of odds), with weights from the track record
    3. extremise      push the pooled log-odds away from 0.5 by a factor that
                      grows with how *independent* the members are
    4. report spread  dispersion and named dissent travel with the answer

Step 4 is the one most systems skip. A 60% consensus built from members at
58/59/61/62 is a completely different object from one built from 5/95/20/99,
and a risk system that reports only "60%" has destroyed the more important half
of its own output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from vyuha.council.schema import CouncilVerdict, Forecast, Question, QuestionKind
from vyuha.council.scoring import EPS, clamp, expit, logit


@dataclass(slots=True)
class PoolConfig:
    """Pooling knobs.

    ``extremise_cap`` is the maximum log-odds multiplier. The default of 1.8 is
    deliberately conservative -- it sits at the low end of the 1.5-3.0 range in
    the forecast-aggregation literature, because extremising an ensemble that
    is *not* actually independent manufactures false confidence, and that error
    is far more costly in a risk system than leaving a little sharpness on the
    table. Do not treat it as a constant: call ``fit_extremise_cap`` once you
    have 50+ resolved questions and let your own track record set it.
    """
    method: str = "log"              # "log" | "linear" | "median"
    extremise: bool = True
    extremise_cap: float = 1.8
    bias_correct: bool = True
    trim: float = 0.0                # fraction trimmed from each tail before pooling


# ----------------------------------------------------------------- dispersion


def dispersion_binary(probs: list[float]) -> float:
    """Standard deviation of member probabilities. 0 = unanimous."""
    return float(np.std(probs, ddof=1)) if len(probs) > 1 else 0.0


def dispersion_categorical(dists: list[list[float]]) -> float:
    """Mean Jensen-Shannon divergence of each member from the group mean.

    Bounded [0, 1] with log base 2, so it is comparable across questions with
    different numbers of outcomes.
    """
    if len(dists) < 2:
        return 0.0
    arr = np.clip(np.asarray(dists, float), EPS, None)
    arr = arr / arr.sum(axis=1, keepdims=True)
    m = arr.mean(axis=0)

    def kl(p: np.ndarray, q: np.ndarray) -> float:
        return float(np.sum(p * np.log2(p / q)))

    return float(np.mean([0.5 * kl(p, m) + 0.5 * kl(m, p) for p in arr]))


def directional_agreement(probs: list[float]) -> float:
    """How united the panel is on *which side* of the question it lands, in [0, 1].

    1.0 = every member on the same side of 50%. 0.0 = a dead even split.
    """
    if not probs:
        return 0.0
    above = sum(1 for p in probs if p > 0.5)
    frac = above / len(probs)
    return float(abs(2 * frac - 1))


def effective_independence(probs: list[float]) -> float:
    """How much genuinely independent information the panel carries, in [0, 1].

    This gates extremisation, and getting it wrong is dangerous in both
    directions, so it combines two signals that must *both* be present:

      spread     members that differ are more likely to be reasoning from
                 different information than members that echo each other
      agreement  ...but only if they still land on the same side. A panel
                 split 5%/95% has enormous spread and zero shared signal;
                 extremising it manufactures confidence out of a deadlock

    Multiplying the two means a bimodal, polarised council is pulled *toward*
    50%, which is the honest reading of "our members fundamentally disagree",
    while a panel that unanimously leans one way but hedges individually gets
    the full Satopaa correction it deserves.
    """
    if len(probs) < 2:
        return 0.0
    spread = float(np.std(probs, ddof=1))
    spread_term = float(np.clip(spread / 0.25, 0.0, 1.0))
    return float(spread_term * directional_agreement(probs))


# --------------------------------------------------------------------- pooling


def _weights_for(members: list[str], weights: dict[str, float] | None) -> np.ndarray:
    if not weights:
        return np.full(len(members), 1.0 / len(members))
    w = np.array([max(weights.get(m, 0.0), 0.0) for m in members], float)
    return np.full(len(members), 1.0 / len(members)) if w.sum() <= 0 else w / w.sum()


def pool_binary(
    probs: list[float],
    members: list[str] | None = None,
    weights: dict[str, float] | None = None,
    bias: dict[str, float] | None = None,
    config: PoolConfig | None = None,
) -> tuple[float, dict]:
    cfg = config or PoolConfig()
    members = members or [f"m{i}" for i in range(len(probs))]
    if not probs:
        return 0.5, {"note": "no forecasts"}

    p = [clamp(x) for x in probs]
    lo = [logit(x) for x in p]

    if cfg.bias_correct and bias:
        lo = [x - bias.get(m, 0.0) for x, m in zip(lo, members, strict=True)]

    w = _weights_for(members, weights)

    if cfg.trim > 0 and len(lo) >= 5:
        order = np.argsort(lo)
        k = max(1, int(len(lo) * cfg.trim))
        keep = order[k:-k] if len(order) > 2 * k else order
        lo = [lo[i] for i in keep]
        w = w[keep] / w[keep].sum()
        members = [members[i] for i in keep]

    if cfg.method == "median":
        pooled_lo = float(np.median(lo))
    elif cfg.method == "linear":
        pooled_lo = logit(float(np.average([expit(x) for x in lo], weights=w)))
    else:  # log-odds pool
        pooled_lo = float(np.average(lo, weights=w))

    info = {
        "raw_pooled": expit(pooled_lo),
        "method": cfg.method,
        "bias_corrected": bool(cfg.bias_correct and bias),
    }

    if cfg.extremise and len(probs) > 1:
        indep = effective_independence(probs)
        # a = 1 means no extremisation; grows toward the cap with independence.
        a = 1.0 + (cfg.extremise_cap - 1.0) * indep
        pooled_lo *= a
        info["extremise_factor"] = a
        info["effective_independence"] = indep

    out = expit(pooled_lo)
    info["pooled"] = out
    return out, info


def pool_categorical(
    dists: list[dict[str, float]],
    outcomes: list[str],
    members: list[str] | None = None,
    weights: dict[str, float] | None = None,
    config: PoolConfig | None = None,
) -> tuple[dict[str, float], dict]:
    """Weighted logarithmic pool: p ∝ Π p_i^{w_i}, renormalised.

    The log pool is *externally Bayesian* -- pooling then updating on new
    evidence gives the same answer as updating then pooling. The linear pool
    does not have this property, which is why a linear pool can be made to
    disagree with itself by reordering the evidence.
    """
    cfg = config or PoolConfig()
    if not dists:
        n = len(outcomes)
        return {o: 1.0 / n for o in outcomes}, {"note": "no forecasts"}

    members = members or [f"m{i}" for i in range(len(dists))]
    w = _weights_for(members, weights)
    arr = np.clip(np.array([[d.get(o, 0.0) for o in outcomes] for d in dists], float), EPS, None)
    arr = arr / arr.sum(axis=1, keepdims=True)

    if cfg.method == "linear":
        pooled = np.average(arr, axis=0, weights=w)
    else:
        log_pooled = np.average(np.log(arr), axis=0, weights=w)
        pooled = np.exp(log_pooled - log_pooled.max())
        pooled = pooled / pooled.sum()

    return (
        {o: float(v) for o, v in zip(outcomes, pooled, strict=True)},
        {
            "method": cfg.method,
            "dispersion_js": dispersion_categorical(arr.tolist()),
            "entropy_bits": float(-np.sum(pooled * np.log2(np.clip(pooled, EPS, None)))),
        },
    )


def pool_quantiles(
    quantile_sets: list[dict[str, float]],
    quantiles: list[float],
    members: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict]:
    """Vincentisation -- average the quantile *values* at each probability level.

    This is the right way round. Averaging the densities (a linear pool) of two
    confident forecasters who disagree produces a bimodal blob whose mean sits
    in a region neither of them considers likely. Averaging the quantiles
    produces a distribution centred between them with sensibly widened
    uncertainty, which is what a reader expects "the council thinks" to mean.
    """
    if not quantile_sets:
        return {}, {"note": "no forecasts"}
    members = members or [f"m{i}" for i in range(len(quantile_sets))]
    w = _weights_for(members, weights)

    out: dict[str, float] = {}
    spreads: list[float] = []
    for q in quantiles:
        key = str(q)
        vals, ws = [], []
        for qs, wi in zip(quantile_sets, w, strict=True):
            v = qs.get(key)
            if v is not None and np.isfinite(v):
                vals.append(float(v))
                ws.append(wi)
        if vals:
            out[key] = float(np.average(vals, weights=ws))
            spreads.append(float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0)

    # Enforce monotonicity; Vincentisation preserves it, floating point may not.
    keys = sorted(out, key=float)
    running = -math.inf
    for k in keys:
        running = max(running, out[k])
        out[k] = running

    width = (
        out.get(str(quantiles[-1]), float("nan")) - out.get(str(quantiles[0]), float("nan"))
        if len(quantiles) >= 2 else float("nan")
    )
    return out, {
        "method": "vincentisation",
        "mean_member_spread": float(np.mean(spreads)) if spreads else 0.0,
        "interval_width": width,
    }


# ------------------------------------------------------------------- top level


def aggregate(
    question: Question,
    forecasts: list[Forecast],
    weights: dict[str, float] | None = None,
    bias: dict[str, float] | None = None,
    config: PoolConfig | None = None,
) -> CouncilVerdict:
    """Pool a round of forecasts into a verdict that keeps its own disagreement."""
    cfg = config or PoolConfig()
    usable = [f for f in forecasts if f.parse_ok]
    members = [f.member for f in usable]

    verdict = CouncilVerdict(
        question_id=question.id,
        kind=question.kind,
        n_members=len(usable),
        method=cfg.method,
        weights=_as_dict(members, _weights_for(members, weights)) if members else {},
        bias_corrections={m: (bias or {}).get(m, 0.0) for m in members},
        member_forecasts=forecasts,
    )
    if not usable:
        verdict.notes.append("no parseable forecasts; verdict is the uninformative prior")
        if question.kind is QuestionKind.BINARY:
            verdict.probability = 0.5
        return verdict

    if question.kind is QuestionKind.BINARY:
        probs = [f.probability if f.probability is not None else 0.5 for f in usable]
        pooled, info = pool_binary(probs, members, weights, bias, cfg)
        verdict.probability = pooled
        verdict.dispersion = dispersion_binary(probs)
        verdict.notes.append(_fmt_info(info))
        verdict.dissent = _name_dissent_binary(usable, probs, pooled)

    elif question.kind is QuestionKind.CATEGORICAL:
        outcomes = question.outcomes or []
        dists = [f.distribution or {} for f in usable]
        pooled, info = pool_categorical(dists, outcomes, members, weights, cfg)
        verdict.distribution = pooled
        verdict.dispersion = float(info.get("dispersion_js", 0.0))
        verdict.notes.append(_fmt_info(info))

    else:  # NUMERIC
        qsets = [f.quantile_values or {} for f in usable]
        pooled, info = pool_quantiles(qsets, question.quantiles, members, weights)
        verdict.quantile_values = pooled
        med = [q.get("0.5") for q in qsets if q.get("0.5") is not None]
        verdict.dispersion = float(np.std(med, ddof=1)) if len(med) > 1 else 0.0
        verdict.notes.append(_fmt_info(info))

    # A member that cited nothing asserted things it was not given evidence for.
    verdict.uncited_claims_flagged = sum(1 for f in usable if not f.citations)
    verdict.strongest_counterargument = _strongest_counter(usable, verdict)
    return verdict


def _as_dict(members: list[str], w: np.ndarray) -> dict[str, float]:
    return {m: float(x) for m, x in zip(members, w, strict=True)}


def _fmt_info(info: dict) -> str:
    return "; ".join(
        f"{k}={v:.4g}" if isinstance(v, (int, float)) else f"{k}={v}"
        for k, v in info.items()
    )


def _name_dissent_binary(
    forecasts: list[Forecast], probs: list[float], pooled: float, threshold: float = 0.15
) -> list[str]:
    out = []
    for f, p in zip(forecasts, probs, strict=True):
        if abs(p - pooled) >= threshold:
            direction = "above" if p > pooled else "below"
            out.append(f"{f.member}: {p:.1%} ({direction} consensus) - {f.key_driver or f.reasoning[:160]}")
    return out


def _strongest_counter(forecasts: list[Forecast], verdict: CouncilVerdict) -> str:
    """Surface the reasoning of whichever member is furthest from the consensus.

    Deliberately not the best-scoring member's view: the point is to hand the
    reader the argument most likely to overturn the answer they were just given.
    """
    if verdict.probability is None or not forecasts:
        return ""
    far = max(
        forecasts,
        key=lambda f: abs((f.probability if f.probability is not None else 0.5) - verdict.probability),
    )
    if far.reasoning:
        return f"[{far.member} @ {far.probability:.1%}] {far.reasoning.strip()[:600]}"
    return ""


def fit_extremise_cap(
    panels: list[tuple[list[float], bool]],
    grid: tuple[float, ...] = (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.25, 2.5, 3.0),
    config: PoolConfig | None = None,
) -> tuple[float, object]:
    """Choose the extremisation cap that minimises Brier score on resolved history.

    ``panels`` is a list of (member probabilities, outcome) pairs. The returned
    cap is the one your council actually earns, which is the only defensible way
    to set it -- a cap borrowed from a paper was fitted to a different panel
    answering different questions.

    A fitted cap near 1.0 is not a failure. It means your members are more
    correlated than they look, and the honest response is to diversify the panel
    (different base models, different evidence) rather than to extremise harder.
    """
    from vyuha.council.scoring import brier_score

    base = config or PoolConfig()
    rows = []
    for cap in grid:
        cfg = PoolConfig(
            method=base.method, extremise=cap > 1.0, extremise_cap=cap,
            bias_correct=base.bias_correct, trim=base.trim,
        )
        scores = [brier_score(pool_binary(ps, config=cfg)[0], y) for ps, y in panels if ps]
        rows.append({"cap": cap, "brier": float(np.mean(scores)) if scores else float("nan"),
                     "n": len(scores)})
    table = sorted(rows, key=lambda r: r["brier"])
    return float(table[0]["cap"]), rows
