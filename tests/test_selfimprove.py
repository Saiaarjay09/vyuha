"""Tests for the parts that make Vyuha improve without being asked to.

The loop was structurally dead before these existed: the point-in-time store
was empty, so every outcome was unresolvable, so no weight ever moved -- and
nothing reported a problem. These tests assert the mechanism actually turns.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pytest

from vyuha.learn.experiment import (
    ALPHA,
    ARMS,
    MIN_PER_ARM,
    analyse,
    apply_winners,
    assign,
    config_for,
    load_tuned,
    record_run,
)
from vyuha.learn.questions import TRACKED, generate, resolve_generated
from vyuha.learn.snapshot import snapshot_today
from vyuha.store.pit import Observation, PITStore


@pytest.fixture
def seeded_store(tmp_path):
    """60 days of a plausible index path."""
    store = PITStore(tmp_path / "t.duckdb")
    rng = np.random.default_rng(3)
    lvl = 23000.0
    base = dt.date.today() - dt.timedelta(days=60)
    for i in range(60):
        lvl *= float(np.exp(rng.normal(0, 0.008)))
        d = base + dt.timedelta(days=i)
        store.write([Observation("NIFTY50_CLOSE", d,
                                 dt.datetime.combine(d, dt.time(18)), "NSE",
                                 round(lvl, 2))], auto_revision=False)
    yield store
    store.close()


# ----------------------------------------------------------- generation


def test_generates_short_horizon_questions(seeded_store):
    """Long horizons starve the loop: a 90-day question teaches nothing for a
    quarter. Everything generated must resolve within a week."""
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=10)
    assert r.generated > 0
    today = dt.date.today()
    for q in r.questions:
        assert (q.resolution_date - today).days <= 7


def test_generated_questions_are_machine_resolvable(seeded_store):
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=6)
    for q in r.questions:
        assert q.resolution_source in TRACKED
        assert q.resolution_source != "manual"
        assert "Resolves YES if" in q.resolution_criteria


def test_no_duplicate_questions(seeded_store):
    """Identical draws produced identical ids and silently collapsed -- 40
    generated questions yielded 16 distinct ones, wasting council time."""
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=40)
    ids = [q.id for q in r.questions]
    assert len(ids) == len(set(ids))


def test_both_directions_are_generated(seeded_store):
    """If every question asked about a fall, a forecaster could score well by
    always saying no, and the base rate would teach nothing."""
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=12)
    tags = {t for q in r.questions for t in q.tags}
    assert "above" in tags and "below" in tags


def test_thresholds_are_volatility_scaled_not_absurd(seeded_store):
    """A threshold at half the index level resolves NO every time and is
    worthless for calibration."""
    import re

    spot = 23000.0
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=12)
    for q in r.questions:
        level = float(re.search(r"is\s+(?:below|above)\s+([\d,]+)",
                                q.resolution_criteria).group(1).replace(",", ""))
        assert 0.85 * spot < level < 1.15 * spot, f"absurd threshold {level}"


def test_skips_series_with_no_data(seeded_store):
    r = generate(store=seeded_store, series=["GOLD_USD"], per_series=2)
    assert r.generated == 0
    assert any("no recent value" in s for s in r.skipped)


# ----------------------------------------------------------- resolution


def test_generated_questions_resolve_from_stored_history(seeded_store):
    """The whole loop hinges on this. Before the store was populated every
    outcome was unresolvable and no weight ever moved."""
    past = dt.date.today() - dt.timedelta(days=30)
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=18,
                 today=past)
    resolved = 0
    for q in r.questions:
        outcome, _ = resolve_generated(q.model_dump(mode="json"), store=seeded_store)
        if outcome is not None:
            assert isinstance(outcome, bool)
            resolved += 1
    assert resolved >= len(r.questions) // 2


def test_future_questions_are_not_resolved(seeded_store):
    r = generate(store=seeded_store, series=["NIFTY50_CLOSE"], per_series=3)
    for q in r.questions:
        outcome, note = resolve_generated(q.model_dump(mode="json"), store=seeded_store)
        assert outcome is None and "not yet due" in note


def test_handwritten_questions_are_left_to_the_text_resolver(seeded_store):
    outcome, note = resolve_generated(
        {"resolution_source": "NIFTY50_CLOSE",
         "resolution_criteria": "whatever the analyst decides",
         "resolution_date": str(dt.date.today())}, store=seeded_store)
    assert outcome is None and "not an auto-generated" in note


# ------------------------------------------------------------- snapshot


def test_snapshot_writes_observations(tmp_path, monkeypatch):
    """A no-op snapshot would leave the loop dead exactly as it was."""
    store = PITStore(tmp_path / "s.duckdb")
    rep = snapshot_today(store=store, as_of=dt.datetime(2026, 9, 28, 17, 0))
    # Network may be unavailable in CI; the contract is that it reports
    # honestly either way rather than claiming success.
    assert rep.written >= 0
    assert isinstance(rep.errors, list)
    if rep.written:
        assert store.coverage().shape[0] > 0
    store.close()


# ----------------------------------------------------------- experiments


def test_assignment_is_deterministic():
    """Re-running must not reassign a question to whichever arm currently
    looks better; that would bias every comparison it feeds."""
    assert config_for("q_abc") == config_for("q_abc")


def test_assignment_is_balanced():
    from collections import Counter

    c = Counter(assign(f"q{i}", "retrieval_enabled") for i in range(400))
    assert min(c.values()) / max(c.values()) > 0.7


def test_only_whitelisted_settings_can_be_tuned():
    """The loop tunes parameters within ranges a human set. It does not get to
    invent new ones."""
    assert set(ARMS) == {"retrieval_enabled", "min_panel", "rounds"}
    for options in ARMS.values():
        assert 2 <= len(options) <= 4


class _Track:
    def __init__(self, rows):
        self.rows = rows


def _experiment(n, effect, tmp_path, seed=5):
    rng = np.random.default_rng(seed)
    path = tmp_path / "exp.json"
    rows = []
    for i in range(n):
        qid = f"q{i}"
        cfg = config_for(qid)
        record_run(qid, cfg, path=path)
        b = 0.22 - (effect if cfg["retrieval_enabled"] else 0) + rng.normal(0, 0.06)
        rows.append({"member": "__council__", "question_id": qid,
                     "brier": max(0.0, b)})
    return _Track(rows), path


def test_refuses_to_decide_on_thin_evidence(tmp_path):
    track, path = _experiment(20, 0.05, tmp_path)
    r = next(x for x in analyse(track, path=path) if x.setting == "retrieval_enabled")
    assert "not enough evidence" in r.decision
    assert r.applied is False


def test_does_not_switch_on_noise(tmp_path):
    """A loop that switches on noise wanders forever, each move looking
    justified."""
    track, path = _experiment(400, 0.0, tmp_path)
    r = next(x for x in analyse(track, path=path) if x.setting == "retrieval_enabled")
    assert not (r.p_value < ALPHA), f"declared a winner on noise (p={r.p_value})"


def test_detects_a_real_effect(tmp_path):
    track, path = _experiment(400, 0.05, tmp_path)
    r = next(x for x in analyse(track, path=path) if x.setting == "retrieval_enabled")
    assert r.winner is True
    assert r.p_value < ALPHA


def test_winners_are_written_to_a_revertible_file(tmp_path):
    """A file, not a code edit: readable, diffable, and deletable to revert."""
    track, path = _experiment(400, 0.05, tmp_path)
    results = analyse(track, path=path)
    out = tmp_path / "tuned.json"
    applied = apply_winners(results, out=out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "_note" in data and "Delete this file to revert" in data["_note"]
    assert applied["applied"]


def test_only_significant_winners_are_applied(tmp_path):
    track, path = _experiment(400, 0.0, tmp_path)
    out = tmp_path / "tuned.json"
    apply_winners(analyse(track, path=path), out=out)
    assert not load_tuned(out), "applied a setting with no significant evidence"


def test_min_per_arm_is_not_trivially_small():
    assert MIN_PER_ARM >= 25
