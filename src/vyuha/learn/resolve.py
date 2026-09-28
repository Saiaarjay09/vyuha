"""The loop that actually makes Vyuha more accurate.

Everything else in this package is optional. This is not.

The council already carries scoring machinery -- proper scoring rules,
per-member bias correction, performance-weighted pooling, a fittable
extremisation cap. All of it is inert until something closes the loop by
looking up what actually happened and writing the outcome back. Without this
module every member is weighted equally forever and the system cannot improve
no matter how much data you add to it.

The order of operations matters and is easy to get wrong:

  1. find questions whose resolution date has passed
  2. resolve them from the point-in-time store, using only data that was
     published *after* the resolution date -- the outcome is a fact about the
     world, so unlike a forecast it may use late-arriving data
  3. score every member's forecast against the outcome
  4. re-derive weights, bias corrections and the extremisation cap

Step 4 is deliberately conservative. Re-tuning on twelve resolved questions
would fit noise and lock in whichever member happened to be lucky, so the
thresholds below refuse to move anything until there is enough evidence.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from vyuha.config import settings
from vyuha.council.scoring import TrackRecord

#: Below this many resolved questions the derived parameters are not trusted.
MIN_FOR_WEIGHTS = 25
MIN_FOR_BIAS = 30
MIN_FOR_EXTREMISE = 50


@dataclass(slots=True)
class ResolutionReport:
    checked: int = 0
    resolved: int = 0
    still_pending: int = 0
    unresolvable: int = 0
    scored_forecasts: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def summary(self) -> str:
        return (
            f"checked {self.checked} run(s): resolved {self.resolved}, "
            f"pending {self.still_pending}, unresolvable {self.unresolvable}, "
            f"{self.scored_forecasts} member forecasts scored"
        )


def _load_runs(log_dir: Path) -> list[dict]:
    runs = []
    for p in sorted(log_dir.glob("*.json")):
        if p.name in ("resolutions.json", "tuning.json"):
            continue
        try:
            runs.append({"path": p, **json.loads(p.read_text())})
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def _already_resolved(log_dir: Path) -> set[str]:
    f = log_dir / "resolutions.json"
    if not f.exists():
        return set()
    try:
        return {r["run_id"] for r in json.loads(f.read_text())}
    except (json.JSONDecodeError, OSError):
        return set()


def _append_resolution(log_dir: Path, record: dict) -> None:
    f = log_dir / "resolutions.json"
    existing = []
    if f.exists():
        try:
            existing = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.append(record)
    f.write_text(json.dumps(existing, indent=2, default=str))


def resolve_outcome_from_store(
    series_id: str, resolution_date: dt.date, threshold: float | None,
    direction: str = "below", store: Any = None,
) -> tuple[bool | None, str]:
    """Look up whether a level was breached, from the point-in-time store.

    Unlike a forecast, an outcome is allowed to use data published after the
    event -- we are establishing what happened, not what was knowable.
    Returns (outcome, note); outcome is None when the data is not there.
    """
    from vyuha.store.pit import PITStore

    own = store is None
    store = store or PITStore(read_only=False)
    try:
        df = store.as_of(
            dt.datetime.now(), series_id=series_id,
            start=resolution_date - dt.timedelta(days=400), end=resolution_date,
        )
        if df.empty:
            return None, f"no observations of {series_id} up to {resolution_date}"
        vals = pd.to_numeric(df["value"], errors="coerce").dropna()
        if vals.empty:
            return None, f"{series_id} has no numeric values in the window"
        if threshold is None:
            return None, "no threshold to compare against"
        hit = bool((vals < threshold).any()) if direction == "below" \
            else bool((vals > threshold).any())
        return hit, (
            f"{len(vals)} observations; min {vals.min():.4g}, max {vals.max():.4g}, "
            f"threshold {threshold:.4g} ({direction})"
        )
    finally:
        if own:
            store.close()


def resolve_due(
    log_dir: Path | None = None,
    today: dt.date | None = None,
    track: TrackRecord | None = None,
    resolver=None,
) -> ResolutionReport:
    """Resolve every council run whose date has passed, and score its members.

    ``resolver`` is a callable ``(question_dict) -> (outcome | None, note)``.
    The default reads the point-in-time store. Injecting one lets a test drive
    the whole loop without a database, and lets you resolve questions whose
    outcome lives somewhere the store does not reach.
    """
    log_dir = log_dir or settings.council_log_dir
    today = today or dt.date.today()
    track = track or TrackRecord(log_dir / "track_record.jsonl")
    resolver = resolver or _default_resolver

    report = ResolutionReport()
    done = _already_resolved(log_dir)

    for run in _load_runs(log_dir):
        q = run.get("question") or {}
        run_id = run.get("run_id")
        if not run_id or run_id in done:
            continue
        report.checked += 1

        try:
            rdate = dt.date.fromisoformat(str(q.get("resolution_date")))
        except (TypeError, ValueError):
            report.unresolvable += 1
            report.errors.append(f"{run_id}: unparseable resolution_date")
            continue

        if rdate > today:
            report.still_pending += 1
            continue

        try:
            outcome, note = resolver(q)
        except Exception as exc:  # noqa: BLE001 - one bad run must not stop the loop
            report.unresolvable += 1
            report.errors.append(f"{run_id}: {exc}")
            continue

        if outcome is None:
            report.unresolvable += 1
            report.details.append({"run_id": run_id, "status": "unresolvable", "note": note})
            continue

        verdict = run.get("verdict") or {}
        scored = 0
        for fc in verdict.get("member_forecasts", []):
            if not fc.get("parse_ok") or fc.get("probability") is None:
                continue
            try:
                track.record(
                    member=fc["member"], question_id=q.get("id", run_id),
                    probability=float(fc["probability"]),
                    outcome_binary=bool(outcome),
                    resolved_at=dt.datetime.now(dt.UTC),
                )
                scored += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{run_id}/{fc.get('member')}: {exc}")

        # The pooled verdict is scored too, under a reserved name, so the
        # council as a whole can be compared against its own members.
        if verdict.get("probability") is not None:
            try:
                track.record(
                    member="__council__", question_id=q.get("id", run_id),
                    probability=float(verdict["probability"]),
                    outcome_binary=bool(outcome),
                    resolved_at=dt.datetime.now(dt.UTC),
                )
            except Exception:  # noqa: BLE001
                pass

        report.resolved += 1
        report.scored_forecasts += scored
        record = {
            "run_id": run_id, "question_id": q.get("id"),
            "question": q.get("text"), "resolution_date": str(rdate),
            "outcome": bool(outcome), "note": note,
            "council_probability": verdict.get("probability"),
            "members_scored": scored,
            "resolved_at": dt.datetime.now(dt.UTC).isoformat(),
        }
        _append_resolution(log_dir, record)
        report.details.append({"run_id": run_id, "status": "resolved", **record})

    return report


def _default_resolver(q: dict) -> tuple[bool | None, str]:
    """Resolve a question, preferring the structured path.

    Auto-generated questions carry a resolution criterion we wrote ourselves,
    in a fixed form, so they parse reliably. Hand-written ones have to be read
    out of free-form text, which frequently fails -- and a question that
    cannot be resolved teaches the system nothing. That asymmetry is the main
    argument for the council posing most of its own questions.
    """
    from vyuha.learn.questions import resolve_generated

    outcome, note = resolve_generated(q)
    if outcome is not None or "not an auto-generated" not in note:
        return outcome, note
    return _text_resolver(q)


def _text_resolver(q: dict) -> tuple[bool | None, str]:
    """Resolve from the point-in-time store by parsing the question text.

    Deliberately narrow: it only handles questions of the form "... below/above
    <number> ..." against a named series. Anything it cannot parse confidently
    is returned as unresolvable rather than guessed, because a wrong outcome
    silently corrupts every future weight derived from it.
    """
    import re

    text = str(q.get("text", ""))
    series = str(q.get("resolution_source") or "")
    if not series or series == "manual":
        return None, "no machine-resolvable source on this question"

    m = re.search(r"\b(below|under|above|over)\b[^\d]{0,12}([\d,]+(?:\.\d+)?)", text, re.I)
    if not m:
        return None, "could not parse a threshold from the question text"
    direction = "below" if m.group(1).lower() in ("below", "under") else "above"
    threshold = float(m.group(2).replace(",", ""))

    try:
        rdate = dt.date.fromisoformat(str(q.get("resolution_date")))
    except (TypeError, ValueError):
        return None, "unparseable resolution date"

    return resolve_outcome_from_store(series, rdate, threshold, direction)


# ------------------------------------------------------------------- retuning


def retune(track: TrackRecord | None = None, log_dir: Path | None = None) -> dict[str, Any]:
    """Re-derive pooling weights, bias corrections and the extremisation cap.

    Every parameter has a minimum sample size, and below it the old value
    stands. This is the guard against the most tempting failure in an
    automated loop: re-fitting daily on a handful of outcomes, chasing noise,
    and converging on whichever member was recently lucky.
    """
    log_dir = log_dir or settings.council_log_dir
    track = track or TrackRecord(log_dir / "track_record.jsonl")

    members = [m for m in track.members() if m != "__council__"]
    n_questions = len({r["question_id"] for r in track.rows})

    out: dict[str, Any] = {
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "resolved_questions": n_questions,
        "members": len(members),
        "applied": {},
        "withheld": {},
    }

    if n_questions >= MIN_FOR_WEIGHTS and members:
        out["applied"]["weights"] = track.weights(members)
    else:
        out["withheld"]["weights"] = (
            f"{n_questions} resolved questions; need {MIN_FOR_WEIGHTS}. "
            "Members stay equally weighted."
        )

    if n_questions >= MIN_FOR_BIAS and members:
        out["applied"]["bias_corrections"] = track.bias_corrections(members)
    else:
        out["withheld"]["bias_corrections"] = (
            f"{n_questions} resolved questions; need {MIN_FOR_BIAS}."
        )

    if n_questions >= MIN_FOR_EXTREMISE:
        panels = _panels_from_track(track)
        if panels:
            from vyuha.council.aggregate import fit_extremise_cap

            cap, grid = fit_extremise_cap(panels)
            out["applied"]["extremise_cap"] = cap
            out["applied"]["extremise_grid"] = grid
    else:
        out["withheld"]["extremise_cap"] = (
            f"{n_questions} resolved questions; need {MIN_FOR_EXTREMISE}."
        )

    # How the pooled council scored against its own members, which is the
    # honest test of whether aggregation is adding anything at all.
    council = track.score("__council__")
    if council.n:
        member_briers = [track.score(m).mean_brier for m in members]
        member_briers = [b for b in member_briers if b == b]
        out["council_vs_members"] = {
            "council_brier": council.mean_brier,
            "best_member_brier": min(member_briers) if member_briers else None,
            "mean_member_brier": (
                sum(member_briers) / len(member_briers) if member_briers else None
            ),
            "aggregation_is_helping": bool(
                member_briers and council.mean_brier < sum(member_briers) / len(member_briers)
            ),
        }

    (log_dir / "tuning.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def _panels_from_track(track: TrackRecord) -> list[tuple[list[float], bool]]:
    by_q: dict[str, tuple[list[float], bool]] = {}
    for r in track.rows:
        if r.get("kind") != "binary" or r["member"] == "__council__":
            continue
        qid = r["question_id"]
        probs, _ = by_q.get(qid, ([], bool(r["y"])))
        probs.append(float(r["p"]))
        by_q[qid] = (probs, bool(r["y"]))
    return [v for v in by_q.values() if len(v[0]) >= 2]
