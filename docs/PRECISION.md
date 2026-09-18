# On precision: what this system can and cannot resolve

Vyuha was specified with a target of detecting effects that move the market by
**0.00001%** (1 part in 10 million, or 1e-7 in relative terms). This document
explains why that target is not reachable — not by Vyuha, not by BlackRock's
Aladdin, not by any system that has ever existed — and what was built instead.

This is here because a risk system that quietly accepts an impossible
specification and then reports numbers to seven decimal places is worse than
useless. It is actively dangerous, because it manufactures confidence.

## 1. The target is below the market's own resolution

Indian equities trade on a price grid. The NSE tick size for most equities is
**₹0.05**. The smallest price change that can physically occur is therefore:

| Stock price | One tick | As a fraction | vs. the 1e-7 target |
|---|---|---|---|
| ₹100   | ₹0.05 | 0.05%   | **5,000× larger** |
| ₹500   | ₹0.05 | 0.01%   | **1,000× larger** |
| ₹2,500 | ₹0.05 | 0.002%  | **200× larger** |

There is no state of the world in which a stock moves by 0.00001%. The
exchange cannot represent that price. The effect you want to detect is smaller
than the quantum in which prices exist.

The Nifty 50 index is quoted to 0.01 points, which at 23,346 is about 4e-7 —
still coarser than the target, and in any case the index is a computed
statistic, not something you can trade at that granularity.

## 2. The target is far below the statistical noise floor

Set aside tick size and suppose prices were continuous. To distinguish an
effect of size ε from zero, against daily volatility σ, you need roughly

    n ≈ (2σ / ε)²

observations. Indian equity daily volatility is around σ = 1%. For ε = 1e-7:

    n ≈ (2 × 0.01 / 1e-7)² = (2 × 10⁵)² = 4 × 10¹⁰ trading days

At 252 trading days a year, that is on the order of **150 million years** of
data. NSE has existed since 1994. You would need a meaningful fraction of the
age of the universe to establish that such an effect was not zero.

This is not a limitation of the model, of compute, or of how many LLMs vote.
It is information-theoretic. The data does not contain the answer.

## 3. Genuine irreducible uncertainty sits many orders of magnitude higher

Even the inputs are not known to anything like this precision:

- **CPI** is released ~12 days late and revised twice. First-print to final
  revision routinely moves 10-20 basis points — that is 1e-3, four orders of
  magnitude above the target.
- **GDP** is revised for *years* afterwards, often by whole percentage points.
- **FII/DII flows** are reported as end-of-day aggregates with no intraday
  detail.
- **Corporate earnings** involve accounting estimates with legitimate ranges
  wider than the entire effect you want to measure.

A system cannot be more precise than its inputs. Propagating a ±0.2% input
uncertainty through any model gives you an output uncertainty far larger than
1e-7, regardless of how sophisticated the model is.

## 4. What Vyuha does instead

Rather than pretend, the system is built to be **maximally resolving within
real limits, and explicit about where those limits are**:

1. **Resolve to the data's actual granularity.** Tick and order-book level
   where that data exists; daily elsewhere. Never report more precision than
   the source carries.

2. **Cover the variable space exhaustively.** The ambition behind "every
   variable" is right even though the precision target is not. The
   [source catalogue](../src/vyuha/ingest/catalogue.py) spans equity,
   derivatives, rates, FX, credit, flows, commodities, macro, policy text,
   weather and alternative data — including power demand, e-way bills, UPI
   volumes and vehicle registrations, which most risk systems ignore entirely.

3. **Report unexplained variance as a first-class output.** The factor model
   returns `pct_specific` — the share of portfolio risk it *cannot* attribute.
   A system that explains 60% of variance and says so is more useful than one
   that claims 99.99% and is wrong.

4. **Report estimator disagreement instead of hiding it.** `var_ensemble()`
   runs five VaR estimators and returns the spread. When they disagree by 2×,
   the honest output is the range, and the system says so.

5. **Refuse to extrapolate past validity.** The Cornish-Fisher expansion is
   checked for monotonicity before use and *rejected* when sample kurtosis puts
   it outside its valid domain, rather than silently returning a worse number
   that looks more sophisticated.

6. **Backtest the risk numbers themselves.** Kupiec and Christoffersen tests
   decide whether a VaR model is believable at all. A model that fails them is
   reported as rejected, not quietly used.

## 5. What precision *is* achievable

Realistically, for Indian markets:

| Quantity | Achievable resolution | Limited by |
|---|---|---|
| Intraday price impact | ~1 basis point (0.01%) | tick size, order book depth |
| Daily VaR | ±10-20% of the estimate | tail sampling; estimator choice |
| Factor attribution | ~1-5% of variance | model specification |
| Macro nowcast | ±0.2-0.5pp | input revision noise |
| Directional forecast (1m) | 55-60% accuracy at best | genuine unpredictability |

Anyone quoting materially better than this on Indian markets is measuring
their backtest, not the world.

## 6. The honest version of the original ambition

> "Calculate every variable that can cause any minor change."

The *breadth* half of this is excellent and is what Vyuha pursues seriously:
cover far more variables than a conventional risk system, including the
weather, the electricity grid and the payments system, because in India those
genuinely propagate to asset prices.

The *precision* half has to be replaced with something achievable: quantify
how much is explained, quantify how much is not, and never present a number
without the uncertainty attached to it.

That is a harder system to build than one that prints seven decimal places.
It is also the only kind worth trusting with money.
