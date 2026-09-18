"""The market's own forecast, extracted from the NSE option chain.

This is the benchmark that makes "is Vyuha any good?" a falsifiable question
rather than a matter of taste. Option prices encode a full probability
distribution over where the index will be at expiry, contributed by people
with money at risk, updated every few seconds, and free.

Breeden-Litzenberger (1978): for European calls C(K) on the same expiry, the
risk-neutral CDF is

    F(K) = P(S_T <= K) = 1 + e^{rT} * dC/dK

so the whole distribution falls out of the slope of call price against strike.
With discrete strikes we difference numerically.

ONE CAVEAT THAT MATTERS, AND IS OFTEN IGNORED
---------------------------------------------
This is the *risk-neutral* distribution, not the real-world one. They are not
the same thing. Investors pay up for downside protection, so index puts are
persistently expensive relative to what actually happens -- the variance risk
premium. The practical consequence is that the implied probability of a large
fall is **biased high**, typically by a meaningful factor for far
out-of-the-money strikes.

So "Vyuha said 20%, the market implied 30%, the crash did not happen, Vyuha
wins" is NOT automatically a real result -- a permabull that always says 0%
would also beat the implied on downside questions, purely by harvesting that
premium. To make the comparison honest you must either (a) compare over many
questions in both directions, or (b) de-bias the implied probability first.
:func:`real_world_adjust` does a crude version of (b) and is explicit that it
is crude.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class ImpliedDistribution:
    """A risk-neutral distribution recovered from an option chain."""

    strikes: np.ndarray
    cdf: np.ndarray                 # P(S_T <= K)
    spot: float
    expiry: str
    time_to_expiry_years: float
    rate: float
    n_strikes_used: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def prob_below(self, level: float) -> float:
        """P(S_T <= level) by interpolation on the recovered CDF."""
        return float(np.clip(np.interp(level, self.strikes, self.cdf), 0.0, 1.0))

    def prob_above(self, level: float) -> float:
        return 1.0 - self.prob_below(level)

    def prob_touch_below(self, level: float) -> float:
        """P(the index trades at or below ``level`` at ANY point before expiry).

        This is NOT the same as :meth:`prob_below`, and conflating the two is a
        real error that would invalidate any comparison against Vyuha.

        The option chain prices where the index finishes. But the council is
        usually asked "will it close below X on any session in the next 30
        days?" -- a *barrier* question about the path, not the endpoint. The
        index can fall through 22,900 in week two and recover by expiry: that
        resolves the council's question YES while the terminal probability
        records it as NO.

        By the reflection principle, for a driftless random walk the
        probability of ever touching a barrier below is approximately twice the
        probability of finishing below it:

            P(min_{t<=T} S_t <= K)  ~  2 * P(S_T <= K),   K < S_0

        The approximation ignores drift and is capped at 1. It is rough, but it
        is far closer than using the terminal probability unadjusted, which
        understates a 30-day barrier question by roughly half.
        """
        if level >= self.spot:
            return float(min(1.0, 2.0 * self.prob_above(level)))
        return float(min(1.0, 2.0 * self.prob_below(level)))

    def quantile(self, q: float) -> float:
        """The strike at which the CDF crosses q."""
        return float(np.interp(q, self.cdf, self.strikes))

    def median(self) -> float:
        return self.quantile(0.5)

    def summary(self) -> dict[str, Any]:
        return {
            "spot": self.spot, "expiry": self.expiry,
            "days_to_expiry": round(self.time_to_expiry_years * 365, 1),
            "median": round(self.median(), 1),
            "q05": round(self.quantile(0.05), 1),
            "q95": round(self.quantile(0.95), 1),
            "n_strikes": self.n_strikes_used,
            **self.diagnostics,
        }


def _monotone(y: np.ndarray) -> np.ndarray:
    """Force a non-decreasing sequence (a CDF cannot go down).

    Noisy quotes at illiquid strikes routinely produce small violations; this
    is a pool-adjacent-violators-lite pass that keeps the result a valid CDF.
    """
    out = np.maximum.accumulate(y)
    return np.clip(out, 0.0, 1.0)


def implied_cdf(
    strikes: np.ndarray, call_prices: np.ndarray, rate: float, t_years: float
) -> np.ndarray:
    """Risk-neutral CDF via the Breeden-Litzenberger derivative."""
    order = np.argsort(strikes)
    k, c = np.asarray(strikes, float)[order], np.asarray(call_prices, float)[order]
    dcdk = np.gradient(c, k)
    cdf = 1.0 + np.exp(rate * t_years) * dcdk
    return _monotone(cdf)


def _otm_call_curve(
    df: pd.DataFrame, spot: float, rate: float, t_years: float, min_oi: int
) -> pd.DataFrame:
    """Build a clean call-price curve from OUT-OF-THE-MONEY options only.

    This is the part that makes the difference between a usable distribution
    and noise. In-the-money options barely trade on the NSE -- their quotes go
    stale for hours and their price is nearly all intrinsic value, so
    differencing them yields garbage. The liquidity lives out of the money:
    puts below spot, calls above it.

    So we take OTM puts and convert them to equivalent call prices with
    put-call parity,

        C = P + S - K * exp(-rT)

    and splice them onto the genuine OTM calls above spot. Every point on the
    resulting curve then comes from an option someone actually trades.
    """
    disc = np.exp(-rate * t_years)

    def _mid(side: str) -> pd.DataFrame:
        x = df[df["side"] == side].copy()
        if min_oi:
            x = x[pd.to_numeric(x["oi"], errors="coerce").fillna(0) >= min_oi]
        bid = pd.to_numeric(x.get("bid"), errors="coerce")
        ask = pd.to_numeric(x.get("ask"), errors="coerce")
        ltp = pd.to_numeric(x.get("ltp"), errors="coerce")
        # A two-sided quote is real; a last-traded price may be hours old.
        x["price"] = ((bid + ask) / 2.0).where((bid > 0) & (ask > 0), ltp)
        x = x[x["price"].notna() & (x["price"] > 0)]
        return x.groupby("strike", as_index=False)["price"].last()

    calls = _mid("CE")
    puts = _mid("PE")

    otm_calls = calls[calls["strike"] >= spot]
    otm_puts = puts[puts["strike"] < spot].copy()
    # Put-call parity turns a liquid OTM put into the call price we need.
    otm_puts["price"] = otm_puts["price"] + spot - otm_puts["strike"] * disc

    curve = pd.concat([otm_puts, otm_calls]).sort_values("strike").reset_index(drop=True)
    curve = curve[curve["price"] > 0]

    # No-arbitrage: C(K) must be non-increasing in K, and bounded by intrinsic.
    curve["price"] = np.minimum.accumulate(curve["price"].to_numpy(float))
    intrinsic = np.maximum(spot - curve["strike"].to_numpy(float) * disc, 0.0)
    curve = curve[curve["price"] >= intrinsic - 1e-9]
    return curve.reset_index(drop=True)


def implied_from_chain(
    chain: pd.DataFrame,
    spot: float | None = None,
    rate: float = 0.0525,
    expiry: str | None = None,
    min_oi: int = 1,
    moneyness_band: tuple[float, float] = (0.80, 1.20),
    today: dt.date | None = None,
    strict: bool = False,
) -> ImpliedDistribution:
    """Recover the risk-neutral distribution from a Vyuha option-chain frame.

    Expects columns: strike, expiry, side, ltp, oi, bid, ask.

    ``moneyness_band`` restricts to strikes where NSE liquidity actually
    exists. Beyond roughly +/-20% of spot the quotes are wide, stale or absent,
    and including them corrupts the numerical derivative for every strike.

    The returned object carries ``diagnostics["reliable"]``. **Check it.** A
    thin or stale chain can produce a mathematically well-formed distribution
    that is complete nonsense -- a flat CDF, or one that never crosses 0.5.
    With ``strict=True`` an unreliable recovery raises instead of returning.
    """
    df = chain.copy()
    if expiry is not None:
        df = df[df["expiry"] == expiry]
    if df.empty:
        raise ValueError(f"no rows for expiry {expiry!r}")

    exp = expiry or str(df["expiry"].iloc[0])
    spot = float(spot if spot is not None else chain.attrs.get("underlying") or np.nan)
    if not np.isfinite(spot):
        raise ValueError("spot not available; pass spot= explicitly")

    t_years = _years_to(exp, today)
    lo, hi = spot * moneyness_band[0], spot * moneyness_band[1]
    df = df[(df["strike"] >= lo) & (df["strike"] <= hi)]

    curve = _otm_call_curve(df, spot, rate, t_years, min_oi)
    if len(curve) < 8:
        raise ValueError(
            f"only {len(curve)} liquid strikes for {exp} within "
            f"{moneyness_band[0]:.0%}-{moneyness_band[1]:.0%} of spot; need >= 8. "
            "The chain is too thin to recover a distribution."
        )

    k = curve["strike"].to_numpy(float)
    c = curve["price"].to_numpy(float)
    cdf = implied_cdf(k, c, rate, t_years)

    crosses = bool(cdf.min() <= 0.5 <= cdf.max())
    spans = bool(cdf.min() < 0.15 and cdf.max() > 0.85)
    flat = bool(np.ptp(cdf) < 0.3)

    # Step-function degeneracy. A CDF that leaps from ~0 to ~1 across one or two
    # strikes is a point mass -- a distribution with essentially no variance,
    # which is never a real market view. This slips past the checks above,
    # because such a CDF is monotone, spans both tails and crosses the median
    # perfectly well. It arises when quotes are constant or stale across
    # strikes: put-call parity then imposes a clean linear call curve on
    # garbage input and manufactures structure that was never there.
    biggest_step = float(np.max(np.diff(cdf))) if len(cdf) > 1 else 1.0
    step_degenerate = biggest_step > 0.5

    # Independently: the recovered 5-95 range should be a plausible fraction of
    # spot for the horizon. Narrower than 0.3% over any real horizon is not a
    # forecast, it is an artefact.
    try:
        rng = float(np.interp(0.95, cdf, k) - np.interp(0.05, cdf, k))
        too_narrow = bool(rng / spot < 0.003)
    except Exception:  # noqa: BLE001
        rng, too_narrow = float("nan"), True

    reliable = (crosses and spans and not flat and not step_degenerate
                and not too_narrow and len(k) >= 12)

    dist = ImpliedDistribution(
        strikes=k, cdf=cdf, spot=spot, expiry=exp,
        time_to_expiry_years=t_years, rate=rate, n_strikes_used=len(k),
        diagnostics={
            "crosses_median": crosses, "spans_tails": spans, "degenerate_flat": flat,
            "step_degenerate": step_degenerate,
            "largest_cdf_step": round(biggest_step, 4),
            "range_pct_of_spot": round(rng / spot, 5) if np.isfinite(rng) else None,
            "cdf_min": round(float(cdf.min()), 4), "cdf_max": round(float(cdf.max()), 4),
            "strike_range": (float(k.min()), float(k.max())),
            "reliable": reliable,
            "unreliable_reason": (
                "" if reliable else
                "; ".join(filter(None, [
                    "" if crosses else "CDF never crosses 0.5",
                    "" if spans else "CDF does not span both tails",
                    "degenerate/flat CDF" if flat else "",
                    (f"step-function CDF (one strike carries {biggest_step:.0%} of "
                     "the mass) - quotes are likely constant or stale")
                    if step_degenerate else "",
                    "implied range is implausibly narrow" if too_narrow else "",
                    "" if len(k) >= 12 else f"only {len(k)} strikes",
                ]))
            ),
        },
    )
    if strict and not reliable:
        raise ValueError(
            f"unreliable implied distribution for {exp}: "
            f"{dist.diagnostics['unreliable_reason']}"
        )
    return dist


def implied_probability_below(
    chain: pd.DataFrame, level: float, **kw: Any
) -> tuple[float, ImpliedDistribution]:
    """Convenience: the market's risk-neutral P(index <= level) at expiry."""
    dist = implied_from_chain(chain, **kw)
    return dist.prob_below(level), dist


def real_world_adjust(p_riskneutral: float, variance_premium: float = 0.25) -> float:
    """Crude de-biasing of a risk-neutral downside probability.

    Shrinks the probability in log-odds by ``variance_premium`` to reflect that
    index puts carry a persistent premium, so the risk-neutral measure
    overstates the chance of a fall.

    This is deliberately simple and openly approximate. The defensible way to
    set ``variance_premium`` is to fit it on your own resolved history --
    compare realised outcome frequencies against the implied probabilities you
    recorded, and solve for the shift that makes them agree. Until you have
    that history, treat the output as indicative, and never present the
    adjusted number as though it were measured.
    """
    from vyuha.council.scoring import clamp, expit, logit

    return float(expit(logit(clamp(p_riskneutral)) - variance_premium))


def _years_to(expiry: str, today: dt.date | None = None) -> float:
    today = today or dt.date.today()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(expiry, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"cannot parse expiry {expiry!r}")
    days = max((d - today).days, 0) + 0.5   # half a day so same-day is not zero
    return days / 365.0
