# Vyuha vs BlackRock's Aladdin

## First: you cannot benchmark against Aladdin

There is no public API, no trial, no published accuracy figures, and no
independent audit of its forecasts. Anyone showing you a head-to-head accuracy
comparison against Aladdin has invented it.

So "be more accurate than BlackRock" cannot be measured directly. It can,
however, be made into a real question by changing the benchmark to something
public and falsifiable.

## The benchmark that does work: the option chain

The NSE option chain encodes a full probability distribution over where the
Nifty will be at expiry. It is produced by people with money at risk, updates
every few seconds, and is free.

This is a *strong* benchmark. Index options are among the most efficiently
priced instruments in India. If Vyuha consistently beats the option-implied
probability, that is a defensible claim of skill — and one that Aladdin, to
public knowledge, does not publish for itself.

`vyuha/benchmark/implied.py` recovers it via Breeden-Litzenberger:

    F(K) = P(S_T ≤ K) = 1 + e^{rT} · dC/dK

Three implementation details separate a usable number from noise:

**Out-of-the-money options only.** In-the-money NSE options barely trade; their
quotes go stale for hours and are nearly all intrinsic value. Differencing them
produces garbage — the first version of this code returned a CDF of 1.0 at every
strike for one expiry. The fix is to use liquid OTM puts below spot, converted
to call prices by put-call parity, spliced onto genuine OTM calls above.

**Barrier ≠ terminal.** The chain prices where the index *finishes*. The council
is usually asked "will it close below X on **any** session in 30 days?" — a
question about the path. The index can break 22,900 in week two and recover by
expiry: that resolves YES while the terminal probability records NO. By the
reflection principle P(ever touch K) ≈ 2 · P(finish below K). Comparing without
this adjustment understates the barrier question by roughly half.

**Risk-neutral ≠ real-world.** Investors overpay for downside protection, so
implied crash probabilities are biased high. A permabull that always says 0%
would "beat" the implied probability on downside questions purely by harvesting
that premium. `real_world_adjust()` applies a crude correction and says plainly
that it is crude.

### A live reading

Nifty at 23,346, question "close below 22,900 on any session in ~30 days":

| Estimate | Value |
|---|---|
| Market, terminal `P(S_T ≤ K)` | 23.2% |
| Market, barrier-adjusted | 46.3% |
| Market, barrier + risk-premium de-biased | 40.2% |
| **Vyuha council** | **12.3%** |

The council sits **27.9pp below** the de-biased market. That is a large gap, and
the most likely explanation is unflattering: a 3B-parameter model does not
reliably grasp that "any session" is a barrier question, so it answers the
terminal one and anchors on "markets usually go up".

**One question proves nothing.** This is the measurement apparatus, not a
result. Distinguishing skill from luck needs dozens of resolved questions —
`score_against_market()` refuses to declare a winner below 20 and says so in its
verdict string.

## Where Vyuha cannot compete, and should not try

Aladdin is not a forecasting tool. It is an operating system for a portfolio:
order management, compliance, settlement, accounting, global multi-asset
coverage, licensed real-time feeds, and thirty years of position history through
real crises. Roughly $20tn+ of assets are administered on it.

Competing there requires a company, not a repository. Specifically out of reach:

- Multi-asset position keeping, order management, settlement
- Licensed exchange feeds (Vyuha uses throttled public endpoints)
- Global coverage — Vyuha covers India
- Regulatory reporting (UCITS, Solvency II, Form PF)
- Decades of crisis-tested history

Chasing these is how a project like this dies. Do not.

## Where a small Indian system genuinely wins

**Alternative data a global vendor has no incentive to wire up.** Grid-India
power demand is the best high-frequency proxy for Indian industrial activity and
lands six weeks before the IIP print it anticipates. GST e-way bills, UPI
volumes, VAHAN registrations, IMD rainfall. These are causally connected to
Indian asset prices and largely absent from global risk platforms.

**Market structure that developed-market models ignore.** A stock locked at its
circuit limit cannot be sold at any price — a failure mode that turns a modelled
loss into an unmodelled one. Promoter pledging has preceded a large share of
Indian mid-cap blowups and has no clean US analogue; Vyuha carries it as a
factor.

**Policy shocks statistics cannot see.** Demonetisation removed 86% of currency
by value overnight. No statistical model anticipated it, and none could. A
policy-literate reader is the only defence.

**The monsoon → food → policy chain.** Rainfall drives kharif output, which
drives food inflation, which drives the repo rate, which drives equity
multiples. Almost no risk system anywhere treats weather as a financial factor.
In India it is not optional.

**Calibration, transparency and disagreement.** Aladdin returns a number. Vyuha
returns a number, how much its members disagreed, every piece of evidence they
used, and a reproducible hash of the whole thing. It also scores itself with
strictly proper rules and publishes the track record. That is a different
product, not a worse one.

**Cost.** Aladdin is a seven-figure annual commitment. This is free.

## The honest summary

> Vyuha cannot and should not try to replace Aladdin. What a small,
> India-focused, transparent system can do better is *depth on India* — data a
> global vendor will not bother with, market structure their models ignore,
> policy risk statistics cannot capture, and reasoning you can actually audit.
> Pick those fights. Do not pick the other one.

## How to actually improve — in priority order

1. **Resolve questions and score them.** Nothing else matters until there are
   50+ resolved forecasts with recorded market-implied comparisons. Everything
   below is speculation until then.
2. **Fix the barrier/terminal confusion.** The 27.9pp gap above suggests the
   council does not understand path-dependent questions. State it explicitly in
   the prompt, or decompose barrier questions before asking.
3. **Run genuinely different models.** All ten members currently share one base
   model, so their errors are correlated and the ensemble is close to a single
   forecaster with extra steps.
4. **Wire the alternative data.** This is the actual edge and it is still mostly
   catalogued rather than connected.
5. **Fit the aggregation parameters** (`fit_extremise_cap`) on real resolved
   history instead of defaults.
6. **Close the asset-class gaps** — see [COVERAGE.md](COVERAGE.md). Bonds and
   housing are thin; commodities are absent.
