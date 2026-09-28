"""Generating the council's own practice questions.

The learning loop was starving. It could only learn from questions a human
happened to ask, those questions carried 30-to-90 day horizons, and a third of
them named no machine-resolvable source. At that rate the 25 resolved
questions needed before pooling weights move would arrive some time next year.

So the system asks itself questions. Every trading day it generates a batch
with **short horizons** (1, 3, 7 days), objective resolution sources, and
thresholds scaled to recent volatility. Those resolve within the week, and a
usable track record accumulates in a fortnight rather than two quarters.

THE PART THAT IS EASY TO GET WRONG

A generated question must be genuinely uncertain. "Will the Nifty fall below
half its current level tomorrow?" resolves NO every time; a forecaster learns
nothing from it, and a track record built on such questions reports
spectacular accuracy that means nothing. Calibration needs questions whose
answers are actually in doubt.

Thresholds are therefore placed at multiples of the expected move over the
horizon -- roughly 0.4, 0.8 and 1.3 standard deviations -- which puts the
implied probabilities in a band from around 10% to 35%. Both directions are
generated, so the base rate does not drift toward one answer and let a
forecaster score well by always saying the same thing.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from vyuha.council.schema import Question, QuestionKind, question_id_for
from vyuha.store.pit import PITStore

#: Series that can be auto-resolved, with a fallback annualised volatility for
#: sizing thresholds before enough history exists to measure it.
TRACKED: dict[str, dict[str, Any]] = {
    "NIFTY50_CLOSE": {"label": "the Nifty 50", "vol": 0.13, "dp": 0},
    "BANKNIFTY_CLOSE": {"label": "the Bank Nifty", "vol": 0.16, "dp": 0},
    "INDIA_VIX": {"label": "India VIX", "vol": 0.60, "dp": 1},
    "USDINR": {"label": "the rupee (USD/INR)", "vol": 0.05, "dp": 2},
    "GOLD_USD": {"label": "gold", "vol": 0.16, "dp": 0},
    "BRENT_USD": {"label": "Brent crude", "vol": 0.30, "dp": 1},
}

HORIZONS_DAYS = (1, 3, 7)
#: Threshold distances in standard deviations of the horizon move. Chosen to
#: land implied probabilities roughly between 10% and 35% -- uncertain enough
#: to be informative, not so uncertain as to be a coin toss.
SIGMA_STEPS = (0.4, 0.8, 1.3)


@dataclass(slots=True)
class GenerationReport:
    generated: int = 0
    questions: list[Question] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"generated {self.generated} question(s)"
                + (f"; skipped {len(self.skipped)}" if self.skipped else ""))


def realised_vol(series_id: str, store: PITStore, days: int = 120) -> float | None:
    """Annualised volatility from whatever history the store holds."""
    df = store.as_of(dt.datetime.now(), series_id=series_id,
                     start=dt.date.today() - dt.timedelta(days=days))
    if df.empty or len(df) < 20:
        return None
    s = (df.sort_values("event_date")
           .drop_duplicates("event_date", keep="last")
           .set_index("event_date")["value"].astype(float))
    r = np.log(s / s.shift(1)).dropna()
    if len(r) < 15 or r.std() == 0:
        return None
    return float(r.std() * math.sqrt(252))


def latest_value(series_id: str, store: PITStore) -> float | None:
    df = store.as_of(dt.datetime.now(), series_id=series_id,
                     start=dt.date.today() - dt.timedelta(days=30))
    if df.empty:
        return None
    v = pd.to_numeric(df.sort_values("event_date")["value"], errors="coerce").dropna()
    return float(v.iloc[-1]) if len(v) else None


def generate(
    store: PITStore | None = None,
    series: list[str] | None = None,
    horizons: tuple[int, ...] = HORIZONS_DAYS,
    per_series: int = 2,
    today: dt.date | None = None,
) -> GenerationReport:
    """Build today's batch of self-posed, objectively resolvable questions."""
    own = store is None
    store = store or PITStore()
    today = today or dt.date.today()
    report = GenerationReport()
    rng = np.random.default_rng(int(today.strftime("%Y%m%d")))
    # Identical (horizon, step, direction) draws produce identical text and
    # therefore an identical id, so a naive batch silently collapses -- 40
    # generated questions yielded 16 distinct ones. Duplicates cost council
    # time and teach nothing, so combinations are drawn WITHOUT replacement.
    seen_ids: set[str] = set()

    try:
        for sid in (series or list(TRACKED)):
            spec = TRACKED.get(sid)
            if spec is None:
                report.skipped.append(f"{sid}: not in the tracked set")
                continue
            spot = latest_value(sid, store)
            if spot is None or spot <= 0:
                report.skipped.append(f"{sid}: no recent value in the store")
                continue

            vol = realised_vol(sid, store) or spec["vol"]
            combos = [(h, st, b) for h in horizons for st in SIGMA_STEPS
                      for b in (True, False)]
            rng.shuffle(combos)
            made = 0
            for horizon, step, below in combos:
                if made >= per_series:
                    break

                sigma = vol * math.sqrt(horizon / 252.0)
                move = spot * sigma * step
                level = spot - move if below else spot + move
                dp = spec["dp"]
                level = round(level, dp) if dp else round(level / 10) * 10

                direction = "below" if below else "above"
                resolves = today + dt.timedelta(days=horizon)
                text = (
                    f"Will {spec['label']} trade {direction} "
                    f"{level:,.{dp}f} at any point on or before {resolves}?"
                )
                q = Question(
                    id=question_id_for(text, resolves),
                    kind=QuestionKind.BINARY,
                    text=text,
                    resolution_criteria=(
                        f"Resolves YES if the recorded value of {sid} is "
                        f"{direction} {level:,.{dp}f} on any day from {today} "
                        f"through {resolves} inclusive."
                    ),
                    resolution_date=resolves,
                    resolution_source=sid,
                    tags=["auto", f"h{horizon}", direction],
                )
                if q.id in seen_ids:
                    continue
                seen_ids.add(q.id)
                report.questions.append(q)
                made += 1
            report.generated += made
    finally:
        if own:
            store.close()
    return report


