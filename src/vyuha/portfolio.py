"""Your actual holdings, run through the risk engine.

Vyuha had a covariance estimator, four VaR models, a factor model, a liquidity
module and nine stress scenarios -- about 1,100 lines of working risk code --
and none of it could be reached from the interface. The one stress test that
was reachable ran on a hard-coded sample portfolio, which tells you nothing
about your own.

This connects them. You describe what you hold in plain English and get
concentration, stress losses, and how long an exit would take.

WHAT IT CANNOT SEE, AND SAYS SO

There is no per-stock data wired: no bhavcopy, and Yahoo blocks this host. So
individual shares cannot be priced, and their betas and volatilities are not
known. Holdings are instead classified into buckets -- large cap, mid and
small cap, gold, debt, international -- and the bucket's characteristics are
applied.

That is a real approximation and it is stated on every result. A concentrated
position in one mid-cap is far riskier than the mid-cap bucket average, and
this will not tell you that. What it does tell you honestly is how exposed you
are by asset class, what history suggests that exposure costs in a crisis, and
whether you could get out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

#: Bucket characteristics. Betas and liquidity are typical values for the
#: segment, taken from the stress module's calibration -- not from your
#: specific holdings, which cannot be priced here.
BUCKETS: dict[str, dict[str, Any]] = {
    "large_cap": {
        "label": "Large-cap Indian equity", "beta": 0.95, "vol": 0.16,
        "cap_segment": "large", "adv_inr": 2_000_000_000,
        "note": "Nifty 50 type names. Deep liquidity, high correlation to the index.",
    },
    "mid_small_cap": {
        "label": "Mid & small-cap Indian equity", "beta": 1.35, "vol": 0.24,
        "cap_segment": "mid", "adv_inr": 80_000_000,
        "note": "Fell roughly three times as far as large caps in the IL&FS episode.",
    },
    "index_fund": {
        "label": "Index fund / ETF", "beta": 1.00, "vol": 0.16,
        "cap_segment": "large", "adv_inr": 500_000_000,
        "note": "Tracks the index; no stock-specific risk.",
    },
    "gold": {
        "label": "Gold", "beta": -0.05, "vol": 0.15,
        "cap_segment": "large", "adv_inr": 1_000_000_000,
        "note": "Usually rises when equities fall, which is the point of holding it.",
    },
    "debt": {
        "label": "Debt / fixed deposit / bonds", "beta": 0.05, "vol": 0.04,
        "cap_segment": "large", "adv_inr": 500_000_000, "duration": 3.5,
        "note": "Main risk is interest rates, not the equity market.",
    },
    "international": {
        "label": "International equity", "beta": 0.75, "vol": 0.18,
        "cap_segment": "large", "adv_inr": 1_000_000_000,
        "note": "Adds currency exposure: your return is the asset's move AND the rupee's.",
    },
    "cash": {
        "label": "Cash", "beta": 0.0, "vol": 0.0,
        "cap_segment": "large", "adv_inr": 10_000_000_000,
        "note": "No market risk; loses to inflation.",
    },
}

#: Enough well-known names to classify a typical retail holding. Not a
#: universe: anything unrecognised falls back to large cap and is FLAGGED, so
#: a wrong guess is visible rather than silent.
_LARGE_CAPS = (
    "reliance", "tcs", "hdfc", "infosys", "infy", "icici", "sbi", "state bank",
    "bharti", "airtel", "itc", "kotak", "axis", "lt", "larsen", "bajaj",
    "asian paint", "maruti", "sun pharma", "titan", "ultratech", "wipro",
    "nestle", "hul", "hindustan unilever", "adani", "ntpc", "ongc", "powergrid",
    "coal india", "tata steel", "tata motors", "jsw", "grasim", "cipla",
    "dr reddy", "britannia", "eicher", "hero", "divis", "hcl", "tech mahindra",
    "indusind", "bpcl", "ioc", "sbi life", "hdfc life", "apollo", "shriram",
)
_BUCKET_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gold", ("gold", "sgb", "sovereign gold", "gold etf", "goldbees", "silver")),
    ("debt", ("fd", "fixed deposit", "debt", "bond", "ppf", "epf", "nps",
              "liquid fund", "gilt", "g-sec", "gsec", "rd", "recurring")),
    ("international", ("us stock", "us equity", "s&p", "sp500", "nasdaq",
                       "international", "global fund", "foreign")),
    ("index_fund", ("index fund", "nifty bees", "niftybees", "etf", "index",
                    "nifty 50 fund", "sensex fund")),
    ("cash", ("cash", "savings", "bank balance", "idle")),
    ("mid_small_cap", ("midcap", "mid cap", "smallcap", "small cap", "microcap",
                       "small-cap", "mid-cap")),
)

_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
         "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3}

_HOLDING = re.compile(
    r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*"
    r"(lakhs?|lacs?|crores?|cr|k|thousand|l)?\s*"
    r"(?:rupees?\s*)?(?:worth\s*)?(?:of\s*|in\s*|into\s*)\s*"
    r"([a-z0-9&.\- ]{2,40}?)(?=\s*(?:,|and\b|;|\.|$))",
    re.I,
)


@dataclass(slots=True)
class Holding:
    name: str
    value: float
    bucket: str
    guessed: bool = False

    @property
    def label(self) -> str:
        return BUCKETS[self.bucket]["label"]


@dataclass(slots=True)
class PortfolioAnalysis:
    holdings: list[Holding] = field(default_factory=list)
    total: float = 0.0
    by_bucket: dict[str, float] = field(default_factory=dict)
    concentration: dict[str, Any] = field(default_factory=dict)
    stress: list[dict[str, Any]] = field(default_factory=list)
    liquidity: list[dict[str, Any]] = field(default_factory=list)
    annual_vol: float = float("nan")
    one_year_range: tuple[float, float] = (float("nan"), float("nan"))
    unrecognised: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["holdings"] = [
            {"name": h.name, "value": h.value, "bucket": h.bucket,
             "label": h.label, "guessed": h.guessed}
            for h in self.holdings
        ]
        return d


def classify(name: str) -> tuple[str, bool]:
    """Map a holding to a bucket. Returns (bucket, was_guessed)."""
    low = name.lower().strip()
    for bucket, words in _BUCKET_WORDS:
        if any(w in low for w in words):
            return bucket, False
    if any(c in low for c in _LARGE_CAPS):
        return "large_cap", False
    if "fund" in low or "mutual" in low:
        # A generic "fund" is most often an equity fund, but we do not know.
        return "large_cap", True
    return "large_cap", True


def parse_holdings(text: str) -> list[Holding]:
    """Pull holdings out of plain English.

    Handles "5 lakh in HDFC Bank, 3L Reliance and 2 lakh gold". Anything it
    cannot classify becomes a flagged guess rather than a silent assumption.
    """
    out: list[Holding] = []
    for m in _HOLDING.finditer(text):
        raw, unit, name = m.group(1), (m.group(2) or "").lower(), m.group(3).strip()
        try:
            value = float(raw.replace(",", "")) * _MULT.get(unit, 1.0)
        except ValueError:
            continue
        if value < 100:
            continue
        name = re.sub(r"\b(worth|of|in|into|the|my|some)\b", "", name, flags=re.I).strip()
        if not name or len(name) < 2:
            continue
        bucket, guessed = classify(name)
        out.append(Holding(name=name.title(), value=value, bucket=bucket,
                           guessed=guessed))
    return out


def analyse(holdings: list[Holding], participation: float = 0.15) -> PortfolioAnalysis:
    """Run a set of holdings through the risk engine."""
    from vyuha.risk.liquidity import concentration, days_to_liquidate
    from vyuha.risk.stress import SCENARIOS, apply_scenario

    a = PortfolioAnalysis(holdings=holdings)
    if not holdings:
        a.caveats.append("No holdings recognised.")
        return a

    a.total = float(sum(h.value for h in holdings))
    for h in holdings:
        a.by_bucket[h.bucket] = a.by_bucket.get(h.bucket, 0.0) + h.value
    a.unrecognised = [h.name for h in holdings if h.guessed]

    # Build the frame the stress engine expects.
    rows = []
    for h in holdings:
        b = BUCKETS[h.bucket]
        rows.append({
            "value": h.value, "beta": b["beta"], "cap_segment": b["cap_segment"],
            "duration": b.get("duration", 0.0),
            "fx_exposure": h.value if h.bucket == "international" else 0.0,
        })
    book = pd.DataFrame(rows, index=[h.name for h in holdings])

    conc = concentration(pd.Series([h.value for h in holdings],
                                   index=[h.name for h in holdings]))
    a.concentration = conc

    for sc in SCENARIOS:
        shocked = apply_scenario(book, sc)
        pnl = float(shocked["total_pnl"].sum())
        a.stress.append({
            "name": sc.name, "period": sc.period,
            "loss": pnl, "loss_pct": pnl / a.total if a.total else float("nan"),
            "lesson": sc.lesson,
        })
    a.stress.sort(key=lambda x: x["loss"])

    adv = pd.Series({h.name: BUCKETS[h.bucket]["adv_inr"] for h in holdings})
    dtl = days_to_liquidate(pd.Series({h.name: h.value for h in holdings}),
                            adv, participation=participation)
    a.liquidity = [
        {"name": i, "days": float(r["days_to_liquidate"]),
         "bucket_label": BUCKETS[next(h.bucket for h in holdings if h.name == i)]["label"]}
        for i, r in dtl.iterrows()
    ]
    a.liquidity.sort(key=lambda x: -x["days"])

    # Portfolio volatility from bucket vols and weights. Correlations are NOT
    # estimated -- there is no per-holding return history here -- so a single
    # conservative cross-bucket correlation is assumed and declared.
    weights = {b: v / a.total for b, v in a.by_bucket.items()}
    assumed_corr = 0.6
    var_sum = sum((w * BUCKETS[b]["vol"]) ** 2 for b, w in weights.items())
    cross = sum(
        2 * assumed_corr * weights[b1] * BUCKETS[b1]["vol"] * weights[b2] * BUCKETS[b2]["vol"]
        for i, b1 in enumerate(weights) for b2 in list(weights)[i + 1:]
    )
    a.annual_vol = float(max(var_sum + cross, 0.0) ** 0.5)
    a.one_year_range = (
        a.total * (1 - 1.65 * a.annual_vol), a.total * (1 + 1.65 * a.annual_vol),
    )

    a.caveats = [
        "Individual shares cannot be priced here -- there is no per-stock data "
        "wired -- so holdings are grouped into asset classes and the class's "
        "typical behaviour is applied. A concentrated position in one mid-cap "
        "is riskier than the mid-cap average, and this will not show that.",
        f"Correlation between asset classes is assumed at {assumed_corr:.0%} "
        "rather than measured, so the volatility figure is indicative.",
        "Stress losses are what these scenarios did historically, applied to "
        "your allocation. They are not forecasts.",
    ]
    if a.unrecognised:
        a.caveats.insert(0, (
            f"Could not identify {', '.join(a.unrecognised[:4])} — treated as "
            "large-cap equity. Correct it by naming the asset class."
        ))
    return a


def analyse_text(text: str, **kw: Any) -> PortfolioAnalysis:
    return analyse(parse_holdings(text), **kw)
