# Vyuha

**Live: https://haven.taila6d3cb.ts.net/vyuha** — plain-English usage guide in
[HOW_TO_USE.txt](HOW_TO_USE.txt). (The site runs on a personal machine; if it is
asleep, the page will not load.)

**व्यूह** — *a battle formation: many independent units, each with its own
vantage, arrayed into a single structure.* It also means, simply, *array*.

An open-source risk and forecasting engine for Indian financial markets, built
on freely available data and open-weight language models. Conceptually in the
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
