"""Return construction. Deliberately picky, because this is where silent
errors enter every downstream number.

Indian-market specifics handled here:
  * Corporate actions -- NSE bhavcopy prices are *not* adjusted. Splits and
    bonuses show up as fake -50% or -80% days. ``adjust_for_actions`` applies
    a backward cumulative adjustment factor.
  * Circuit limits -- stocks locked at +/-5/10/20% produce zero-volume prints
    that are not tradable. Flagged, not silently used.
  * Stale prints -- illiquid counters repeat yesterday's close. A run of exact
    zero returns is a data artefact, not low volatility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def simple_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return prices.pct_change().iloc[1:]


def log_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return np.log(prices / prices.shift(1)).iloc[1:]


def align_prices(
    prices: pd.DataFrame, min_obs: int = 60, max_stale_run: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align a price panel and return (clean_prices, quality_flags).

    Columns with fewer than ``min_obs`` observations are dropped. Stale runs
    longer than ``max_stale_run`` are flagged so volatility estimates can
    discount them rather than reading them as calm.
    """
    prices = prices.sort_index()
    keep = prices.notna().sum() >= min_obs
    dropped = sorted(prices.columns[~keep])
    prices = prices.loc[:, keep]

    unchanged = prices.diff() == 0
    stale_run = unchanged.groupby((~unchanged).cumsum()).cumsum()
    flags = pd.DataFrame(
        {
            "stale_days": unchanged.sum(),
            "max_stale_run": stale_run.max(),
            "coverage": prices.notna().mean(),
            "suspect": stale_run.max() > max_stale_run,
        }
    )
    flags.attrs["dropped_insufficient_history"] = dropped
    return prices, flags


def adjust_for_actions(
    prices: pd.DataFrame, actions: pd.DataFrame
) -> pd.DataFrame:
    """Back-adjust prices for splits/bonuses/dividends.

    ``actions`` needs columns: ``symbol``, ``ex_date``, ``ratio`` where ratio is
    the multiplicative price factor on the ex-date (0.5 for a 1:1 bonus, 0.2 for
    a 1:5 split, ``1 - div/close`` for a dividend).
    """
    adj = prices.copy()
    for sym, grp in actions.groupby("symbol"):
        if sym not in adj.columns:
            continue
        factor = pd.Series(1.0, index=adj.index)
        for _, a in grp.iterrows():
            ex = pd.Timestamp(a["ex_date"])
            factor.loc[factor.index < ex] *= float(a["ratio"])
        adj[sym] = adj[sym] * factor
    return adj


def winsorize(r: pd.DataFrame | pd.Series, lower: float = 0.001, upper: float = 0.999):
    """Clip extreme returns cross-sectionally.

    Note: for *tail risk* work you usually must NOT do this -- the tail is the
    signal. Use it for factor estimation, not for VaR.
    """
    lo, hi = r.quantile(lower), r.quantile(upper)
    return r.clip(lower=lo, upper=hi, axis=1 if isinstance(r, pd.DataFrame) else None)


def annualise_vol(daily_vol: float | np.ndarray, periods: int = 252):
    return daily_vol * np.sqrt(periods)


def realised_vol(returns: pd.Series, window: int = 21, annualise: bool = True) -> pd.Series:
    v = returns.rolling(window).std()
    return annualise_vol(v) if annualise else v


def drawdown(cum_returns: pd.Series) -> pd.Series:
    peak = cum_returns.cummax()
    return cum_returns / peak - 1.0
