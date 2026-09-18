"""Liquidity risk.

The risk number that matters in a crisis is not "how much could this fall" but
"how much could this fall *before I can get out*". In India that distinction is
sharp: the listed universe runs to several thousand names, of which only a few
hundred trade enough that a large position can be exited inside a day. Circuit
limits can halt a stock entirely, and the exit you modelled may simply not
exist on the day you need it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def amihud_illiquidity(
    returns: pd.DataFrame, volume_inr: pd.DataFrame, window: int = 60
) -> pd.DataFrame:
    """Amihud (2002) ILLIQ: mean of |return| / traded value.

    Reads as "price impact per rupee traded". Higher means a given rupee of
    trading moves the price more. Scale is arbitrary -- use it cross-sectionally
    or as a time series, not as an absolute.
    """
    impact = returns.abs() / volume_inr.replace(0, np.nan)
    return impact.rolling(window, min_periods=max(5, window // 4)).mean() * 1e6


def days_to_liquidate(
    positions: pd.Series, adv_inr: pd.Series, participation: float = 0.20
) -> pd.DataFrame:
    """Days to exit at a given share of average daily volume.

    ``participation`` is the fraction of ADV you assume you can be without
    moving the market against yourself. 20% is already aggressive for Indian
    mid-caps; 10% is the more defensible default for anything outside the
    Nifty 100.
    """
    capacity = adv_inr.reindex(positions.index).fillna(0.0) * participation
    days = positions.abs() / capacity.replace(0, np.nan)
    out = pd.DataFrame({
        "position_inr": positions,
        "adv_inr": adv_inr.reindex(positions.index),
        "daily_capacity_inr": capacity,
        "days_to_liquidate": days,
    })
    out["liquidity_bucket"] = pd.cut(
        days, [-np.inf, 1, 3, 10, 30, np.inf],
        labels=["<1d", "1-3d", "3-10d", "10-30d", ">30d"],
    )
    # An unmeasurable position is not a liquid one -- treat NaN as the worst case.
    out["untradeable"] = days.isna() | np.isinf(days)
    return out


def liquidity_adjusted_var(
    var: float, days: float, daily_vol: float, participation_cost_bps: float = 25.0,
    position_value: float = 1.0,
) -> dict[str, float]:
    """Widen VaR for the time it actually takes to get out.

    Two additions to the headline number:
      exit-horizon risk -- you are exposed for ``days``, not one day, so the
        market risk scales by sqrt(days)
      execution cost   -- spread plus impact, which rises with the square root
        of how long the exit takes (a standard impact approximation)
    """
    horizon_var = var * np.sqrt(max(days, 1.0))
    exec_cost = (participation_cost_bps / 10_000.0) * np.sqrt(max(days, 1.0))
    total = horizon_var + exec_cost
    return {
        "headline_var": var,
        "days_to_liquidate": days,
        "horizon_adjusted_var": float(horizon_var),
        "execution_cost": float(exec_cost),
        "liquidity_adjusted_var": float(total),
        "liquidity_premium": float(total - var),
        "liquidity_premium_pct": float((total - var) / var) if var > 0 else np.nan,
        "value_at_risk_inr": float(total * position_value),
    }


def concentration(positions: pd.Series) -> dict[str, float]:
    """Herfindahl and top-N concentration.

    Relevant for India specifically because index concentration is high: a
    handful of corporate groups carry enough weight that "diversified across
    the Nifty" is less diversified than it sounds.
    """
    v = positions.abs()
    total = float(v.sum())
    if total <= 0:
        return {"hhi": np.nan, "effective_n": np.nan}
    w = v / total
    hhi = float((w**2).sum())
    top = w.sort_values(ascending=False)
    return {
        "hhi": hhi,
        "effective_n": float(1 / hhi) if hhi > 0 else np.nan,
        "top1_pct": float(top.iloc[0]) if len(top) else np.nan,
        "top5_pct": float(top.head(5).sum()),
        "top10_pct": float(top.head(10).sum()),
        "n_positions": int((v > 0).sum()),
    }


def circuit_limit_risk(
    returns: pd.DataFrame, limits: pd.Series | float = 0.10, lookback: int = 252
) -> pd.DataFrame:
    """How often each name has hit its price band.

    A stock locked at its circuit limit cannot be sold at any price. This is
    the failure mode that turns a modelled loss into an unmodelled one, and it
    is largely absent from risk systems designed for developed markets.
    """
    lim = (
        pd.Series(limits, index=returns.columns) if np.isscalar(limits)
        else limits.reindex(returns.columns)
    )
    recent = returns.tail(lookback)
    hits = (recent.abs() >= (lim * 0.99)).sum()
    return pd.DataFrame({
        "circuit_limit": lim,
        "days_at_limit": hits,
        "pct_days_at_limit": hits / len(recent),
        "max_abs_move": recent.abs().max(),
        "circuit_risk": hits > (len(recent) * 0.01),
    }).sort_values("days_at_limit", ascending=False)