# --------------------------------------------------------------- resolution


def resolve_generated(question: dict, store: PITStore | None = None,
                      today: dt.date | None = None) -> tuple[bool | None, str]:
    """Resolve an auto-generated question from recorded history.

    Parses the threshold and direction out of the resolution criteria we wrote
    ourselves, rather than out of free-form question text -- which is why
    generated questions are reliably resolvable and hand-written ones often
    are not.
    """
    import re

    own = store is None
    store = store or PITStore(read_only=True)
    try:
        sid = str(question.get("resolution_source") or "")
        criteria = str(question.get("resolution_criteria", ""))
        m = re.search(r"is\s+(below|above)\s+([\d,]+(?:\.\d+)?)", criteria)
        if not sid or not m:
            return None, "not an auto-generated question"
        direction, level = m.group(1), float(m.group(2).replace(",", ""))

        try:
            resolves = dt.date.fromisoformat(str(question["resolution_date"]))
        except (KeyError, TypeError, ValueError):
            return None, "unparseable resolution date"

        today = today or dt.date.today()
        if resolves > today:
            return None, "not yet due"

        df = store.as_of(
            dt.datetime.now(), series_id=sid,
            start=resolves - dt.timedelta(days=30), end=resolves,
        )
        if df.empty:
            return None, f"no recorded values of {sid} in the window"
        vals = pd.to_numeric(df["value"], errors="coerce").dropna()
        if vals.empty:
            return None, f"{sid} has no numeric values in the window"

        hit = bool((vals < level).any()) if direction == "below" else bool((vals > level).any())
        return hit, (
            f"{len(vals)} observation(s); range {vals.min():.4g}-{vals.max():.4g} "
            f"vs threshold {level:.4g} ({direction})"
        )
    finally:
        if own:
            store.close()
