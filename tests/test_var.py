import numpy as np
import pandas as pd
import pytest

from vyuha.backtest.var_tests import backtest_var, christoffersen_independence, kupiec_pof
from vyuha.risk.var import (
    fit_garch11, var_ensemble, var_evt, var_filtered_historical, var_historical, var_parametric,
)


@pytest.fixture
def normal_returns():
    return pd.Series(np.random.default_rng(0).standard_normal(2000) * 0.01)


@pytest.fixture
def fat_tailed_returns():
    return pd.Series(np.random.default_rng(0).standard_t(3, 2000) * 0.008)


def test_historical_var_matches_empirical_quantile(normal_returns):
    r = var_historical(normal_returns, confidence=0.99)
    assert r.var == pytest.approx(-np.quantile(normal_returns, 0.01), rel=1e-9)


def test_es_always_exceeds_var(fat_tailed_returns):
    """Expected shortfall is a mean beyond the quantile, so it must be larger."""
    for fn in (var_historical, var_parametric, var_evt):
        r = fn(fat_tailed_returns, confidence=0.99)
        assert r.es > r.var, f"{r.method}: ES {r.es} <= VaR {r.var}"


def test_var_increases_with_confidence(normal_returns):
    lo = var_historical(normal_returns, confidence=0.95).var
    hi = var_historical(normal_returns, confidence=0.99).var
    assert hi > lo


def test_gaussian_var_understates_fat_tails(fat_tailed_returns):
    """The core reason Vyuha does not ship plain Gaussian VaR for Indian equities."""
    gauss = var_parametric(fat_tailed_returns, 0.99, cornish_fisher=False)
    hist = var_historical(fat_tailed_returns, 0.99)
    assert gauss.var < hist.var
    assert gauss.diagnostics["normality_rejected"] is True


def test_cornish_fisher_helps_for_mild_non_normality():
    """CF beats Gaussian where it is valid -- scored against the TRUE quantile.

    Scoring against the empirical sample quantile would be scoring one noisy
    estimator against another. Here the data-generating process is known, so
    the true 1% quantile of a scaled t(8) is available in closed form and both
    estimators can be measured against the right answer.
    """
    from scipy import stats as st

    scale, df_t = 0.008, 8
    mild = pd.Series(np.random.default_rng(0).standard_t(df_t, 20_000) * scale)
    true_var = -st.t.ppf(0.01, df_t) * scale

    res_cf = var_parametric(mild, 0.99, cornish_fisher=True)
    gauss = var_parametric(mild, 0.99, cornish_fisher=False).var

    assert res_cf.diagnostics["cf_rejected"] is False
    assert abs(res_cf.var - true_var) < abs(gauss - true_var), (
        f"CF err={abs(res_cf.var - true_var):.5f} vs Gaussian "
        f"err={abs(gauss - true_var):.5f}"
    )


def test_cornish_fisher_rejected_for_extreme_kurtosis(fat_tailed_returns):
    """t(3) has undefined kurtosis; CF breaks down and must NOT be applied.

    This is a real failure mode: unguarded, CF reports a VaR larger than the
    worst day ever observed. The system must detect it and fall back.
    """
    res = var_parametric(fat_tailed_returns, 0.99, cornish_fisher=True)
    assert res.diagnostics["cf_rejected"] is True
    assert res.method == "parametric_cf_rejected"
    assert res.diagnostics["prefer_evt_or_fhs"] is True
    assert res.diagnostics["z_adjusted"] == res.diagnostics["z_normal"]


def test_cornish_fisher_strict_mode_raises(fat_tailed_returns):
    with pytest.raises(ValueError, match="Cornish-Fisher rejected"):
        var_parametric(fat_tailed_returns, 0.99, cornish_fisher=True, strict=True)


def test_cornish_fisher_validity_boundary():
    from vyuha.risk.var import cornish_fisher_valid
    assert cornish_fisher_valid(skew=-0.3, excess_kurtosis=1.5)[0] is True
    assert cornish_fisher_valid(skew=-0.5, excess_kurtosis=25.0)[0] is False


