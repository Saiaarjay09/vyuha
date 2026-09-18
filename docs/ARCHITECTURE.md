# Architecture

```
                 ┌──────────────────────────────────────────┐
   free / open   │  ingest/   catalogue.py  (36 sources)    │
   data sources  │            base.py       (cache, throttle,│
   NSE, RBI,     │                           per-host UA)    │
   MOSPI, AMFI,  │            sources.py    (fetchers)       │
   FRED, GDELT,  └────────────────────┬─────────────────────┘
   Grid-India…                        │
                                      ▼
                 ┌──────────────────────────────────────────┐
                 │  store/pit.py  BITEMPORAL DUCKDB          │
                 │  (event_date, available_at, revision)     │
                 │  as_of(t) → only what was knowable at t   │
                 └────────────────────┬─────────────────────┘
                                      │
                    ┌─────────────────┴──────────────────┐
                    ▼                                    ▼
      ┌──────────────────────────┐        ┌──────────────────────────┐
      │  risk/                   │        │  council/                │
      │   covariance  factors    │        │   personas  (10 biases)  │
      │   var         stress     │───────▶│   evidence  (cited IDs)  │
      │   liquidity   returns    │ packet │   debate    (N rounds)   │
      └────────────┬─────────────┘        │   aggregate (log pool)   │
                   │                      │   scoring   (Brier/CRPS) │
                   ▼                      └────────────┬─────────────┘
      ┌──────────────────────────┐                     │
      │  backtest/var_tests.py   │                     ▼
      │  Kupiec, Christoffersen  │        ┌──────────────────────────┐
      │  Basel traffic light     │        │  CouncilVerdict          │
      └──────────────────────────┘        │  + dispersion + dissent  │
                                          │  + run log (auditable)   │
                                          └──────────────────────────┘
```

## Why the store is bitemporal

Every observation carries `event_date` (what it describes) and `available_at`
(when it became public). `as_of(t)` returns only the highest revision visible at
`t`. This is not a nicety — it is the difference between a backtest and a
fiction. India's release calendar makes it acute: CPI lands ~12 days after the
month it describes and is revised twice; IIP lands ~42 days later; GDP is
restated for years.

If you cannot state when a number became public, it does not go in the store.

## Why the evidence packet is frozen

Council members never query the database and never browse. They get a numbered,
hashed packet built `as_of` a timestamp, and must cite items by ID. This gives
three properties at once: no lookahead in a council backtest, no fabricated
figures (a citation to an ID we never issued is flagged), and full
reproducibility — the run log stores the packet fingerprint, so any past
verdict can be reconstructed exactly.

## Data flow invariants

1. A fetcher never returns a silently-empty frame. Missing data raises.
2. Nothing is imputed. A gap stays a gap and is reported in `coverage()`.
3. Risk outputs carry their own diagnostics (shrinkage applied, effective
   observations, estimator disagreement, rejected corrections).
4. The council's dispersion is returned with every verdict and is never
   collapsed into the point estimate.
