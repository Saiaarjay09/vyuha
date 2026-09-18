"""Cross-sectional factor model for Indian equities.

Vyuha uses a *fundamental* (characteristic-based) model in the Barra tradition
rather than a statistical one: exposures are observable characteristics (size,
value, momentum), and factor returns are estimated each period by
cross-sectional regression. The advantage over PCA is interpretability -- when
the model says a portfolio is carrying risk, it names which bet.

India-specific choices, which are not cosmetic:

  * A **size** factor is unusually important. The large/mid/small dispersion in
    this market is extreme and regime-dependent: in the IL&FS episode mid-caps
    fell roughly three times as far as large caps.
  * A **liquidity** factor is mandatory. A large share of listed Indian names
    trade thinly enough that illiquidity is a priced, and occasionally
    dominant, risk.
  * A **promoter-holding / governance** factor has no clean analogue in US
    models but matters here, where concentrated promoter ownership and share
    pledging have preceded a large share of mid-cap failures.

Estimation uses weighted least squares with square-root-of-market-cap weights
(standard practice: it stops micro-caps, which are numerous and noisy, from
determining the factor returns) and Huber-style robust down-weighting of
outliers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

STANDARD_FACTORS: tuple[str, ...] = (
    "market", "size", "value", "momentum", "quality", "low_vol", "liquidity", "growth",
)


@dataclass(slots=True)
class FactorModel:
    factor_returns: pd.DataFrame      # date x factor
    exposures: pd.DataFrame           # asset x factor (latest)
    specific_returns: pd.DataFrame    # date x asset
    r_squared: pd.Series              # per date
    factor_cov: pd.DataFrame | None = None
    specific_risk: pd.Series | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def risk_decomposition(self, weights: pd.Series) -> dict[str, Any]:
        """Split portfolio variance into factor and specific components.

        The ``pct_specific`` number is the one to watch. A portfolio whose risk
        is 70% specific is making stock bets; one at 10% is making a factor bet
        while believing it is picking stocks.
        """
        if self.factor_cov is None:
            raise ValueError("call fit_factor_covariance() first")
        w = weights.reindex(self.exposures.index).fillna(0.0)
        x = self.exposures.loc[w.index].fillna(0.0)
        fx = x.T @ w                                   # portfolio factor exposure
        factor_var = float(fx @ self.factor_cov.values @ fx)

        if self.specific_risk is not None:
            sr = self.specific_risk.reindex(w.index).fillna(self.specific_risk.median())
            specific_var = float((w**2 * sr**2).sum())
        else:
            specific_var = 0.0

        total = factor_var + specific_var
        return {
            "total_vol": float(np.sqrt(max(total, 0.0))),
            "total_vol_ann": float(np.sqrt(max(total, 0.0) * 252)),
            "factor_vol": float(np.sqrt(max(factor_var, 0.0))),
            "specific_vol": float(np.sqrt(max(specific_var, 0.0))),
            "pct_factor": factor_var / total if total > 0 else np.nan,
            "pct_specific": specific_var / total if total > 0 else np.nan,
            "factor_exposures": fx.to_dict(),
            "factor_contributions": _factor_contributions(fx, self.factor_cov, total),
        }


def _factor_contributions(fx: pd.Series, cov: pd.DataFrame, total: float) -> dict[str, float]:
    if total <= 0:
        return {}
    contrib = fx * (cov.values @ fx.values)
    return {k: float(v / total) for k, v in contrib.items()}


# ---------------------------------------------------------------- exposures


def zscore(s: pd.Series, winsor: float = 3.0) -> pd.Series:
    """Cross-sectional z-score, clipped at +/- ``winsor`` sigma.

    Clipping matters more in India than in developed markets: a handful of
    names routinely post characteristic values several hundred sigma from the
    median (a micro-cap with near-zero book value produces an astronomical P/B),
    and unclipped they alone determine the factor return.
    """
    s = pd.to_numeric(s, errors="coerce")
    med, mad = s.median(), (s - s.median()).abs().median()
    if mad and np.isfinite(mad) and mad > 0:
        s = s.clip(med - winsor * 1.4826 * mad, med + winsor * 1.4826 * mad)
    mu, sd = s.mean(), s.std(ddof=1)
    if not sd or not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return ((s - mu) / sd).clip(-winsor, winsor).fillna(0.0)


def build_exposures(characteristics: pd.DataFrame) -> pd.DataFrame:
    """Turn raw characteristics into standardised factor exposures.

    Expected (all optional; whatever is present gets used):
        market_cap, book_to_price, earnings_yield, return_12m_1m,
        roe, debt_to_equity, realised_vol_60d, turnover_ratio,
        sales_growth_3y, promoter_pledge_pct
    """
    c = characteristics
    x = pd.DataFrame(index=c.index)
    x["market"] = 1.0

    if "market_cap" in c:
        # Log market cap, negated so a positive loading means "small".
        x["size"] = -zscore(np.log(pd.to_numeric(c["market_cap"], errors="coerce").clip(lower=1)))
    if {"book_to_price", "earnings_yield"} & set(c.columns):
        parts = [zscore(c[k]) for k in ("book_to_price", "earnings_yield") if k in c]
        x["value"] = sum(parts) / len(parts)
    if "return_12m_1m" in c:
        x["momentum"] = zscore(c["return_12m_1m"])
    if {"roe", "debt_to_equity"} & set(c.columns):
        parts = []
        if "roe" in c:
            parts.append(zscore(c["roe"]))
        if "debt_to_equity" in c:
            parts.append(-zscore(c["debt_to_equity"]))
        x["quality"] = sum(parts) / len(parts)
    if "realised_vol_60d" in c:
        x["low_vol"] = -zscore(c["realised_vol_60d"])
    if "turnover_ratio" in c:
        x["liquidity"] = zscore(c["turnover_ratio"])
    if "sales_growth_3y" in c:
        x["growth"] = zscore(c["sales_growth_3y"])
    if "promoter_pledge_pct" in c:
        x["governance"] = -zscore(c["promoter_pledge_pct"])

    return x.fillna(0.0)


# ---------------------------------------------------------------- estimation


def cross_sectional_regression(
    returns: pd.Series, exposures: pd.DataFrame, weights: pd.Series | None = None,
    robust: bool = True,
) -> tuple[pd.Series, pd.Series, float]:
    """One period's WLS cross-sectional regression.

    Returns (factor_returns, specific_returns, r_squared).
    """
    idx = returns.dropna().index.intersection(exposures.dropna(how="all").index)
    if len(idx) < exposures.shape[1] + 5:
        raise ValueError(f"only {len(idx)} usable assets for {exposures.shape[1]} factors")

    y = returns.loc[idx].values
    x = exposures.loc[idx].fillna(0.0).values
    w = (
        np.sqrt(weights.loc[idx].clip(lower=0).values)
        if weights is not None else np.ones(len(idx))
    )
    w = w / w.sum() * len(w)

    def solve(wv: np.ndarray) -> np.ndarray:
        sw = np.sqrt(wv)[:, None]
        return np.linalg.lstsq(x * sw, y * np.sqrt(wv), rcond=None)[0]

    beta = solve(w)
    if robust:
        # One Huber reweighting pass: cap the influence of 2-MAD outliers.
        resid = y - x @ beta
        scale = 1.4826 * np.median(np.abs(resid - np.median(resid))) or resid.std() or 1.0
        w = w * np.clip(2.0 * scale / np.maximum(np.abs(resid), 1e-12), None, 1.0)
        beta = solve(w)

    fitted = x @ beta
    resid = y - fitted
    ss_res, ss_tot = float((resid**2).sum()), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    return (
        pd.Series(beta, index=exposures.columns),
        pd.Series(resid, index=idx),
        float(r2),
    )


def fit(
    returns: pd.DataFrame, exposures_by_date: dict[Any, pd.DataFrame],
    market_caps: pd.DataFrame | None = None,
) -> FactorModel:
    """Estimate factor returns period by period.

    ``exposures_by_date`` must map each date to exposures built from data
    knowable *before* that date's return. Getting this wrong is the classic
    way to build a factor model with a spectacular and entirely fictional
    information ratio.
    """
    frs, srs, r2s = {}, {}, {}
    for date in returns.index:
        x = exposures_by_date.get(date)
        if x is None or x.empty:
            continue
        caps = market_caps.loc[date] if market_caps is not None and date in market_caps.index else None
        try:
            fr, sr, r2 = cross_sectional_regression(returns.loc[date], x, caps)
        except ValueError:
            continue
        frs[date], srs[date], r2s[date] = fr, sr, r2

    if not frs:
        raise ValueError("no periods could be estimated -- check exposure alignment")

    fr_df = pd.DataFrame(frs).T.sort_index()
    sr_df = pd.DataFrame(srs).T.sort_index()
    last_date = max(exposures_by_date)
    return FactorModel(
        factor_returns=fr_df,
        exposures=exposures_by_date[last_date],
        specific_returns=sr_df,
        r_squared=pd.Series(r2s).sort_index(),
        diagnostics={
            "periods_estimated": len(frs),
            "periods_skipped": len(returns.index) - len(frs),
            "mean_r_squared": float(np.mean(list(r2s.values()))),
            "factors": list(fr_df.columns),
        },
    )


def fit_factor_covariance(
    model: FactorModel, lam: float = 0.97, min_specific_vol: float = 0.005
) -> FactorModel:
    """Attach an EWMA factor covariance and per-asset specific risk.

    A longer half-life (lam=0.97, ~23 days) than the asset-level default is
    intentional: factor returns are already diversified across hundreds of
    names, so their covariance is estimated far more precisely and does not
    need to react as fast.
    """
    from vyuha.risk.covariance import ewma_cov

    model.factor_cov = ewma_cov(model.factor_returns, lam=lam).matrix
    spec = model.specific_returns.std(ddof=1)
    model.specific_risk = spec.fillna(spec.median()).clip(lower=min_specific_vol)
    return model


def factor_summary(model: FactorModel) -> pd.DataFrame:
    """Annualised factor performance with t-statistics.

    A |t| below ~2 means that factor's return is not distinguishable from zero
    in your sample, and any risk attribution leaning on it is decoration.
    """
    fr = model.factor_returns
    n = len(fr)
    mean, sd = fr.mean(), fr.std(ddof=1)
    t = mean / (sd / np.sqrt(n))
    return pd.DataFrame({
        "ann_return": mean * 252,
        "ann_vol": sd * np.sqrt(252),
        "sharpe": (mean / sd) * np.sqrt(252),
        "t_stat": t,
        "p_value": 2 * (1 - stats.t.cdf(np.abs(t), df=n - 1)),
        "significant": np.abs(t) > 2.0,
        "n_periods": n,
    }).sort_values("t_stat", key=np.abs, ascending=False)