def test_evt_detects_heavy_tail(fat_tailed_returns):
    assert var_evt(fat_tailed_returns, 0.99).diagnostics["xi_shape"] > 0


def test_evt_requires_enough_exceedances():
    with pytest.raises(ValueError, match="exceedances"):
        var_evt(pd.Series(np.random.default_rng(0).standard_normal(60) * 0.01),
                threshold_quantile=0.99)


def test_garch_recovers_persistence():
    """Simulate a known GARCH(1,1) and check the fit finds high persistence."""
    rng = np.random.default_rng(3)
    omega, alpha, beta = 1e-6, 0.09, 0.89
    n = 3000
    r, s2 = np.zeros(n), np.zeros(n)
    s2[0] = omega / (1 - alpha - beta)
    for t in range(1, n):
        r[t] = np.sqrt(s2[t - 1]) * rng.standard_normal()
        s2[t] = omega + alpha * r[t] ** 2 + beta * s2[t - 1]
    p = fit_garch11(r[1:])
    assert 0.90 < p["persistence"] < 1.0
    assert p["alpha"] > 0 and p["beta"] > 0


def test_filtered_historical_responds_to_recent_volatility():
    """FHS must report higher risk after a shock; unconditional HS cannot."""
    rng = np.random.default_rng(5)
    calm = rng.standard_normal(800) * 0.006
    storm = rng.standard_normal(40) * 0.03
    series = pd.Series(np.concatenate([calm, storm]))
    fhs = var_filtered_historical(series, 0.99)
    assert fhs.diagnostics["vol_ratio_vs_unconditional"] > 1.3
    assert fhs.var > var_historical(series, 0.99).var


def test_var_scales_with_horizon(normal_returns):
    one = var_historical(normal_returns, 0.99, horizon_days=1).var
    ten = var_historical(normal_returns, 0.99, horizon_days=10).var
    assert ten == pytest.approx(one * np.sqrt(10), rel=1e-9)


def test_ensemble_reports_every_method(normal_returns):
    df = var_ensemble(normal_returns, 0.99)
    assert len(df) == 5
    assert df["var"].notna().sum() >= 4
    assert np.isfinite(df.attrs["spread_ratio"])


def test_var_rejects_short_series():
    with pytest.raises(ValueError, match="30 observations"):
        var_historical(pd.Series([0.01] * 10))


# ------------------------------------------------------------- backtesting


def test_kupiec_accepts_correct_model():
    _, p = kupiec_pof(n=1000, x=10, p=0.01)
    assert p > 0.05


def test_kupiec_rejects_understated_risk():
    _, p = kupiec_pof(n=1000, x=50, p=0.01)
    assert p < 0.01


def test_christoffersen_detects_clustering():
    """20 exceptions all in a row must fail independence."""
    e = np.zeros(1000, int)
    e[500:520] = 1
    _, p = christoffersen_independence(e)
    assert p < 0.05


def test_christoffersen_accepts_scattered_exceptions():
    rng = np.random.default_rng(0)
    e = (rng.random(2000) < 0.01).astype(int)
    _, p = christoffersen_independence(e)
    assert p > 0.05


def test_backtest_flags_a_deliberately_bad_var():
    """A VaR set far too low must be rejected and land in the Basel red zone."""
    rng = np.random.default_rng(11)
    r = pd.Series(rng.standard_normal(1000) * 0.01)
    res = backtest_var(r, pd.Series(0.005, index=r.index), confidence=0.99)
    assert "REJECTED" in res.verdict
    assert res.basel_zone == "red"
    assert res.exception_rate > 0.05


def test_backtest_accepts_a_well_specified_var():
    rng = np.random.default_rng(12)
    r = pd.Series(rng.standard_normal(2000) * 0.01)
    true_var = -np.quantile(r, 0.01)
    res = backtest_var(r, pd.Series(true_var, index=r.index), confidence=0.99)
    assert res.basel_zone == "green"
    assert "not rejected" in res.verdict
