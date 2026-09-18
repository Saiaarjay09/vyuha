"""Value-at-Risk and Expected Shortfall.

Four estimators, because they disagree and the disagreement is informative:

  historical            no distributional assumption, but the tail is only as
                        rich as the worst day in the window
  parametric            closed form and smooth, but Gaussian VaR understates
                        Indian equity tails badly -- Nifty daily kurtosis runs
                        7-12 against the Gaussian 3. Cornish-Fisher corrects
                        part of that from sample skew/kurtosis
  filtered historical   GARCH-filter returns to i.i.d., bootstrap, re-inflate
                        by today's volatility. Handles volatility clustering,
                        which is the single largest effect in the data
  EVT (peaks-over-      fits a Generalised Pareto to exceedances, so it can
  threshold)            extrapolate *beyond* the worst observed day

Vyuha reports all four plus their spread. A wide spread means the tail is
genuinely not pinned down by the data, and that fact is the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import optimize, stats


@dataclass(slots=True)
class VaRResult:
    var: float           # positive number = loss magnitude
    es: float            # expected shortfall (conditional VaR)
    confidence: float
    horizon_days: int
    method: str
    n_obs: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"VaR({self.method}, {self.confidence:.1%}, {self.horizon_days}d) = "
            f"{self.var:.4%}  ES = {self.es:.4%}"
        )


def _scale(h: int) -> float:
    """Square-root-of-time. Valid only for i.i.d. returns; with volatility
    clustering and mean reversion it is an approximation, and it is recorded
    as such in diagnostics."""
    return float(np.sqrt(h))


def _clean(returns: pd.Series | np.ndarray) -> np.ndarray:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 30:
        raise ValueError(f"need >= 30 observations for VaR, got {r.size}")
    return r


# ---------------------------------------------------------------- historical


def var_historical(
    returns: pd.Series, confidence: float = 0.99, horizon_days: int = 1
) -> VaRResult:
    r = _clean(returns)
    q = np.quantile(r, 1 - confidence)
    tail = r[r <= q]
    es = float(tail.mean()) if tail.size else float(q)
    s = _scale(horizon_days)
    return VaRResult(
        var=float(-q * s), es=float(-es * s), confidence=confidence,
        horizon_days=horizon_days, method="historical", n_obs=r.size,
        diagnostics={
            "n_tail_obs": int(tail.size),
            "worst_observed": float(-r.min() * s),
            # With only this many tail points the quantile is itself uncertain.
            "tail_obs_warning": tail.size < 10,
        },
    )


def es_historical(returns: pd.Series, confidence: float = 0.975) -> float:
    r = _clean(returns)
    q = np.quantile(r, 1 - confidence)
    tail = r[r <= q]
    return float(-tail.mean()) if tail.size else float(-q)


# ---------------------------------------------------------------- parametric


def cornish_fisher_valid(skew: float, excess_kurtosis: float) -> tuple[bool, str]:
    """Is the Cornish-Fisher expansion trustworthy for these moments?

    CF is a 4th-order Edgeworth expansion around the normal. It improves on
    Gaussian VaR for *mild* non-normality, but it is an asymptotic series, not
    a convergent one: past a certain skew/kurtosis region the mapping
    z -> z_CF stops being monotonic, and the "corrected" quantile can be worse
    than the uncorrected one. Maillard (2012) characterises the valid domain.

    This matters concretely for Indian equities. Nifty daily excess kurtosis in
    a calm year sits around 3-5, where CF helps. In a crisis window, or for an
    illiquid small cap, it can exceed 10, where CF overshoots badly -- it will
    happily report a VaR *larger* than the worst day ever observed.

    We check monotonicity numerically over the quantile range we care about,
    which is exact rather than relying on a tabulated boundary.
    """
    zs = np.linspace(-4.0, -1.0, 200)
    cf = (
        zs
        + (zs**2 - 1) * skew / 6
        + (zs**3 - 3 * zs) * excess_kurtosis / 24
        - (2 * zs**3 - 5 * zs) * skew**2 / 36
    )
    if np.any(np.diff(cf) <= 0):
        return False, (
            f"Cornish-Fisher is non-monotonic for skew={skew:.2f}, "
            f"excess kurtosis={excess_kurtosis:.2f}; the expansion has broken down"
        )
    if excess_kurtosis > 7.0:
        return False, (
            f"excess kurtosis {excess_kurtosis:.2f} is beyond the range where the "
            "4th-order expansion is reliable"
        )
    return True, ""


def var_parametric(
    returns: pd.Series,
    confidence: float = 0.99,
    horizon_days: int = 1,
    cornish_fisher: bool = True,
    strict: bool = False,
) -> VaRResult:
    """Parametric VaR, optionally with a Cornish-Fisher tail correction.

    When CF is requested but the sample moments fall outside its valid domain,
    the correction is **not silently applied**. With ``strict=False`` (default)
    we fall back to the Gaussian quantile and set ``cf_rejected`` in the
    diagnostics; with ``strict=True`` we raise. Returning a number that looks
    more sophisticated but is further from the truth is the worst option, so it
    is not one of them.
    """
    r = _clean(returns)
    mu, sigma = float(r.mean()), float(r.std(ddof=1))
    skew, kurt = float(stats.skew(r)), float(stats.kurtosis(r))  # excess kurtosis
    z = stats.norm.ppf(1 - confidence)

    cf_rejected, cf_reason = False, ""
    if cornish_fisher:
        valid, reason = cornish_fisher_valid(skew, kurt)
        if valid:
            z_cf = (
                z
                + (z**2 - 1) * skew / 6
                + (z**3 - 3 * z) * kurt / 24
                - (2 * z**3 - 5 * z) * skew**2 / 36
            )
        else:
            if strict:
                raise ValueError(f"Cornish-Fisher rejected: {reason}")
            cf_rejected, cf_reason = True, reason
            z_cf = z
    else:
        z_cf = z

    s = _scale(horizon_days)
    var = -(mu + z_cf * sigma) * s
    es_gauss = -(mu - sigma * stats.norm.pdf(z) / (1 - confidence))
    es = es_gauss * (abs(z_cf) / abs(z) if z else 1.0) * s

    jb_stat, jb_p = stats.jarque_bera(r)
    method = "parametric_normal"
    if cornish_fisher:
        method = "parametric_cf_rejected" if cf_rejected else "parametric_cf"

    return VaRResult(
        var=float(var), es=float(es), confidence=confidence, horizon_days=horizon_days,
        method=method, n_obs=r.size,
        diagnostics={
            "mu": mu, "sigma": sigma, "skew": skew, "excess_kurtosis": kurt,
            "z_normal": float(z), "z_adjusted": float(z_cf),
            "jarque_bera_p": float(jb_p),
            "normality_rejected": bool(jb_p < 0.05),
            "cf_rejected": cf_rejected,
            "cf_rejection_reason": cf_reason,
            # When CF is rejected the tail is heavier than any parametric form
            # here can express -- EVT or FHS is the estimator to trust.
            "prefer_evt_or_fhs": cf_rejected,
        },
    )


# ------------------------------------------------------------------- GARCH


def fit_garch11(r: np.ndarray) -> dict[str, float]:
    """Maximum-likelihood GARCH(1,1) with Gaussian innovations.

    sigma2_t = omega + alpha * eps_{t-1}^2 + beta * sigma2_{t-1}

    Implemented directly rather than pulling in `arch` to keep the dependency
    surface small. alpha+beta is the volatility persistence -- for the Nifty it
    typically sits around 0.97-0.99, i.e. shocks decay over months, not days.
    """
    r = r - r.mean()
    var0 = float(np.var(r, ddof=1))
    if var0 <= 0:
        raise ValueError("zero variance series")

    def neg_ll(p: np.ndarray) -> float:
        omega, alpha, beta = np.exp(p)  # positivity by construction
        if alpha + beta >= 0.9999:
            return 1e10
        s2 = np.empty(r.size)
        s2[0] = var0
        for t in range(1, r.size):
            s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        if not np.all(np.isfinite(s2)) or np.any(s2 <= 0):
            return 1e10
        return float(0.5 * np.sum(np.log(s2) + r**2 / s2))

    x0 = np.log([var0 * 0.05, 0.08, 0.90])
    res = optimize.minimize(neg_ll, x0, method="Nelder-Mead",
                            options={"maxiter": 2000, "xatol": 1e-8, "fatol": 1e-8})
    omega, alpha, beta = np.exp(res.x)
    return {
        "omega": float(omega), "alpha": float(alpha), "beta": float(beta),
        "persistence": float(alpha + beta),
        "long_run_vol": float(np.sqrt(omega / max(1 - alpha - beta, 1e-12))),
        "converged": bool(res.success),
        "loglik": float(-res.fun),
    }


def garch_sigma_path(r: np.ndarray, params: dict[str, float]) -> np.ndarray:
    r = r - r.mean()
    omega, alpha, beta = params["omega"], params["alpha"], params["beta"]
    s2 = np.empty(r.size + 1)
    s2[0] = float(np.var(r, ddof=1))
    for t in range(1, r.size + 1):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
    return np.sqrt(s2)


def var_filtered_historical(
    returns: pd.Series,
    confidence: float = 0.99,
    horizon_days: int = 1,
    n_sims: int = 20_000,
    seed: int = 7,
) -> VaRResult:
    """Filtered Historical Simulation (Barone-Adesi / Hull-White).

    Standardise returns by their GARCH conditional volatility, giving residuals
    that are close to i.i.d. but keep the empirical fat tails. Bootstrap those,
    re-inflate by the *current* conditional volatility, and accumulate over the
    horizon. This is the estimator that correctly says "risk is high today
    because yesterday was violent" -- unconditional historical VaR cannot.
    """
    r = _clean(returns)
    params = fit_garch11(r)
    sigma = garch_sigma_path(r, params)
    resid = (r - r.mean()) / sigma[:-1]
    resid = resid[np.isfinite(resid)]
    sigma_now = float(sigma[-1])

    rng = np.random.default_rng(seed)
    omega, alpha, beta = params["omega"], params["alpha"], params["beta"]

    draws = rng.choice(resid, size=(n_sims, horizon_days), replace=True)
    s2 = np.full(n_sims, sigma_now**2)
    total = np.zeros(n_sims)
    for h in range(horizon_days):
        shock = np.sqrt(s2) * draws[:, h]
        total += shock
        s2 = omega + alpha * shock**2 + beta * s2  # let vol evolve over the horizon

    q = float(np.quantile(total, 1 - confidence))
    tail = total[total <= q]
    return VaRResult(
        var=float(-q), es=float(-tail.mean()) if tail.size else float(-q),
        confidence=confidence, horizon_days=horizon_days,
        method="filtered_historical", n_obs=r.size,
        diagnostics={
            **params,
            "current_vol_daily": sigma_now,
            "unconditional_vol_daily": float(r.std(ddof=1)),
            # >1 means today is riskier than the average day in the sample.
            "vol_ratio_vs_unconditional": sigma_now / float(r.std(ddof=1)),
            "n_sims": n_sims,
        },
    )


# ---------------------------------------------------------------------- EVT


def var_evt(
    returns: pd.Series,
    confidence: float = 0.99,
    horizon_days: int = 1,
    threshold_quantile: float = 0.95,
) -> VaRResult:
    """Extreme Value Theory, peaks-over-threshold with a Generalised Pareto fit.

    The only estimator here that can produce a loss larger than anything in the
    sample. The shape parameter xi is the headline number: xi > 0 means a heavy
    (power-law) tail, and xi >= 0.5 means infinite variance, at which point
    every volatility-based risk number in the system is on thin ice.
    """
    r = _clean(returns)
    losses = -r
    u = float(np.quantile(losses, threshold_quantile))
    exceed = losses[losses > u] - u
    if exceed.size < 20:
        raise ValueError(
            f"only {exceed.size} exceedances above the {threshold_quantile:.0%} "
            "threshold; EVT needs >= 20. Use a longer window or lower threshold."
        )

    xi, _, beta = stats.genpareto.fit(exceed, floc=0)
    nu, n = exceed.size, losses.size
    p = 1 - confidence

    if abs(xi) < 1e-8:
        var = u + beta * np.log((nu / n) / p)
    else:
        var = u + (beta / xi) * (((n / nu) * p) ** (-xi) - 1)

    es = (var + beta - xi * u) / (1 - xi) if xi < 1 else np.inf

    s = _scale(horizon_days)
    return VaRResult(
        var=float(var * s), es=float(es * s), confidence=confidence,
        horizon_days=horizon_days, method="evt_pot", n_obs=r.size,
        diagnostics={
            "xi_shape": float(xi), "beta_scale": float(beta), "threshold": u,
            "n_exceedances": int(nu),
            "heavy_tailed": bool(xi > 0),
            "infinite_variance": bool(xi >= 0.5),
            "infinite_mean": bool(xi >= 1.0),
        },
    )


# ------------------------------------------------------------------ ensemble


def var_ensemble(
    returns: pd.Series, confidence: float = 0.99, horizon_days: int = 1
) -> pd.DataFrame:
    """Run every estimator and lay the disagreement out on the table.

    The ``spread_ratio`` at the bottom is the point: when the most and least
    conservative estimators differ by 2x, no single VaR number is defensible,
    and the honest output is the range.
    """
    runs: dict[str, VaRResult] = {}
    for name, fn, kw in [
        ("historical", var_historical, {}),
        ("parametric_normal", var_parametric, {"cornish_fisher": False}),
        ("parametric_cf", var_parametric, {"cornish_fisher": True}),
        ("filtered_historical", var_filtered_historical, {}),
        ("evt_pot", var_evt, {}),
    ]:
        try:
            runs[name] = fn(returns, confidence=confidence, horizon_days=horizon_days, **kw)
        except Exception as exc:  # noqa: BLE001 - surfaced in the table, not hidden
            runs[name] = VaRResult(np.nan, np.nan, confidence, horizon_days,
                                   name, 0, {"error": str(exc)})

    df = pd.DataFrame(
        {n: {"var": v.var, "es": v.es, "n_obs": v.n_obs,
             "error": v.diagnostics.get("error", "")} for n, v in runs.items()}
    ).T
    vals = df["var"].astype(float).dropna()
    df.attrs["spread_ratio"] = float(vals.max() / vals.min()) if len(vals) > 1 and vals.min() > 0 else np.nan
    df.attrs["results"] = runs
    return df
