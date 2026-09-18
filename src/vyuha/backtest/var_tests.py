"""VaR backtesting -- the part that decides whether to believe the risk number.

A 99% 1-day VaR makes a falsifiable claim: losses should exceed it on about 1
day in 100, and those exceptions should be scattered, not bunched. Both halves
matter, and they fail differently:

  Kupiec POF          tests the *count* of exceptions. Catches a VaR that is
                      simply too low (or too high).
  Christoffersen      tests *independence* -- whether an exception today makes
                      one tomorrow more likely. A model can pass Kupiec and
                      still fail catastrophically here: the right number of
                      breaches, all in the same week, is what actually blows
                      up a book.
  Conditional coverage joint test of both.

These are the tests Basel's traffic-light framework is built on, and running
them is the difference between a risk system and a random number generator
with good manners.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(slots=True)
class BacktestResult:
    n_obs: int
    n_exceptions: int
    expected_exceptions: float
    exception_rate: float
    confidence: float
    kupiec_stat: float
    kupiec_p: float
    christoffersen_stat: float
    christoffersen_p: float
    conditional_coverage_stat: float
    conditional_coverage_p: float
    basel_zone: str
    verdict: str

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


def kupiec_pof(n: int, x: int, p: float) -> tuple[float, float]:
    """Unconditional coverage likelihood-ratio test."""
    if n == 0:
        return np.nan, np.nan
    if x == 0:
        lr = -2 * n * np.log(1 - p)
    elif x == n:
        lr = -2 * n * np.log(p)
    else:
        phat = x / n
        lr = -2 * (
            (n - x) * np.log(1 - p) + x * np.log(p)
            - (n - x) * np.log(1 - phat) - x * np.log(phat)
        )
    return float(lr), float(1 - stats.chi2.cdf(lr, df=1))


def christoffersen_independence(exceptions: np.ndarray) -> tuple[float, float]:
    """Tests whether exceptions cluster, via a first-order Markov chain."""
    e = np.asarray(exceptions, int)
    if e.size < 2:
        return np.nan, np.nan
    n00 = int(np.sum((e[:-1] == 0) & (e[1:] == 0)))
    n01 = int(np.sum((e[:-1] == 0) & (e[1:] == 1)))
    n10 = int(np.sum((e[:-1] == 1) & (e[1:] == 0)))
    n11 = int(np.sum((e[:-1] == 1) & (e[1:] == 1)))

    if (n01 + n11) == 0 or (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0  # not enough transitions to reject independence

    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11)
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    if pi in (0.0, 1.0) or pi01 in (0.0,) or pi11 in (0.0, 1.0):
        return 0.0, 1.0

    ll_null = (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
    ll_alt = (
        n00 * np.log(1 - pi01) + n01 * np.log(pi01)
        + n10 * np.log(1 - pi11) + n11 * np.log(pi11)
    )
    lr = -2 * (ll_null - ll_alt)
    return float(lr), float(1 - stats.chi2.cdf(lr, df=1))


def basel_traffic_light(n: int, x: int, p: float = 0.01) -> str:
    """Basel's green/yellow/red zones, scaled to the sample length.

    Defined for 250 days at 99%; scaled proportionally for other windows.
    Red means the model is rejected and capital multipliers apply.
    """
    if n == 0:
        return "unknown"
    scale = n / 250.0
    if x <= 4 * scale:
        return "green"
    if x <= 9 * scale:
        return "yellow"
    return "red"


def backtest_var(
    returns: pd.Series, var_forecasts: pd.Series, confidence: float = 0.99
) -> BacktestResult:
    """Score a series of VaR forecasts against what actually happened.

    ``var_forecasts`` are positive loss magnitudes aligned to ``returns``, each
    made *before* its return was observed. An exception is a day where the
    realised loss exceeded the forecast.
    """
    df = pd.concat([returns.rename("r"), var_forecasts.rename("var")], axis=1).dropna()
    if df.empty:
        raise ValueError("no overlapping dates between returns and VaR forecasts")

    exceptions = (df["r"] < -df["var"]).astype(int).values
    n, x = len(df), int(exceptions.sum())
    p = 1 - confidence

    k_stat, k_p = kupiec_pof(n, x, p)
    c_stat, c_p = christoffersen_independence(exceptions)
    cc_stat = (k_stat + c_stat) if np.isfinite(k_stat) and np.isfinite(c_stat) else np.nan
    cc_p = float(1 - stats.chi2.cdf(cc_stat, df=2)) if np.isfinite(cc_stat) else np.nan

    zone = basel_traffic_light(n, x, p)
    if n < 100:
        verdict = f"inconclusive - {n} observations is too few to test a {confidence:.0%} VaR"
    elif k_p < 0.05 and (x / n) > p:
        verdict = "REJECTED - too many exceptions; the model understates risk"
    elif k_p < 0.05:
        verdict = "rejected - too few exceptions; the model overstates risk and wastes capital"
    elif np.isfinite(c_p) and c_p < 0.05:
        verdict = ("rejected on independence - exceptions cluster. The count is right but "
                   "they arrive together, which is the dangerous failure")
    else:
        verdict = "not rejected - consistent with the data"

    return BacktestResult(
        n_obs=n, n_exceptions=x, expected_exceptions=n * p, exception_rate=x / n,
        confidence=confidence, kupiec_stat=k_stat, kupiec_p=k_p,
        christoffersen_stat=c_stat, christoffersen_p=c_p,
        conditional_coverage_stat=cc_stat, conditional_coverage_p=cc_p,
        basel_zone=zone, verdict=verdict,
    )


def rolling_var_backtest(
    returns: pd.Series, estimator, window: int = 500, confidence: float = 0.99,
    step: int = 1,
) -> tuple[pd.Series, BacktestResult]:
    """Walk forward: fit on a trailing window, forecast the next day, never peek.

    ``estimator`` is called as ``estimator(window_returns, confidence=...)`` and
    must return an object with a ``.var`` attribute.
    """
    forecasts: dict = {}
    for i in range(window, len(returns), step):
        hist = returns.iloc[i - window:i]
        try:
            forecasts[returns.index[i]] = estimator(hist, confidence=confidence).var
        except Exception:  # noqa: BLE001 - a failed fit is a missing forecast, not a crash
            continue
    if not forecasts:
        raise ValueError("no VaR forecasts could be produced")
    fc = pd.Series(forecasts)
    return fc, backtest_var(returns.reindex(fc.index), fc, confidence)
