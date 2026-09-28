"""Tests for the standings report.

The risk this file guards against is not a wrong number. It is a number that
reads as a ranking when it is not one. Brier scores from different question
sets are not comparable, and a scoreboard that quietly implies otherwise is
marketing wearing a lab coat.
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

import pytest

from vyuha.benchmark.scoreboard import (
    MIN_FOR_A_NUMBER,
    MIN_FOR_COMPARISON,
    REFERENCES,
    render,
    standing,
)
from vyuha.council.scoring import TrackRecord


def track_with(n, skill, base_rate=0.3, seed=9):
    """A council of a given skill. skill=0 means it predicts the base rate."""
    rnd = random.Random(seed)
    tr = TrackRecord(Path(tempfile.mkdtemp()) / "t.jsonl")
    for i in range(n):
        truth = rnd.random() < base_rate
        if skill <= 0:
            p = base_rate
        else:
            p = base_rate + (skill if truth else -skill * base_rate / (1 - base_rate))
            p = min(max(p + rnd.gauss(0, 0.05), 0.02), 0.98)
        tr.record("__council__", f"q{i}", probability=p, outcome_binary=truth)
    return tr


def test_says_nothing_when_there_is_nothing_to_say():
    """The failure mode is inventing a number to fill the space."""
    s = standing(TrackRecord(Path(tempfile.mkdtemp()) / "empty.jsonl"))
    assert s.n_resolved == 0
    assert s.brier != s.brier          # NaN, not a fabricated 0
    assert "would be invented" in s.verdict
    assert "No resolved questions" in render(s)


def test_refuses_to_interpret_a_thin_record():
    s = standing(track_with(10, 0.3))
    assert "Too few" in s.verdict
    assert str(MIN_FOR_A_NUMBER) in s.verdict


def test_reports_negative_skill_bluntly():
    """A council worse than a constant must be told so, not cushioned."""
    rnd = random.Random(2)
    tr = TrackRecord(Path(tempfile.mkdtemp()) / "bad.jsonl")
    for i in range(60):
        truth = rnd.random() < 0.3
        # Deliberately anti-correlated.
        tr.record("__council__", f"q{i}",
                  probability=0.8 if not truth else 0.2, outcome_binary=truth)
    s = standing(tr)
    assert s.skill_vs_base_rate < 0
    assert "WORSE" in s.verdict and "adding nothing" in s.verdict


def test_skill_score_is_the_headline_comparable_number():
    """Raw Brier depends on question difficulty; skill vs base rate does not,
    which is why it is the number the report leads on."""
    easy = standing(track_with(200, 0.25, base_rate=0.05))
    hard = standing(track_with(200, 0.25, base_rate=0.50))
    # Very different raw Briers...
    assert abs(easy.brier - hard.brier) > 0.02
    # ...but both report a skill figure on the same scale.
    assert -1 <= easy.skill_vs_base_rate <= 1
    assert -1 <= hard.skill_vs_base_rate <= 1


def test_every_comparison_is_marked_not_comparable():
    """No single row may be quotable as a ranking."""
    s = standing(track_with(200, 0.3))
    assert s.comparisons
    for c in s.comparisons:
        assert c["comparable"] is False
        assert c["source"]


def test_caveats_are_present_and_specific():
    s = standing(track_with(200, 0.3))
    joined = " ".join(s.caveats)
    assert "not comparable across question sets" in joined
    assert "option-implied" in joined


def test_thin_records_get_an_extra_warning():
    s = standing(track_with(50, 0.3))
    assert any(str(MIN_FOR_COMPARISON) in c for c in s.caveats)


def test_rendered_report_cannot_be_read_as_a_league_table():
    s = standing(track_with(200, 0.3))
    out = render(s)
    assert "NOT a ranking" in out
    assert "FOR CONTEXT ONLY" in out
    assert "not comparable across question sets" in out


def test_references_are_sourced_and_ordered_sensibly():
    for r in REFERENCES:
        assert r.source and r.note
        assert 0.0 < r.brier <= 0.25
    names = {r.name for r in REFERENCES}
    assert "Always saying 50%" in names, "the floor must be shown"
    coin = next(r for r in REFERENCES if r.name == "Always saying 50%")
    assert coin.brier == pytest.approx(0.25)
    best = min(REFERENCES, key=lambda r: r.brier)
    assert best.brier >= 0.09, "no reference should imply near-perfection"


def test_calibration_and_resolution_are_reported():
    s = standing(track_with(200, 0.3))
    assert s.calibration_error == s.calibration_error
    assert s.resolution == s.resolution
