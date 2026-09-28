"""Letting the system tune itself, within limits.

Several of Vyuha's settings were chosen by argument rather than evidence: does
retrieval help or just cost six seconds? Is a four-member panel as good as ten?
Does the second deliberation round change anything? Each is answerable, and
none of them should be answered by whoever is writing the code that day.

So the daily loop randomises them. Each generated question is assigned to a
configuration variant; when it resolves, the variant inherits the Brier score.
After enough questions the comparison is real evidence.

WHAT THIS DELIBERATELY DOES NOT DO

It does not write code, and it does not merge anything. It tunes **parameters
within ranges a human set**, and nothing else. An agent that edits and deploys
its own source has failure modes that compound silently and invisibly, which
in a system that produces financial numbers is not a risk worth taking for the
convenience of skipping review.

It also refuses to declare a winner on thin evidence. With twenty questions the
difference between a better configuration and a luckier one is invisible, and a
loop that switches on noise will wander forever, each move looking justified.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from vyuha.config import settings

#: The settings the loop is permitted to vary, and the values it may choose.
#: Anything not listed here is fixed and stays that way until a human changes it.
ARMS: dict[str, list[Any]] = {
    "retrieval_enabled": [True, False],
    "min_panel": [4, 6],
    "rounds": [1, 2],
}

#: Below this many resolved questions per arm, no winner is declared.
MIN_PER_ARM = 30
#: Two-sided significance required before a default is changed.
ALPHA = 0.05


@dataclass(slots=True)
class ArmResult:
    name: str
    value: Any
    n: int = 0
    mean_brier: float = float("nan")
    std_error: float = float("nan")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class ExperimentResult:
    setting: str
    arms: list[ArmResult] = field(default_factory=list)
    winner: Any = None
    p_value: float = float("nan")
    decision: str = ""
    applied: bool = False

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["arms"] = [a.to_dict() for a in self.arms]
        return d


def assign(question_id: str, setting: str) -> Any:
    """Deterministically assign a question to an arm.

    Hashing the question id rather than drawing randomly means the assignment
    is reproducible: re-running the loop cannot quietly reassign a question to
    whichever arm currently looks better, which would bias every comparison.
    """
    options = ARMS[setting]
    h = hashlib.sha256(f"{setting}:{question_id}".encode()).hexdigest()
    return options[int(h[:8], 16) % len(options)]


def config_for(question_id: str) -> dict[str, Any]:
    """The full variant assignment for one question."""
    return {k: assign(question_id, k) for k in ARMS}


def _load_assignments(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def record_run(question_id: str, config: dict[str, Any],
               path: Path | None = None) -> None:
    """Note which variant answered a question, so the score can be attributed."""
    path = path or (settings.data_dir / "experiments.json")
    data = _load_assignments(path)
    data[question_id] = {"config": config,
                         "recorded_at": dt.datetime.now(dt.UTC).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def analyse(track, path: Path | None = None) -> list[ExperimentResult]:
    """Compare arms on the Brier score of the pooled council forecast."""
    path = path or (settings.data_dir / "experiments.json")
    assignments = _load_assignments(path)
    if not assignments:
        return []

    # Only the pooled verdict is compared. Individual members vary for reasons
    # unrelated to configuration, and averaging them in would add noise.
    scores: dict[str, float] = {}
    for row in track.rows:
        if row.get("member") == "__council__" and "brier" in row:
            scores[row["question_id"]] = float(row["brier"])
    if not scores:
        return []

    results: list[ExperimentResult] = []
    for setting, options in ARMS.items():
        buckets: dict[Any, list[float]] = {o: [] for o in options}
        for qid, brier in scores.items():
            cfg = assignments.get(qid, {}).get("config", {})
            val = cfg.get(setting)
            if val in buckets:
                buckets[val].append(brier)

        arms = []
        for val, xs in buckets.items():
            a = ArmResult(name=setting, value=val, n=len(xs))
            if xs:
                a.mean_brier = float(np.mean(xs))
                a.std_error = float(np.std(xs, ddof=1) / np.sqrt(len(xs))) if len(xs) > 1 else float("nan")
            arms.append(a)

        res = ExperimentResult(setting=setting, arms=arms)
        usable = [a for a in arms if a.n >= MIN_PER_ARM]
        if len(usable) < 2:
            have = ", ".join(f"{a.value}: {a.n}" for a in arms)
            res.decision = (
                f"not enough evidence ({have}); need {MIN_PER_ARM} per arm. "
                "Switching on fewer would be chasing noise."
            )
            results.append(res)
            continue

        best = min(usable, key=lambda a: a.mean_brier)
        rest = [a for a in usable if a is not best]
        a_scores = buckets[best.value]
        b_scores = [s for a in rest for s in buckets[a.value]]
        # Welch's t-test: the arms have no reason to share a variance.
        t, p = stats.ttest_ind(a_scores, b_scores, equal_var=False)
        res.winner = best.value
        res.p_value = float(p)
        if p < ALPHA:
            res.decision = (
                f"{setting}={best.value} scored better "
                f"({best.mean_brier:.4f} vs {np.mean(b_scores):.4f}, p={p:.4f})"
            )
        else:
            res.decision = (
                f"no significant difference (p={p:.3f}); keeping the current "
                "default rather than switching on a coin flip"
            )
        results.append(res)
    return results


def apply_winners(results: list[ExperimentResult],
                  out: Path | None = None) -> dict[str, Any]:
    """Write significant winners to a settings overlay the app reads at start.

    A file, not a code edit. It is readable, diffable, version-controlled and
    can be deleted to revert everything in one action -- none of which is true
    of a process that rewrites its own source.
    """
    out = out or (settings.data_dir / "tuned_settings.json")
    current = {}
    if out.exists():
        try:
            current = json.loads(out.read_text())
        except (json.JSONDecodeError, OSError):
            current = {}

    changed = {}
    for r in results:
        if r.winner is not None and r.p_value == r.p_value and r.p_value < ALPHA:
            if current.get(r.setting) != r.winner:
                changed[r.setting] = r.winner
            current[r.setting] = r.winner
            r.applied = True

    current["_updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    current["_note"] = (
        "Written by vyuha.learn.experiment from measured Brier scores. "
        "Delete this file to revert to code defaults."
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(current, indent=2, default=str))
    return {"applied": changed, "all_tuned": {k: v for k, v in current.items()
                                              if not k.startswith("_")}}


def load_tuned(path: Path | None = None) -> dict[str, Any]:
    """Settings the loop has earned the right to change."""
    path = path or (settings.data_dir / "tuned_settings.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and k in ARMS}
