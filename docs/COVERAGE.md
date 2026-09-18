# What Vyuha can and cannot answer

Generated from the catalogue, not from optimism. Run it yourself:

```bash
vyuha coverage
curl localhost:8601/api/coverage
```

"Usable" means a source with a **working or fragile fetcher that returned real
data when last run**. Catalogued-but-unwired sources do not count, because a
source you have not connected cannot answer anything.

| Asset class | Sources | Usable | Can answer? | What you actually get |
|---|---|---|---|---|
| **Equity / shares** | 13 | 6 | **Yes** | Index levels, 139 NSE indices, India VIX, FII/DII daily flows, option chain, factor model, stress scenarios |
| **Derivatives** | 4 | 2 | **Yes** | Full Nifty option chain — OI, IV, volume, PCR — plus the implied distribution |
| **ETFs** | 3 | 3 | **Yes, shallow** | Prices via Yahoo (`NIFTYBEES.NS`), NAVs via AMFI. No ETF-specific analytics like tracking error or creation/redemption |
| **Mutual funds** | 2 | 1 | **Yes** | Daily NAV for ~14,400 schemes across 53 AMCs. No flows or holdings yet |
| **Currency** | 5 | 3 | **Yes** | RBI reference rates, ECB daily history for 30 currencies, spot for 166. No forward curve, no intraday |
| **Bonds / fixed income** | 7 | 2 | **Weak** | Policy corridor (repo, SDF, MSF, bank rate, reverse repo, CRR, SLR) and US yields. **No Indian G-sec yield curve** — the single biggest gap |
| **Macro** | 16 | 5 | **Yes, lagged** | RBI rates, FRED, World Bank, data.gov.in. CPI/IIP are archival, not current |
| **Real estate / housing** | 3 | **0** | **No** | Nothing wired. Three candidates catalogued |
| **Commodities** | 4 | 2 | **Yes** | Gold and silver from the LBMA daily fix (back to 1968); Brent, WTI, natural gas daily; copper, aluminium, wheat monthly. All shown in USD **and INR** |
| **Global equity & rates** | — | — | **Yes** | S&P 500, Nasdaq, Dow, VIX, US 2Y/10Y, fed funds, dollar index, and euro-area/Japan/UK 10-year yields |
| **World macro** | — | — | **Yes** | GDP growth, inflation, unemployment, debt and market-cap-to-GDP for **217 countries** |

## The system refuses rather than guesses

Ask about housing or gold and you get:

> **I don't have data for that yet.** I don't have a working data source for
> real estate yet, so I can't answer this honestly. I'd rather say that than
> guess.

This is deliberate and it is the whole point. A language model will cheerfully
answer a Mumbai property question from training-data memory, with confident
numbers and no source. That is the exact failure this system exists to prevent,
so `coverage_gap()` intercepts the question before any model sees it.

## The rupee lens

Every foreign price is also shown in rupees, converted at the **contemporaneous**
rate rather than today's, and `inr_return_decomposition()` splits a foreign
return into the asset move and the currency move.

This is not a cosmetic feature. Over the year to 2026-09-17 the S&P 500 returned
**+15.2% in dollars**, but the rupee weakened 8.9%, so an Indian investor
received **+25.4%** — the currency was **35% of the total return**. A global
tool that quotes only the dollar figure is telling an Indian reader the wrong
number.

```bash
vyuha world commodities     # gold, silver, crude, metals — in USD and INR
vyuha world indices         # S&P, Nasdaq, VIX, global rates
vyuha world inr sp500       # what a rupee investor actually earned
vyuha world country BRA     # macro for any of 217 countries
```

## The gaps, in priority order

**1. Indian G-sec yield curve — the biggest hole.** Without it there is no
duration risk, no curve positioning, no real fixed-income analytics. The stress
module already computes duration and convexity; it has no curve to apply them
to. Candidates: CCIL, FBIL, RBI DBIE. All need parsing work.

**2. Housing.** Three catalogued routes: the data.gov.in Housing Price Index
(resource id located, but the shared demo API key is quota-exhausted — get a
free key at data.gov.in/help), NHB RESIDEX (the canonical source, behind a JS
app and spreadsheets), and RBI's HPI (inside DBIE, no API). Housing is also
structurally hard in India: transaction prices are unreliable, circle rates
distort everything, and the indices lag by a quarter.

**3. Per-country equity indices.** World rates and US equity are covered, but
there is no good free source for daily equity indices across many countries —
Yahoo, which used to serve this, now hard-blocks (persistent HTTP 429). MCX for
Indian domestic gold and agri futures is also unwired; the LBMA fix is the
international price, which differs from the Indian landed price after duty.

**4. Individual stock fundamentals.** The factor model expects book-to-price,
ROE and promoter pledging. No fundamentals source is wired, so it currently
runs on price-derived characteristics only.

## Honest limits that apply to everything above

Even where coverage is good, see [PRECISION.md](PRECISION.md): no system can
resolve moves finer than the NSE's 5 paise tick, forecasts are calibrated
uncertainty rather than predictions, and the council is currently running all
members on one base model, which makes their agreement worth less than it looks.
