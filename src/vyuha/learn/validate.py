"""Statistical gate between "we found a variable" and "we believe it matters".

This module exists because of one number: if you test 100 unrelated series
against Nifty returns at p<0.05, roughly **five will look significant on pure
noise**. An automated loop that discovers variables daily and keeps whatever
correlates will therefore accumulate spurious predictors indefinitely, grow
more confident as it does, and get worse. The failure is silent and it
compounds.

Three defences, all necessary and none sufficient alone:

**Out-of-sample only.** The relationship is fitted on an early slice and
measured on a later one the fit never saw. An in-sample correlation is not
evidence of anything.

**A gap between train and test.** Macro series are autocorrelated and often
overlap in construction, so adjacent observations leak. A purge gap between
the two slices removes the most obvious leakage.

**Multiple-comparison correction.** Benjamini-Hochberg across everything tested
in the same batch, controlling the false discovery rate rather than the
per-test error. The denominator is what makes the p-values mean anything, so
the batch size is recorded with every result.

Even a survivor is only a *correlation that persisted out of sample after
correction*. That is not causation, and the module never claims otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(slots=True)
class ValidationResult:
    key: str
    n_aligned: int = 0
    tested: bool = False
    in_sample_rho: float = float("nan")
    oos_rho: float = float("nan")
    oos_p: float = float("nan")
    p_adjusted: float = float("nan")
    survives_fdr: bool = False
    effect_size: float = float("nan")
    direction: str = ""
    note: str = ""
    batch_size: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


def benjamini_hochberg(pvals: Sequence[float], q: float = 0.10) -> np.ndarray:
    """Which hypotheses survive at false-discovery rate ``q``.

    Controls the expected *proportion* of false positives among rejections,
    which is the right criterion when screening many candidates: with q=0.10
    roughly one in ten survivors is expected to be spurious, and that is a
    stated, bounded cost rather than an unknown one.
    """
    p = np.asarray(pvals, float)
    n = p.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresholds = q * (np.arange(1, n + 1) / n)
    passed = ranked <= thresholds
    out = np.zeros(n, dtype=bool)
    if passed.any():
        cutoff = np.max(np.where(passed)[0])
        out[order[: cutoff + 1]] = True
    return out


def adjusted_pvalues(pvals: Sequence[float]) -> np.ndarray:
    """BH-adjusted p-values (q-values), monotonic and clipped to 1."""
    p = np.asarray(pvals, float)
    n = p.size
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order]
    adj = ranked * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(adj, 0, 1)
    return out


def _align(
    candidate: pd.DataFrame, target: pd.Series, lag: int = 1,
    value_col: str = "value", date_col: str = "date",
) -> pd.DataFrame:
    """Align a candidate to forward target returns, with an explicit lag.

    The lag is not cosmetic. Using X(t) to explain return(t) tests whether the
    two move together, which is usually just both reacting to the same thing.
    Using X(t-1) asks whether X came *first*, which is the only version with
    any use.
    """
    c = candidate[[date_col, value_col]].dropna().copy()
    c[date_col] = pd.to_datetime(c[date_col])
    c = c.sort_values(date_col).set_index(date_col)[value_col]

    # Changes, not levels: most macro series are non-stationary and a
    # regression of one trending series on another finds a relationship
    # between the trends, not the variables.
    dx = c.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

    t = target.dropna().copy()
    t.index = pd.to_datetime(t.index)
    t = t.sort_index()

    df = pd.DataFrame({"x": dx}).join(pd.DataFrame({"y": t}), how="outer").sort_index()
    df["y_fwd"] = df["y"].shift(-lag)
    return df.dropna(subset=["x", "y_fwd"])[["x", "y_fwd"]]


def validate_one(
    key: str, candidate: pd.DataFrame, target: pd.Series,
    lag: int = 1, train_frac: float = 0.6, purge: int = 3, min_obs: int = 40,
) -> ValidationResult:
    """Test one candidate out of sample. No FDR correction yet -- that is
    applied across the batch by :func:`validate_candidates`."""
    res = ValidationResult(key=key)
    try:
        df = _align(candidate, target, lag=lag)
    except Exception as exc:  # noqa: BLE001
        res.note = f"alignment failed: {type(exc).__name__}: {exc}"
        return res

    res.n_aligned = len(df)
    if len(df) < min_obs:
        res.note = (
            f"only {len(df)} aligned observations; need {min_obs}. Most Indian "
            "macro series are monthly, so this usually means too little history."
        )
        return res

    split = int(len(df) * train_frac)
    train = df.iloc[:split]
    test = df.iloc[split + purge:]          # purge gap kills the obvious leakage
    if len(test) < 20:
        res.note = f"only {len(test)} out-of-sample points after purging"
        return res

    rho_in, _ = stats.spearmanr(train["x"], train["y_fwd"])
    rho_out, p_out = stats.spearmanr(test["x"], test["y_fwd"])

    res.tested = True
    res.in_sample_rho = float(rho_in)
    res.oos_rho = float(rho_out)
    res.oos_p = float(p_out)
    res.effect_size = float(abs(rho_out))
    res.direction = "positive" if rho_out > 0 else "negative"
    res.diagnostics = {
        "n_train": len(train), "n_test": len(test), "purge": purge, "lag": lag,
        # A sign flip between train and test is the signature of a fluke.
        "sign_consistent": bool(np.sign(rho_in) == np.sign(rho_out)),
        "in_sample_stronger": bool(abs(rho_in) > abs(rho_out)),
    }
    return res


def validate_candidates(
    candidates: dict[str, pd.DataFrame], target: pd.Series,
    lag: int = 1, q: float = 0.10, require_sign_consistency: bool = True,
) -> list[ValidationResult]:
    """Test a batch and apply FDR correction across it.

    ``require_sign_consistency`` additionally throws out anything whose
    relationship flips direction between the fit and the holdout, which is the
    clearest signature of a fluke and costs almost nothing to enforce.
    """
    results = [validate_one(k, df, target, lag=lag) for k, df in candidates.items()]
    tested = [r for r in results if r.tested]
    if not tested:
        for r in results:
            r.batch_size = len(results)
        return results

    pvals = [r.oos_p for r in tested]
    survives = benjamini_hochberg(pvals, q=q)
    adj = adjusted_pvalues(pvals)

    for r, s, a in zip(tested, survives, adj, strict=True):
        r.p_adjusted = float(a)
        r.batch_size = len(tested)
        ok = bool(s)
        if ok and require_sign_consistency and not r.diagnostics.get("sign_consistent"):
            ok = False
            r.note = "relationship flipped sign out of sample; rejected as a fluke"
        r.survives_fdr = ok
        if ok and not r.note:
            r.note = (
                f"survived BH-FDR at q={q} across {len(tested)} tests "
                f"(out-of-sample rho {r.oos_rho:+.3f}). A persistent correlation, "
                "not a demonstrated cause."
            )
    for r in results:
        if not r.batch_size:
            r.batch_size = len(tested)
    return results


def expected_false_positives(n_tests: int, alpha: float = 0.05) -> float:
    """How many of ``n_tests`` would clear ``alpha`` on pure noise.

    Printed alongside results so the number of survivors is always read
    against the number that chance alone would produce.
    """
    return n_tests * alpha


def summarise(results: Iterable[ValidationResult], q: float = 0.10) -> dict[str, Any]:
    rs = list(results)
    tested = [r for r in rs if r.tested]
    survivors = [r for r in tested if r.survives_fdr]
    naive = [r for r in tested if r.oos_p < 0.05]
    return {
        "candidates": len(rs),
        "tested": len(tested),
        "untestable": len(rs) - len(tested),
        "naive_significant_p05": len(naive),
        "expected_by_chance": round(expected_false_positives(len(tested)), 1),
        "survive_fdr": len(survivors),
        "survivors": [r.key for r in survivors],
        "fdr_q": q,
        "reading": (
            f"{len(naive)} of {len(tested)} cleared a naive p<0.05, and chance "
            f"alone would produce about {expected_false_positives(len(tested)):.1f}. "
            f"After FDR correction {len(survivors)} survive."
        ),
    }
