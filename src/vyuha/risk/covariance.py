"""Covariance estimation.

For a portfolio of N assets with T observations, the sample covariance matrix
has N(N+1)/2 free parameters estimated from NT numbers. On the Nifty 500 with
two years of daily data that is 125,250 parameters from 252,000 observations --
the estimate is dominated by noise, and its smallest eigenvalues are biased
toward zero, which is exactly the direction an optimiser will lever into.

Everything here therefore produces a *shrunk*, provably positive-definite
estimate, and reports how much shrinkage was applied so the user can see how
much of the answer is data and how much is prior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.covariance import OAS, LedoitWolf

from vyuha.config import settings


@dataclass(slots=True)
class CovarianceEstimate:
    """A covariance matrix plus an honest account of how it was made."""

    matrix: pd.DataFrame
    method: str
    n_obs: int
    shrinkage: float | None = None
    effective_obs: float | None = None
    condition_number: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def vols(self) -> pd.Series:
        return pd.Series(np.sqrt(np.diag(self.matrix.values)), index=self.matrix.index)

    @property
    def correlation(self) -> pd.DataFrame:
        d = 1.0 / self.vols.replace(0.0, np.nan)
        return self.matrix.mul(d, axis=0).mul(d, axis=1)

    def portfolio_variance(self, weights: pd.Series) -> float:
        w = weights.reindex(self.matrix.index).fillna(0.0).values
        return float(w @ self.matrix.values @ w)

    def portfolio_vol(self, weights: pd.Series, annualise: bool = False) -> float:
        v = np.sqrt(max(self.portfolio_variance(weights), 0.0))
        return v * np.sqrt(settings.trading_days_per_year) if annualise else v

    def marginal_contribution(self, weights: pd.Series) -> pd.Series:
        """d(sigma_p)/d(w_i) -- how much portfolio vol moves per unit weight."""
        w = weights.reindex(self.matrix.index).fillna(0.0).values
        sigma_p = np.sqrt(max(w @ self.matrix.values @ w, 1e-300))
        return pd.Series((self.matrix.values @ w) / sigma_p, index=self.matrix.index)

    def risk_contribution(self, weights: pd.Series, normalise: bool = True) -> pd.Series:
        """w_i * d(sigma_p)/d(w_i) -- Euler decomposition, sums to sigma_p."""
        w = weights.reindex(self.matrix.index).fillna(0.0)
        rc = w * self.marginal_contribution(weights)
        return rc / rc.sum() if normalise else rc

    def summary(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "n_assets": len(self.matrix),
            "n_obs": self.n_obs,
            "shrinkage": self.shrinkage,
            "effective_obs": self.effective_obs,
            "condition_number": self.condition_number,
            **self.diagnostics,
        }


# --------------------------------------------------------------------- helpers


def nearest_psd(m: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """Project a symmetric matrix onto the PSD cone by eigenvalue clipping."""
    m = (m + m.T) / 2.0
    vals, vecs = np.linalg.eigh(m)
    if vals.min() >= epsilon:
        return m
    vals = np.clip(vals, epsilon, None)
    return (vecs * vals) @ vecs.T


def _prep(returns: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    r = returns.dropna(axis=1, how="all")
    r = r.fillna(0.0)
    if r.shape[0] < 2:
        raise ValueError(f"need >= 2 observations, got {r.shape[0]}")
    return r.values, list(r.columns)


def _finish(
    cov: np.ndarray, cols: list[str], method: str, n_obs: int, **kw: Any
) -> CovarianceEstimate:
    cov = nearest_psd(cov)
    cond = float(np.linalg.cond(cov)) if cov.shape[0] else np.nan
    return CovarianceEstimate(
        matrix=pd.DataFrame(cov, index=cols, columns=cols),
        method=method,
        n_obs=n_obs,
        condition_number=cond,
        **kw,
    )


# ------------------------------------------------------------------ estimators


def sample_cov(returns: pd.DataFrame) -> CovarianceEstimate:
    x, cols = _prep(returns)
    return _finish(np.cov(x, rowvar=False, ddof=1), cols, "sample", x.shape[0])


def ewma_cov(
    returns: pd.DataFrame, lam: float | None = None, min_periods: int = 20
) -> CovarianceEstimate:
    """RiskMetrics exponentially weighted covariance.

    Weights decay as lam^k going back in time, so the estimate responds to a
    regime break in weeks rather than the years a long equal-weighted window
    takes. lam=0.94 (the RiskMetrics daily default) implies a half-life of
    ~11 trading days and ~32 effective observations.
    """
    lam = settings.ewma_lambda if lam is None else lam
    if not 0 < lam < 1:
        raise ValueError("lam must be in (0, 1)")
    x, cols = _prep(returns)
    t = x.shape[0]
    if t < min_periods:
        raise ValueError(f"need >= {min_periods} observations, got {t}")

    # Most recent observation gets the largest weight.
    ages = np.arange(t - 1, -1, -1)
    w = (1 - lam) * lam**ages
    w /= w.sum()

    mu = w @ x
    xc = x - mu
    cov = (xc * w[:, None]).T @ xc
    eff = float(1.0 / np.sum(w**2))  # Kish effective sample size
    return _finish(
        cov, cols, f"ewma(lam={lam})", t,
        effective_obs=eff,
        diagnostics={"half_life_days": float(np.log(0.5) / np.log(lam))},
    )


def ledoit_wolf_cov(returns: pd.DataFrame) -> CovarianceEstimate:
    """Ledoit-Wolf shrinkage toward a scaled identity, with an analytically
    optimal intensity. The workhorse when N is large relative to T."""
    x, cols = _prep(returns)
    lw = LedoitWolf(assume_centered=False).fit(x)
    return _finish(
        lw.covariance_, cols, "ledoit_wolf", x.shape[0], shrinkage=float(lw.shrinkage_)
    )


def oas_cov(returns: pd.DataFrame) -> CovarianceEstimate:
    """Oracle Approximating Shrinkage -- tighter than Ledoit-Wolf when returns
    are close to Gaussian, worse when they are not. Indian small caps are not."""
    x, cols = _prep(returns)
    o = OAS(assume_centered=False).fit(x)
    return _finish(o.covariance_, cols, "oas", x.shape[0], shrinkage=float(o.shrinkage_))


def shrunk_ewma_cov(
    returns: pd.DataFrame, lam: float | None = None, shrinkage: float | None = None
) -> CovarianceEstimate:
    """EWMA correlations with Ledoit-Wolf-style shrinkage of the correlation
    matrix toward the equicorrelation target.

    This is the default estimator in Vyuha. EWMA gets the *level* of volatility
    right through a regime change; shrinking the *correlation* matrix stops the
    small eigenvalues from collapsing. Shrinking correlations rather than the
    full covariance preserves individual asset volatilities exactly, which
    matters because those are estimated far more reliably than co-movements.
    """
    ew = ewma_cov(returns, lam=lam)
    cov = ew.matrix.values
    n = cov.shape[0]
    if n < 2:
        return ew

    vols = np.sqrt(np.diag(cov))
    safe = np.where(vols > 0, vols, 1.0)
    corr = cov / np.outer(safe, safe)
    np.fill_diagonal(corr, 1.0)

    off = corr[~np.eye(n, dtype=bool)]
    rbar = float(off.mean())
    target = np.full((n, n), rbar)
    np.fill_diagonal(target, 1.0)

    if shrinkage is None:
        # Heuristic intensity: shrink harder when assets are many relative to
        # the effective number of independent observations.
        eff = ew.effective_obs or ew.n_obs
        shrinkage = float(np.clip(n / (n + eff), 0.05, 0.95))

    corr_s = shrinkage * target + (1 - shrinkage) * corr
    np.fill_diagonal(corr_s, 1.0)
    cov_s = corr_s * np.outer(vols, vols)

    return _finish(
        cov_s, list(ew.matrix.index), f"shrunk_ewma(lam={lam or settings.ewma_lambda})",
        ew.n_obs,
        shrinkage=shrinkage,
        effective_obs=ew.effective_obs,
        diagnostics={"mean_correlation": rbar, **ew.diagnostics},
    )


def estimate(returns: pd.DataFrame, method: str = "shrunk_ewma", **kw: Any) -> CovarianceEstimate:
    """Dispatch by name so config files can select an estimator."""
    table = {
        "sample": sample_cov,
        "ewma": ewma_cov,
        "ledoit_wolf": ledoit_wolf_cov,
        "oas": oas_cov,
        "shrunk_ewma": shrunk_ewma_cov,
    }
    if method not in table:
        raise ValueError(f"unknown method {method!r}; choose from {sorted(table)}")
    return table[method](returns, **kw)
