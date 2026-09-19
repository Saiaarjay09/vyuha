import numpy as np
import pandas as pd
import pytest

from vyuha.risk.covariance import (
    ewma_cov,
    ledoit_wolf_cov,
    nearest_psd,
    sample_cov,
    shrunk_ewma_cov,
)


@pytest.fixture
def returns():
    rng = np.random.default_rng(42)
    n, t = 6, 600
    factor = rng.standard_normal(t) * 0.012
    loadings = rng.uniform(0.6, 1.4, n)
    noise = rng.standard_normal((t, n)) * 0.008
    data = np.outer(factor, loadings) + noise
    return pd.DataFrame(data, columns=[f"A{i}" for i in range(n)],
                        index=pd.bdate_range("2022-01-03", periods=t))


def test_all_estimators_return_psd(returns):
    for est in (sample_cov, ewma_cov, ledoit_wolf_cov, shrunk_ewma_cov):
        cov = est(returns)
        eig = np.linalg.eigvalsh(cov.matrix.values)
        assert eig.min() >= -1e-10, f"{est.__name__} produced a non-PSD matrix"
        assert cov.matrix.shape == (6, 6)
        assert np.allclose(cov.matrix.values, cov.matrix.values.T)


def test_ewma_effective_obs_matches_theory(returns):
    """Kish effective sample size for EWMA weights is (1+lam)/(1-lam)."""
    lam = 0.94
    cov = ewma_cov(returns, lam=lam)
    assert cov.effective_obs == pytest.approx((1 + lam) / (1 - lam), rel=0.02)


def test_ewma_half_life(returns):
    cov = ewma_cov(returns, lam=0.94)
    assert cov.diagnostics["half_life_days"] == pytest.approx(11.2, abs=0.2)


def test_ewma_reacts_faster_than_sample():
    """A late volatility spike should move EWMA far more than the sample cov."""
    rng = np.random.default_rng(1)
    calm = rng.standard_normal((400, 2)) * 0.005
    storm = rng.standard_normal((30, 2)) * 0.05
    df = pd.DataFrame(np.vstack([calm, storm]), columns=["A", "B"])
    assert ewma_cov(df, lam=0.94).vols["A"] > sample_cov(df).vols["A"] * 1.5


def test_shrinkage_preserves_individual_vols(returns):
    """Shrinking correlations must leave asset volatilities untouched."""
    ew, sh = ewma_cov(returns), shrunk_ewma_cov(returns)
    np.testing.assert_allclose(ew.vols.values, sh.vols.values, rtol=1e-8)


def test_shrinkage_improves_conditioning_when_n_exceeds_t():
    """With more assets than observations the sample matrix is singular."""
    rng = np.random.default_rng(7)
    df = pd.DataFrame(rng.standard_normal((40, 60)) * 0.01)
    assert np.linalg.cond(ledoit_wolf_cov(df).matrix.values) < np.linalg.cond(
        np.cov(df.values, rowvar=False)
    )


def test_risk_contributions_sum_to_one(returns):
    cov = shrunk_ewma_cov(returns)
    w = pd.Series(1 / 6, index=returns.columns)
    assert cov.risk_contribution(w).sum() == pytest.approx(1.0)


def test_risk_contributions_euler_identity(returns):
    """Un-normalised risk contributions must sum to portfolio vol exactly."""
    cov = shrunk_ewma_cov(returns)
    w = pd.Series([0.3, 0.2, 0.2, 0.1, 0.1, 0.1], index=returns.columns)
    rc = cov.risk_contribution(w, normalise=False)
    assert rc.sum() == pytest.approx(cov.portfolio_vol(w), rel=1e-9)


def test_nearest_psd_repairs_indefinite_matrix():
    bad = np.array([[1.0, 0.99, 0.99], [0.99, 1.0, -0.99], [0.99, -0.99, 1.0]])
    assert np.linalg.eigvalsh(bad).min() < 0
    assert np.linalg.eigvalsh(nearest_psd(bad)).min() >= -1e-12


def test_rejects_too_few_observations():
    with pytest.raises(ValueError, match="observations"):
        ewma_cov(pd.DataFrame({"A": [0.01, 0.02], "B": [0.01, 0.0]}))


def test_lambda_out_of_range_rejected(returns):
    for bad in (0.0, 1.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="lam"):
            ewma_cov(returns, lam=bad)
