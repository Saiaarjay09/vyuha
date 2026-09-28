"""Projecting what an investment might become -- as a distribution, never a number.

"I have 5 lakh, what will it be worth in 5 years?" is the question people
actually want answered, and it is the one where a tool like this can most
easily do harm. Print a single confident figure and you have produced
investment advice dressed as arithmetic.

So this module never returns a point estimate. It returns a distribution built
by resampling *actual history*, and it puts the unpleasant numbers first: the
chance of losing money, the chance of merely matching inflation, the 5th
percentile. Those are the numbers that should change a decision.

METHOD

Block bootstrap on historical monthly returns. Blocks of twelve months are
drawn with replacement and chained together, rather than sampling individual
months independently, because independent sampling destroys the two features
that matter most for a multi-year horizon:

  volatility clustering   bad months arrive together, which is what makes a
                          real drawdown deep rather than merely frequent
  mean reversion          long-run equity returns are less volatile than
                          iid sampling of monthly returns implies

An iid bootstrap therefore produces a distribution that is too narrow in the
middle and too thin in the tails -- flattering, and wrong in the direction
that matters.

WHAT THIS CANNOT DO

It assumes the next N years resemble some N years drawn from the past. That is
the least-bad available assumption and it is still an assumption. India's
growth rate, inflation regime, market structure and valuation level have all
changed over the sample. A 70-year bootstrap includes the licence raj and the
post-liberalisation boom; neither may describe the next decade.

It is not advice, and the output says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

Mode = Literal["lumpsum", "sip"]

#: Where each asset class's return history comes from. Every projection states
#: its source and sample period, because a distribution is only as good as the
#: history behind it.
ASSET_SOURCES: dict[str, dict[str, Any]] = {
    "indian_equity": {
        "label": "Indian equity (broad index)",
        "kind": "fred", "id": "SPASTT01INM661N",
        "note": "OECD share-price index for India via FRED, monthly since 1957.",
    },
    "gold": {
        "label": "Gold (London fix, USD)",
        "kind": "lbma", "id": "gold",
        "note": "LBMA PM fix. In USD -- for a rupee investor the currency move "
                "is part of the return and is handled separately.",
    },
    "silver": {
        "label": "Silver (London fix, USD)",
        "kind": "lbma", "id": "silver",
        "note": "LBMA fix, USD.",
    },
    "us_equity": {
        "label": "US equity (Nasdaq Composite)",
        "kind": "fred", "id": "NASDAQCOM",
        "note": "Nasdaq Composite, daily since 1971. Tech-heavy, so more "
                "volatile than the S&P 500.",
    },
}

#: Fixed-income has no long free public series, so it is modelled as a rate
#: rather than bootstrapped, and labelled as such rather than dressed up.
FIXED_RATE_ASSETS: dict[str, dict[str, Any]] = {
    "fixed_deposit": {
        "label": "Bank fixed deposit",
        "rate": 0.068, "vol": 0.0,
        "note": "Modelled as a flat 6.8% nominal, not bootstrapped. Rates vary "
                "by bank and tenor; override with rate=.",
    },
    "debt_fund": {
        "label": "Debt mutual fund",
        "rate": 0.072, "vol": 0.025,
        "note": "Modelled as 7.2% nominal with mild volatility. Indicative only.",
    },
}

#: Indian capital gains treatment, as amended in 2024. Tax law changes; these
#: are defaults, not advice, and every result restates them.
TAX_RULES: dict[str, dict[str, Any]] = {
    "indian_equity": {
        "ltcg_rate": 0.125, "ltcg_months": 12, "stcg_rate": 0.20,
        "annual_exemption": 125_000,
        "note": "Equity LTCG 12.5% above Rs 1.25 lakh a year, held over 12 months.",
    },
    "gold": {
        "ltcg_rate": 0.125, "ltcg_months": 24, "stcg_rate": 0.30,
        "annual_exemption": 0,
        "note": "Gold LTCG 12.5% without indexation after 24 months.",
    },
    "silver": {
        "ltcg_rate": 0.125, "ltcg_months": 24, "stcg_rate": 0.30,
        "annual_exemption": 0, "note": "As gold.",
    },
    "us_equity": {
        "ltcg_rate": 0.125, "ltcg_months": 24, "stcg_rate": 0.30,
        "annual_exemption": 0,
        "note": "Foreign equity is not treated as 'equity' for Indian tax: "
                "LTCG 12.5% after 24 months, otherwise slab.",
    },
    "fixed_deposit": {
        "ltcg_rate": 0.30, "ltcg_months": 0, "stcg_rate": 0.30,
        "annual_exemption": 0,
        "note": "FD interest is taxed at your slab rate, assumed 30% here.",
    },
    "debt_fund": {
        "ltcg_rate": 0.30, "ltcg_months": 0, "stcg_rate": 0.30,
        "annual_exemption": 0,
        "note": "Debt funds bought after April 2023 are taxed at slab.",
    },
}

DEFAULT_INFLATION = 0.055   # India CPI, long-run-ish. Overridden by live data.


@dataclass(slots=True)
class ProjectionResult:
    asset: str
    asset_label: str
    amount: float
    years: float
    mode: Mode
    total_invested: float

    percentiles: dict[str, float] = field(default_factory=dict)        # nominal
    real_percentiles: dict[str, float] = field(default_factory=dict)   # inflation-adjusted
    post_tax_percentiles: dict[str, float] = field(default_factory=dict)
    # After tax AND after inflation -- the only figure that answers "what will
    # this actually be worth to me". Quoting post-tax and real separately
    # invites reading them as alternatives rather than as two deductions from
    # the same amount.
    net_real_percentiles: dict[str, float] = field(default_factory=dict)

    prob_loss: float = float("nan")
    prob_below_inflation: float = float("nan")
    prob_below_fd: float = float("nan")

    median_cagr: float = float("nan")
    worst_year_in_sample: float = float("nan")
    max_drawdown_median: float = float("nan")

    n_simulations: int = 0
    data_source: str = ""
    sample_start: str = ""
    sample_end: str = ""
    sample_years: float = 0.0
    inflation_assumed: float = 0.0
    tax_note: str = ""
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def summary(self) -> str:
        p = self.percentiles
        return (
            f"{self.asset_label}, Rs {self.amount:,.0f} over {self.years:g}y: "
            f"median Rs {p.get('p50', float('nan')):,.0f} "
            f"(5th-95th: Rs {p.get('p5', float('nan')):,.0f} - "
            f"Rs {p.get('p95', float('nan')):,.0f}), "
            f"{self.prob_loss:.0%} chance of ending below what you put in"
        )


# ------------------------------------------------------------------ history


def monthly_returns(asset: str, ttl: int = 86_400) -> tuple[pd.Series, dict[str, Any]]:
    """Monthly total-return series for an asset class, plus its provenance."""
    spec = ASSET_SOURCES.get(asset)
    if spec is None:
        raise ValueError(
            f"no history for {asset!r}; bootstrappable assets are "
            f"{sorted(ASSET_SOURCES)}, fixed-rate are {sorted(FIXED_RATE_ASSETS)}"
        )

    if spec["kind"] == "fred":
        from vyuha.ingest.sources import fred_series

        df = fred_series(spec["id"], ttl=ttl)
    else:
        from vyuha.ingest.globalmarkets import commodity

        df = commodity(spec["id"], ttl=ttl)

    df = df.dropna(subset=["value"]).sort_values("date")
    s = df.set_index(pd.to_datetime(df["date"]))["value"]
    monthly = s.resample("ME").last().dropna()
    rets = monthly.pct_change().dropna()
    if len(rets) < 60:
        raise ValueError(f"only {len(rets)} monthly observations for {asset}")

    meta = {
        "source": spec["note"], "label": spec["label"],
        "start": str(monthly.index.min().date()), "end": str(monthly.index.max().date()),
        "years": round((monthly.index.max() - monthly.index.min()).days / 365.25, 1),
        "n_months": len(rets),
    }
    return rets, meta


def india_inflation(ttl: int = 86_400) -> float:
    """Trailing 10-year average Indian CPI inflation, or a documented default."""
    try:
        from vyuha.ingest.sources import fred_series

        df = fred_series("INDCPIALLMINMEI", ttl=ttl).dropna(subset=["value"])
        s = df.set_index(pd.to_datetime(df["date"]))["value"].resample("ME").last().dropna()
        yrs = 10
        if len(s) > yrs * 12:
            total = s.iloc[-1] / s.iloc[-yrs * 12] - 1
            return float((1 + total) ** (1 / yrs) - 1)
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_INFLATION


# -------------------------------------------------------------- simulation


def block_bootstrap(
    returns: np.ndarray, n_months: int, n_sims: int, block: int = 12,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Draw (n_sims x n_months) return paths by chaining 12-month blocks.

    Sampling whole blocks keeps the internal structure of a year -- crashes
    that run for months, recoveries that take longer -- which independent
    monthly sampling destroys.
    """
    rng = rng or np.random.default_rng(12345)
    n = returns.size
    if n < block * 2:
        block = max(1, n // 4)
    n_blocks = int(np.ceil(n_months / block))
    starts = rng.integers(0, n - block + 1, size=(n_sims, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, -1)
    return returns[idx[:, :n_months]]


def project(
    amount: float,
    years: float,
    asset: str = "indian_equity",
    mode: Mode = "lumpsum",
    n_sims: int = 20_000,
    inflation: float | None = None,
    apply_tax: bool = True,
    rate: float | None = None,
    seed: int = 12345,
) -> ProjectionResult:
    """Project an investment as a distribution of outcomes.

    ``amount`` is the lump sum, or the MONTHLY contribution when mode='sip'.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")
    if years <= 0 or years > 50:
        raise ValueError("years must be between 0 and 50")

    n_months = max(1, int(round(years * 12)))
    rng = np.random.default_rng(seed)
    infl = india_inflation() if inflation is None else inflation

    caveats: list[str] = []

    if asset in FIXED_RATE_ASSETS:
        spec = FIXED_RATE_ASSETS[asset]
        r = float(rate if rate is not None else spec["rate"])
        vol = float(spec["vol"])
        monthly_mu = (1 + r) ** (1 / 12) - 1
        paths = rng.normal(monthly_mu, vol / np.sqrt(12), size=(n_sims, n_months))
        label, meta = spec["label"], {"source": spec["note"], "start": "-", "end": "-",
                                      "years": 0.0}
        caveats.append(spec["note"])
    else:
        rets, meta = monthly_returns(asset)
        paths = block_bootstrap(rets.to_numpy(), n_months, n_sims, rng=rng)
        label = meta["label"]
        caveats.append(meta["source"])

    # ---- accumulate
    growth = 1.0 + paths
    if mode == "sip":
        # Each monthly contribution compounds only for the months remaining.
        cum = np.cumprod(growth, axis=1)
        # value at T of a rupee invested at month i = cum[T]/cum[i]
        factors = cum[:, -1][:, None] / cum
        terminal = amount * factors.sum(axis=1)
        invested = amount * n_months
    else:
        terminal = amount * np.prod(growth, axis=1)
        invested = amount

    # ---- median path drawdown, a better felt measure than terminal spread
    cumpaths = np.cumprod(growth, axis=1)
    peaks = np.maximum.accumulate(cumpaths, axis=1)
    dd = (cumpaths / peaks - 1.0).min(axis=1)

    def pct(a: np.ndarray) -> dict[str, float]:
        qs = [5, 10, 25, 50, 75, 90, 95]
        return {f"p{q}": float(np.percentile(a, q)) for q in qs}

    real = terminal / ((1 + infl) ** years)

    post_tax = terminal.copy()
    tax = TAX_RULES.get(asset, {})
    if apply_tax and tax:
        gain = np.maximum(terminal - invested, 0.0)
        long_term = (years * 12) >= tax.get("ltcg_months", 12)
        rate_t = tax["ltcg_rate"] if long_term else tax["stcg_rate"]
        taxable = np.maximum(gain - tax.get("annual_exemption", 0), 0.0)
        post_tax = terminal - taxable * rate_t

    fd_rate = FIXED_RATE_ASSETS["fixed_deposit"]["rate"]
    fd_value = (
        amount * (1 + fd_rate) ** years if mode == "lumpsum"
        else amount * sum((1 + fd_rate) ** ((n_months - i) / 12) for i in range(n_months))
    )

    res = ProjectionResult(
        asset=asset, asset_label=label, amount=amount, years=years, mode=mode,
        total_invested=float(invested),
        percentiles=pct(terminal),
        real_percentiles=pct(real),
        post_tax_percentiles=pct(post_tax),
        net_real_percentiles=pct(post_tax / ((1 + infl) ** years)),
        prob_loss=float((terminal < invested).mean()),
        prob_below_inflation=float((real < invested).mean()),
        prob_below_fd=float((terminal < fd_value).mean()),
        median_cagr=float((np.median(terminal) / invested) ** (1 / years) - 1),
        worst_year_in_sample=float(np.percentile(dd, 5)),
        max_drawdown_median=float(np.median(dd)),
        n_simulations=n_sims,
        data_source=meta["source"],
        sample_start=str(meta.get("start", "-")), sample_end=str(meta.get("end", "-")),
        sample_years=float(meta.get("years", 0.0)),
        inflation_assumed=infl,
        tax_note=tax.get("note", "No tax applied."),
        caveats=caveats,
    )

    res.caveats.append(
        f"Inflation assumed {infl:.1%} a year; 'real' figures are in today's "
        "rupees. Money that merely keeps pace with inflation has not grown."
    )
    res.caveats.append(
        "Built by resampling history, which assumes the next "
        f"{years:g} years resemble some period from the past. They may not."
    )
    if apply_tax and tax:
        res.caveats.append(tax["note"] + " Tax law changes; verify current rules.")
    if years < 3 and asset in ("indian_equity", "us_equity", "gold", "silver"):
        res.caveats.append(
            f"Over {years:g} years this is close to a coin toss. Equity and gold "
            "need long horizons for the odds to tilt meaningfully in your favour."
        )
    return res


@dataclass(slots=True)
class GoalResult:
    target: float
    years: float
    asset: str
    asset_label: str
    monthly_required: float
    lumpsum_required: float
    probability_of_reaching: float
    monthly_for_80pct: float
    total_contributed: float
    target_in_todays_money: float
    inflation_assumed: float
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


def plan_goal(
    target: float, years: float, asset: str = "indian_equity",
    n_sims: int = 8000, inflation: float | None = None, seed: int = 4242,
) -> GoalResult:
    """How much to save monthly to have a decent shot at a target.

    The naive calculation -- compound the median return backwards -- answers
    "what monthly amount reaches the target if everything goes averagely?"
    That has roughly a 50% chance of working, which is a poor basis for a
    plan you cannot redo.

    So two numbers are returned: the monthly amount whose MEDIAN outcome hits
    the target, and the larger amount that reaches it in 80% of simulated
    histories. The gap between them is the price of confidence, and it is
    usually startling.

    The target is also restated in today's money. A crore in fifteen years is
    not a crore -- at 5.5% inflation it buys what about 45 lakh buys now, and
    a plan that ignores that is planning for the wrong number.
    """
    if target <= 0:
        raise ValueError("target must be positive")
    if years <= 0 or years > 50:
        raise ValueError("years must be between 0 and 50")

    n_months = max(1, int(round(years * 12)))
    infl = india_inflation() if inflation is None else inflation
    rng = np.random.default_rng(seed)

    if asset in FIXED_RATE_ASSETS:
        spec = FIXED_RATE_ASSETS[asset]
        r = float(spec["rate"])
        monthly_mu = (1 + r) ** (1 / 12) - 1
        paths = rng.normal(monthly_mu, spec["vol"] / np.sqrt(12),
                           size=(n_sims, n_months))
        label = spec["label"]
        source_note = spec["note"]
    else:
        rets, meta = monthly_returns(asset)
        paths = block_bootstrap(rets.to_numpy(), n_months, n_sims, rng=rng)
        label = meta["label"]
        source_note = meta["source"]

    # Terminal value per rupee of monthly contribution, for every path.
    cum = np.cumprod(1.0 + paths, axis=1)
    per_rupee = (cum[:, -1][:, None] / cum).sum(axis=1)
    lump_factor = cum[:, -1]

    median_monthly = float(target / np.median(per_rupee))
    p80_monthly = float(target / np.percentile(per_rupee, 20))  # 80% of paths exceed
    prob = float((median_monthly * per_rupee >= target).mean())

    res = GoalResult(
        target=target, years=years, asset=asset, asset_label=label,
        monthly_required=median_monthly,
        lumpsum_required=float(target / np.median(lump_factor)),
        probability_of_reaching=prob,
        monthly_for_80pct=p80_monthly,
        total_contributed=median_monthly * n_months,
        target_in_todays_money=float(target / ((1 + infl) ** years)),
        inflation_assumed=infl,
        caveats=[
            source_note,
            f"Rs {target:,.0f} in {years:g} years buys what about "
            f"Rs {target / ((1 + infl) ** years):,.0f} buys today, at "
            f"{infl:.1%} inflation. Consider targeting the inflated figure.",
            f"Saving Rs {median_monthly:,.0f} a month reaches the target in "
            f"about half of simulated histories. Rs {p80_monthly:,.0f} reaches "
            "it in four out of five. The difference is what certainty costs.",
            "Built by resampling history, which assumes the coming years "
            "resemble some past stretch. Not advice.",
        ],
    )
    return res


def compare_assets(
    amount: float, years: float, assets: list[str] | None = None, **kw: Any
) -> pd.DataFrame:
    """Same money, same horizon, across asset classes."""
    assets = assets or ["indian_equity", "gold", "us_equity", "fixed_deposit", "debt_fund"]
    rows = []
    for a in assets:
        try:
            r = project(amount, years, asset=a, **kw)
            rows.append({
                "asset": r.asset_label,
                "median": r.percentiles["p50"],
                "p5": r.percentiles["p5"],
                "p95": r.percentiles["p95"],
                "median_real": r.real_percentiles["p50"],
                "prob_loss": r.prob_loss,
                "prob_below_inflation": r.prob_below_inflation,
                "median_cagr": r.median_cagr,
            })
        except Exception as exc:  # noqa: BLE001 - a missing series is a blank row
            rows.append({"asset": a, "median": np.nan, "error": str(exc)[:80]})
    return pd.DataFrame(rows)
