# How Vyuha learns

Two separate things get called "learning", and only one of them makes the
system more accurate. Keeping them apart is the whole design.

## 1. Scoring (this is the one that matters)

The council has always carried the machinery — proper scoring rules,
per-member bias correction, performance-weighted pooling, a fittable
extremisation cap. **All of it was inert**, because nothing looked up what
actually happened. Every member was weighted equally forever.

`vyuha/learn/resolve.py` closes that loop:

1. find council runs whose resolution date has passed
2. resolve the outcome from the point-in-time store
3. score every member's forecast with a strictly proper rule
4. re-derive weights, bias corrections and the extremisation cap

Demonstrated on 60 simulated questions with a skilled member, a permabear and
a coin-flipper:

| member | weight | bias | Brier |
|---|---|---|---|
| sharp | **0.950** | +0.028 | 0.0233 |
| permabear | 0.029 | +0.720 | 0.1591 |
| noise | 0.020 | +0.192 | 0.2526 |

The weights recover the true skill ordering, and the permabear's systematic
over-statement is measured and subtracted rather than indulged.

### Why the thresholds exist

Re-fitting daily on a handful of outcomes chases noise and locks in whoever
was recently lucky. So nothing moves until there is evidence:

| parameter | minimum resolved questions |
|---|---|
| pooling weights | 25 |
| bias corrections | 30 |
| extremisation cap | 50 |

Below the threshold the old value stands and the report says why.

### A bug this surfaced

The original bias measure was `mean(logit(p) − logit(outcome))`. Since `logit`
of a 0/1 outcome is ±13.8 after clamping, that average is dominated by the
clamp constant and the base rate, not by the forecaster — a perfectly
calibrated member picked up a large spurious correction whenever the base rate
wasn't 0.5. It now measures calibration-in-the-large:
`mean(logit(p)) − logit(base_rate)`. A calibrated member reads ≈0.

## 2. Discovery (useful, but dangerous if unguarded)

**Adding variables does not make a system more accurate.** Usually the
opposite. Test 100 unrelated series against Nifty returns at p<0.05 and about
**five will look significant on pure noise**. A loop that discovers variables
daily and keeps whatever correlates accumulates spurious predictors forever,
grows more confident as it does, and gets worse. The failure is silent and it
compounds.

So discovery is a funnel with a statistical gate in the middle.

```
proposed → verified → validated → promoted
              ↓           ↓           ↑
           rejected    rejected   human only
```

**Proposed.** Two channels. *Registry diffing* snapshots official catalogues
(World Bank indicators, data.gov.in resources) and diffs them daily — anything
new is a fact, not a guess. *LLM hypotheses* are speculative, labelled as such,
and can never be promoted on that basis alone.

**Verified.** The endpoint must actually return parseable data. This is what
separates a real source from a plausible-looking URL.

**Validated.** Out-of-sample only, with a purge gap between train and test
(macro series are autocorrelated and adjacent observations leak), and
**Benjamini-Hochberg FDR correction across the whole batch**. Anything whose
relationship flips sign between fit and holdout is thrown out as a fluke.

**Promoted.** By a human, via pull request. Never automatically.

### The gate, demonstrated

61 candidates — 60 pure noise, 1 genuine signal:

```
4 of 61 cleared a naive p<0.05, and chance alone would produce about 3.1.
After FDR correction 1 survives.
survivors: ['real_signal']
noise survivors: 0
```

Three of the four naive "discoveries" were flukes. Without correction, three
junk variables would have entered the catalogue that day, and more the next.

### First real run

The loop verified seven previously-unwired India series on FRED's OECD
mirrors — CPI (819 observations), industrial production (346), the discount
rate (655), REER, exports, imports and GDP — partially closing the MOSPI gap
documented in [COVERAGE.md](COVERAGE.md).

It also **rejected** the India 10-year government bond yield: the endpoint
failed to return data. That is the single series the project most wants, and
the loop refused it rather than recording a dead URL as a source.

## The daily automation

`.github/workflows/daily-learn.yml` runs weekdays at 03:50 UTC — shortly after
the NSE opens at 09:15 IST.

```bash
python scripts/daily_learn.py --all              # everything
python scripts/daily_learn.py --resolve --retune # just the part that matters
```

What it does: resolve → retune → discover → verify → validate, then commit the
evidence (outcomes and scores are append-only facts) and open a **pull request**
if anything reached `validated`. Catalogue changes are never merged
automatically.

### Things that will bite you

- **Cron is best-effort.** GitHub routinely delays scheduled runs by 5–30
  minutes and occasionally skips them. Nothing may assume it ran.
- **Scheduled workflows are disabled after 60 days of repository inactivity.**
  If you stop merging, check the workflow is still enabled.
- **No Ollama on a hosted runner**, so the LLM hypothesis channel is off in CI.
  Resolution, retuning, registry discovery and validation need no model.
- **Snapshots must be cached.** Discovery works by diffing against yesterday;
  without the cache every run sees an empty baseline and reports the entire
  catalogue as new. The workflow caches `data/cache`.
- **data.gov.in's shared demo key is quota-limited.** Set
  `DATA_GOV_IN_KEY` as a repository secret for reliable discovery.

## What this still cannot do

It cannot establish causation. A validated candidate is *a correlation that
persisted out of sample after correcting for how many hypotheses were tested* —
which is a real and unusual bar, and still not a mechanism.

It cannot fix a panel whose members share one base model. Correlated advisors
produce correlated errors, and no amount of scoring repairs that; it needs
genuinely different models.

And it cannot start working until questions resolve. With 30-day horizons the
first weights are roughly a month away, and the thresholds mean meaningful
tuning needs several months of daily runs. That is the honest timeline.
