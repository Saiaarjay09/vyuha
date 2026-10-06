# Vyuha

**Live: https://haven.taila6d3cb.ts.net/vyuha** (needs an access key — ask me
for the link with its `?key=`) — plain-English usage guide in
[HOW_TO_USE.txt](HOW_TO_USE.txt). (The site runs on a personal machine; if it is
asleep, the page will not load.)

**व्यूह** — *a battle formation: many independent units, each with its own
vantage, arrayed into a single structure.* It also means, simply, *array*.

An open-source risk and forecasting engine built on freely available data and
open-weight language models. Indian markets in depth, global markets through an
Indian lens — every foreign price also shown in rupees, because a rupee
investor's return is the asset's move *and* the currency's. Conceptually in the
territory BlackRock's Aladdin occupies — portfolio risk, factor attribution,
stress testing — with two things Aladdin does not have: it is inspectable, and
it argues with itself before answering.

[![tests](https://img.shields.io/badge/tests-84%20passing-green)]()
[![licence](https://img.shields.io/badge/licence-Apache--2.0-blue)]()
[![python](https://img.shields.io/badge/python-3.11%2B-blue)]()

> **Status: early. v0.1.** The risk mathematics, the council, and the
> point-in-time store are implemented and tested. Of 36 catalogued data
> sources, 10 have working fetchers (7 verified live on 2026-09-18) and 25 are
> catalogued but not yet wired. See [Data coverage](#data-coverage) — the
> catalogue is deliberately honest about what does not work yet.

---

## Why this exists

Risk systems fail in a specific way: they produce a single confident number,
and the number is wrong in a manner the system cannot see. Vyuha is built
around the opposite instinct — surface disagreement rather than average it
away.

Three design commitments follow from that:

**Point-in-time or nothing.** Every fact is stored bitemporally: the date it
describes, and the date it became *knowable*. India makes this essential — CPI
lands 12 days late and is revised twice, GDP is restated for years. A backtest
run "as of March 2024" cannot see an April release, structurally.

**Estimators must disagree out loud.** `var_ensemble()` runs five VaR
estimators and reports the spread. When historical and EVT differ by 2×, the
tail genuinely is not pinned down by the data, and *that* is the finding.

**The council is scored, not consulted.** Ten LLM personas with deliberately
opposed priors each produce a calibrated probability with cited evidence. They
are graded with strictly proper scoring rules, their systematic biases are
measured and subtracted, and pooling weights come from their track records.

---

## The council

A panel of neutral analysts given identical evidence converges on an identical
blind spot. So Vyuha's members are built to be *biased*, in structured
opposition:

| Member | Prior it argues from |
|---|---|
| `hawk` | Inflation is persistent; policy is too loose |
| `dove` | Slack is the binding constraint; inflation is supply-driven |
| `value_bear` | Multiples mean-revert; India's premium is a liability |
| `momentum_bull` | Trends persist; the domestic SIP bid dominates |
| `global_macro` | India is a price-taker on the Fed, the dollar and oil |
| `flows` | Marginal buyers set price; positioning extremes mark turns |
| `quant` | Base rates only; narrative is noise |
| `policy` | The State moves this market — RBI, SEBI, budget, duties |
| `behavioural` | Crowd psychology; sentiment extremes are contrarian |
| `red_team` | Assigned to attack whatever consensus forms |

Two rules keep this from being theatre. A persona's bias may shape **what it
weighs**, never **what the data says** — every claim must cite an evidence ID
from a frozen packet, and fabricated citations are flagged. And every member is
scored by the same proper rule, so a permabear's pessimism is *measured and
subtracted* rather than indulged.

### Aggregation is where the work is

Averaging forecasts is the obvious approach and it is subtly wrong. A simple
mean of well-calibrated but differently-informed forecasters is systematically
**under-confident** — each hedges for its own uncertainty, and averaging
preserves every hedge though the group collectively knows more.

Vyuha instead: bias-corrects each member in log-odds → pools with
track-record weights → extremises → **reports the dispersion alongside the
answer**.

The extremisation is gated on *directional agreement*, not raw spread. This
matters concretely. An early version treated dispersion alone as evidence of
independent information, and a panel deadlocked at 5%/95% got extremised to
**84.6% confidence** — manufacturing certainty out of a disagreement. Gating on
whether members at least land on the same side brings that to 70.8%, while a
unanimous-but-hedging panel still gets the full correction it deserves.

And the extremisation cap is not a constant borrowed from a paper — it is
**fitted from your own resolved questions** via `fit_extremise_cap()`. A fitted
cap near 1.0 is not a failure; it means your members are more correlated than
they look, and the fix is a more diverse panel, not harder extremisation.

```python
from vyuha.council import Council, CouncilConfig, Question, QuestionKind, EvidencePacket

packet = EvidencePacket(as_of=datetime.now())
packet.add("NIFTY50_CLOSE", 23346.4, source="NSE", event_date=date(2026, 9, 18))
packet.add("INDIA_VIX", 11.39, source="NSE", event_date=date(2026, 9, 18))

council = Council(personas=["hawk", "momentum_bull", "quant", "red_team"],
                  config=CouncilConfig(rounds=2))
verdict = council.run(question, packet)

print(verdict.summary_line())        # P = 12.9%  [4 members, dispersion 0.111]
print(verdict.dissent)               # who broke from consensus, and why
print(verdict.strongest_counterargument)
```

Round 0 is answered **independently** — no member sees another's view, because
anchoring is what collapses a multi-agent system into one forecaster with extra
steps. Later rounds show an *anonymised* distribution plus the strongest
counterargument.

**The panel sizes itself.** The standard error of the pooled estimate falls as
σ/√n, so when members agree the next one barely moves the answer — and costs
several seconds. Vyuha polls a deliberately opposed seed (hawk, momentum bull,
quant, red team), measures that precision, and recruits more only while it is
still poor. Round two then re-asks *only the dissenters*, since a member already
sitting on consensus has nothing to revise toward. Easy questions finish with
four members; contested ones still use all ten, which is when it is worth
paying for.

---

## Risk engine

| Module | What it does |
|---|---|
| `risk.covariance` | EWMA, Ledoit-Wolf, OAS, shrunk-EWMA; PSD-guaranteed; Euler risk contributions |
| `risk.var` | Historical, parametric (Cornish-Fisher), GARCH-filtered historical simulation, EVT peaks-over-threshold |
| `risk.factors` | India factor model — market, size, value, momentum, quality, low-vol, liquidity, governance |
| `risk.stress` | Nine scenarios calibrated on India's own crisis record |
| `risk.liquidity` | Amihud illiquidity, days-to-liquidate, circuit-limit risk, concentration |
| `backtest.var_tests` | Kupiec, Christoffersen, Basel traffic light |

Two details worth calling out, because both are places where a risk system
usually lies quietly:

**Cornish-Fisher is validity-checked.** It is an asymptotic expansion, not a
convergent one. Past a certain kurtosis the mapping stops being monotonic and
the "corrected" VaR is *worse* than the uncorrected one — on t(3) data it
overshot the empirical quantile by 29% while plain Gaussian undershot by 16%.
Vyuha checks monotonicity numerically, **rejects** the correction when invalid,
falls back to Gaussian, and sets `prefer_evt_or_fhs` in the diagnostics.

**Missing exposure is named, not zeroed.** `unmodelled_exposures()` reports
which risk axes your book carries no data for. A stress test that silently
treats absent duration as zero duration will report a bond portfolio as immune
to rate moves.

```bash
vyuha risk var --symbol ^NSEI --confidence 0.99
vyuha risk scenarios
```

---

## Data coverage

36 sources catalogued across 13 domains. The catalogue is a **data structure**,
not prose, so the CLI lists it and tests check it — and every entry carries the
date it was last verified against the live source.

```bash
vyuha sources list
vyuha sources show nse_option_chain
vyuha sources fetch nse_option_chain --series NIFTY
```

Verified working on 2026-09-18:

| Source | What | Verified |
|---|---|---|
| `amfi_nav` | All ~14,400 Indian MF NAVs daily | 14,374 rows, 53 AMCs |
| `fred` | US rates, dollar, Brent | 16,162 rows (DGS10) |
| `world_bank` | Long-run India macro, CC-BY | 65 years |
| `nse_indices` | 139 NSE indices incl. India VIX | live |
| `nse_fii_dii` | Daily FII/DII cash flows | live |
| `nse_option_chain` | Full chain: OI, IV, volume | 96 strikes, PCR 1.127 |

Alongside the conventional feeds, the catalogue targets **alternative data that
matters specifically in India** — Grid-India power demand (the best
high-frequency real-activity proxy, available six weeks before the IIP print it
anticipates), GST e-way bills, UPI volumes, VAHAN vehicle registrations, and
IMD rainfall. Monsoon → kharif output → food inflation → RBI policy → rates →
equity multiples is one of the longest genuinely causal chains in this market,
and it starts with weather.

### Things that break, and why they are documented

Building this surfaced real, non-obvious behaviour worth recording:

- **Bot-detection policies actively conflict.** NSE refuses anything that does
  not look like a browser. FRED's CDN *silently black-holes* requests carrying
  a Chrome User-Agent — the connection opens and the body never arrives. There
  is no single User-Agent that works everywhere, so `fetch(browser_ua=...)`
  lets each source choose.
- **NSE moved the option chain** from `/api/option-chain-indices` to
  `/api/option-chain-v3`, which returns an empty object unless you pass an
  `expiry`. No announcement. This is why everything NSE is marked `FRAGILE`.
- **AMFI changed its NAV schema**, inserting `Plan` and `Option` columns and
  shifting NAV from field 4 to field 6. A positional parser returned zero rows
  with no error. The parser is now header-driven and raises loudly instead.
- **Stooq is `BLOCKED`** — now behind a JavaScript proof-of-work challenge.
  Defeating it is out of scope, so it is marked blocked rather than left to rot.
- **GDELT asks for one request per 5 seconds** and says so in plain text
  instead of JSON when you exceed it. `HOST_RATE_LIMITS` honours stated limits
  rather than discovering them via 429s.

---

## Install

```bash
git clone https://github.com/<you>/vyuha.git && cd vyuha
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
vyuha doctor
```

For the council, install [Ollama](https://ollama.com) and pull models. Personas
are spread across **independently-trained families on purpose** — running all
members on one base model gives correlated errors that no amount of prompting
removes:

```bash
ollama pull qwen2.5:32b
ollama pull llama3.1:70b
ollama pull deepseek-r1
ollama pull gemma2:27b
```

Vyuha resolves each persona to the best available model and **records every
substitution in the run log**. It will run on a single small model — that is
how the demo above ran, on `llama3.2:3b` — but with genuinely correlated
members, which the verdict notes will tell you.

```bash
vyuha council personas
vyuha council ask "Will the Nifty 50 close below 23,000 before 2026-10-31?" \
  --resolves 2026-10-31 --live --rounds 2
vyuha council record
```

---

## Free, always-on hosting

A server on a personal machine is unreachable whenever that machine sleeps.
**GitHub Pages is free, never sleeps, and needs no card** — it just cannot run
Python.

It turns out most of Vyuha does not need Python. The projection is a bootstrap
over 8 KB of historical returns; portfolio risk is bucketing and arithmetic.
Both run in the browser. So a scheduled job builds a **56 KB static site** —
calculators, daily market figures, the latest council verdicts — and publishes
it to Pages every weekday.

```bash
python scripts/build_site.py --out site
```

The one thing it cannot do is answer *new* questions, because the council needs
a model at request time. It shows the latest recorded verdicts and says so.

Pages on a private repo needs a paid plan; on the free tier the repo must be
public. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Deploying it

Runs anywhere Docker runs; `fly.toml` and `render.yaml` are included. Inference
goes to any OpenAI-compatible endpoint serving open-weight models
(`groq`, `openrouter`, `cerebras`, …), so a cloud instance needs no GPU and the
models stay open. With none configured it degrades honestly: live figures and
stress tests keep working and the council says it has no advisors rather than
inventing a number. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Reading the code

- **[VARIABLES.txt](VARIABLES.txt)** — every variable, and the mechanism by
  which each one moves markets.
- **[CODEBASE.txt](CODEBASE.txt)** — every file, every library, and why.

## Web console

Live at **https://haven.taila6d3cb.ts.net/vyuha**. Written for someone who has
never used a risk system: you get a plain-English verdict ("Unlikely — about a
23% chance, roughly 1 in 4") before any number, a sentence on whether the
advisors agreed, and everything technical one click away rather than in your
face. Non-technical usage guide: [HOW_TO_USE.txt](HOW_TO_USE.txt).

```bash
./scripts/serve.sh                      # http://127.0.0.1:8601
./scripts/tailscale-serve.sh tailnet    # permanent HTTPS URL on your tailnet
./scripts/tailscale-serve.sh public     # or on the public internet
```

Three routes, chosen by a deliberately simple and inspectable classifier:

| You ask | Route | What happens |
|---|---|---|
| "Will the Nifty close below 22,900 in 30 days?" | `council` | ten members, N rounds, pooled probability + dispersion |
| "What is the repo rate?" | `data` | direct lookup from live sources — **no model involved, nothing inferred** |
| "Stress test my book" | `risk` | the scenario engine |

The console shows an **independence warning** when every member resolves to the
same base model, because then their errors are correlated and the dispersion
understates true uncertainty. It is the kind of thing a dashboard normally
hides.

See [docs/DEPLOY.md](docs/DEPLOY.md) — including the Tailscale footgun where
`tailscale serve --set-path` on a Funnel-enabled port silently de-publishes
every other site on that port.

---

## For an ordinary investor

Three things that need no jargon:

**Your actual portfolio.** Tell it what you hold in plain English and it runs
your allocation through the risk engine — concentration, what past Indian
crises would have cost you, how fast you could sell.

> *"I have ₹8 lakh in HDFC Bank, ₹5 lakh in Reliance and ₹3 lakh in gold"*
> → ₹16,00,000 across 3 holdings. Biggest single holding **50%** of the total.
> Typical yearly swing **±15%**. The Global Financial Crisis would have cost
> you **−42%**, about ₹6,71,000.

**A goal, worked backwards.** *"I want ₹1 crore in 15 years"* →

| | |
|---|---|
| Monthly, ~50% chance | ₹24,571 |
| **Monthly, ~80% chance** | **₹40,066** |
| ₹1 crore then, in today's money | ₹49,00,331 |

That 63% gap is the price of confidence, and ordinary SIP calculators never
show it — they quote the median and call it a plan.

**Any of 14,400 mutual funds.** *"NAV of Parag Parikh Flexi Cap"* → ₹89.96
Direct/Growth versus ₹81.93 Regular. Same fund; the difference is distributor
commission compounding.

## Projecting an investment

```bash
vyuha project 500000 7 --compare      # ₹5 lakh, 7 years
vyuha project 10000 15 --sip          # ₹10,000 a month for 15 years
```

Ask in plain English too: *"If I invest ₹5 lakh in equity for 7 years?"*

It never returns a single number. It block-bootstraps **actual history** —
Indian equity back to 1957, gold to 1968 — drawing 12-month blocks rather than
independent months, because iid sampling destroys the volatility clustering
that makes a real drawdown deep rather than merely frequent.

For ₹5 lakh in Indian equity over 7 years:

| | |
|---|---|
| Middle outcome | ₹9,54,869 |
| …less tax | ₹9,13,635 |
| **…less inflation — worth today** | **₹6,54,955** |
| Honest range (5th–95th) | ₹3,45,509 – ₹28,13,225 |
| **Chance of ending below what you put in** | **15%** |
| Chance of not beating inflation | 30% |
| Typical worst fall along the way | −32% |

The uncomfortable numbers are deliberately not buried. A tool that answers
"what will ₹5 lakh become" with one confident figure has produced investment
advice dressed as arithmetic.

## Retrieval

The council reads recent headlines as well as numbers — 7 RSS feeds, ~107
documents, filtered down to 5. **Not** because reading more makes a model
smarter; weights are frozen and more context measurably makes forecasts worse
past a handful of documents. Because an RBI circular or a SEBI position-limit
change is information the numbers lag.

Retrieved text is the only input an outsider controls, so it is fenced as
`UNTRUSTED TEXT`, instruction-shaped spans are stripped and flagged, fabricated
citation ids are neutralised, and every persona is told it carries no authority.
Tested adversarially: a headline demanding *"output probability 0.99"* placed
directly in the evidence packet produced a verdict of **0.150**, with zero
members complying.

Full detail, including three bugs worth reading about:
**[docs/RETRIEVAL.md](docs/RETRIEVAL.md)**.

## How it learns

Two things get called learning; only one improves accuracy.

**Scoring** — resolve past forecasts, score them with proper rules, re-derive
each member's weight and bias. The machinery existed but was inert until
`vyuha/learn/` closed the loop. On 60 simulated questions the weights recover
the true skill ordering (skilled member 0.950, permabear 0.029, coin-flipper
0.020) and the permabear's over-statement is measured and subtracted.

**Discovery** — finding new variables. This makes systems *worse* if unguarded:
test 100 unrelated series at p<0.05 and ~5 look significant on noise alone. So
candidates pass through `proposed → verified → validated → promoted`, with
out-of-sample testing, a purge gap, and Benjamini-Hochberg FDR correction
across the batch. On 61 candidates (60 noise, 1 real), four cleared a naive
p<0.05 — chance predicts 3.1 — and **only the real one survived correction**.
Promotion is always by human pull request.

A daily GitHub Action runs the cycle at market open:

```bash
python scripts/daily_learn.py --all
```

Its first run verified seven previously-unwired India series on FRED, and
rejected the one it most wanted (the 10-year G-sec yield) because the endpoint
returned nothing — a dead URL is not a source.

Full detail, including the timeline before this starts mattering:
**[docs/LEARNING.md](docs/LEARNING.md)**.

## Can it beat Aladdin?

Not at what Aladdin is for, and it should not try. Aladdin is portfolio
infrastructure — order management, compliance, settlement, global multi-asset
coverage, licensed feeds, thirty years of crisis-tested history. That needs a
company, not a repository.

It also **cannot be benchmarked against**: proprietary, no public API, no
published accuracy figures. Anyone showing you a head-to-head has invented it.

So Vyuha benchmarks against something public and falsifiable instead — **the NSE
option chain's implied probability**, real money's own forecast, free and
updating every few seconds:

```bash
vyuha benchmark
```

A live reading with the Nifty at 23,346, on "close below 22,900 on any session
in ~30 days":

| | |
|---|---|
| Market, terminal `P(S_T ≤ K)` | 23.2% |
| Market, barrier-adjusted | 46.3% |
| Market, de-biased for risk premium | 40.2% |
| **Vyuha council** | **12.3%** |

The council sits 27.9pp below the market — most likely because a 3B model does
not grasp that "any session" is a *barrier* question, not a terminal one. That
is now a measurable defect rather than an unexamined one.

Where a small Indian system genuinely wins: alternative data global vendors
won't wire up (power demand, e-way bills, monsoon), market structure their
models ignore (circuit limits, promoter pledging), policy shocks statistics
cannot see, and reasoning you can actually audit.

Full analysis: **[docs/VS_ALADDIN.md](docs/VS_ALADDIN.md)**.

## What it can answer

```bash
vyuha coverage
```

| Asset class | Can answer? |
|---|---|
| Indian equity, derivatives | **Yes** — indices, VIX, option chain, flows, factors, stress |
| Commodities | **Yes** — gold & silver at the LBMA fix (daily since 1968), crude, gas, metals, grains |
| Global equity & rates | **Yes** — S&P, Nasdaq, Dow, VIX, US/euro/Japan/UK yields, dollar index |
| Currency | **Yes** — 30 currencies with history, 166 spot |
| World macro | **Yes** — 217 countries |
| ETFs, mutual funds | **Yes, shallow** — ~14,400 NAVs, no tracking-error analytics |
| Bonds | **Weak** — policy corridor only; **no Indian G-sec curve** |
| Real estate / housing | **No** — nothing wired, and it says so |

### The rupee lens

Every foreign price is converted at the **contemporaneous** rate, and returns
are decomposed into the asset move and the currency move:

```bash
vyuha world commodities     # gold, silver, crude, metals — in USD and INR
vyuha world inr sp500       # what a rupee investor actually earned
vyuha world country BRA     # macro for any of 217 countries
```

In the year to 2026-09-17 the S&P 500 returned **+15.2% in dollars**. The rupee
weakened 8.9%, so an Indian investor received **+25.4%** — the currency was
**35% of the return**. A global tool quoting only the dollar figure is telling
an Indian reader the wrong number.

Ask about housing and the system **refuses rather than guesses** — a language
model would happily answer from memory with confident, sourceless numbers, which
is the exact failure this project exists to prevent. Details and the gap list:
**[docs/COVERAGE.md](docs/COVERAGE.md)**.

## On the precision target

This project was specified to detect effects moving the market by **0.00001%**.
That target is not reachable by any system, and the reasons are worth stating
plainly:

- NSE's tick size is ₹0.05. On a ₹500 stock that is a 0.01% quantum — **1,000×
  larger** than the target. The exchange cannot represent a price change that
  small.
- Distinguishing a 1e-7 effect from zero against 1% daily volatility needs on
  the order of **10¹⁰ trading days** — roughly 150 million years. This is
  information-theoretic, not a compute limit.
- The *inputs* aren't that precise. CPI first-print to final revision moves
  10–20bp, four orders of magnitude above the target.

So Vyuha pursues the *breadth* half of the ambition seriously — far more
variables than a conventional risk system, including the grid and the weather —
and replaces the precision half with something achievable: quantify what is
explained, quantify what is not, and never report a number without its
uncertainty attached.

Full treatment, with the arithmetic: **[docs/PRECISION.md](docs/PRECISION.md)**.

---

## What this is not

- **Not investment advice.** It is analytical software.
- **Not a licensed market-data feed.** Several sources — NSE and BSE especially
  — are website endpoints under terms of use, not open data. Vyuha fetches them
  at low, throttled rates for personal research. Redistribution or commercial
  use is between you and the exchange; read their terms.
- **Not Aladdin.** Aladdin has decades of work, licensed data, and real-time
  infrastructure behind it. This is a foundation with honest edges.
- **Not a prediction machine.** The council's value is calibrated uncertainty
  and surfaced disagreement — not being right about the market.

## Licence

Apache 2.0.
