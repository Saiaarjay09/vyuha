import datetime as dt
import json
import random

import numpy as np
import pandas as pd
import pytest

from vyuha.council.scoring import TrackRecord
from vyuha.learn.registry import CandidateRecord, CandidateRegistry
from vyuha.learn.resolve import (
    MIN_FOR_BIAS,
    MIN_FOR_EXTREMISE,
    MIN_FOR_WEIGHTS,
    resolve_due,
    retune,
)
from vyuha.learn.validate import (
    adjusted_pvalues,
    benjamini_hochberg,
    expected_false_positives,
    summarise,
    validate_candidates,
    validate_one,
)


def _make_runs(tmp_path, n=60, seed=7):
    """Synthetic council history: one skilled member, one biased, one useless."""
    rng = random.Random(seed)
    truths = {}
    for i in range(n):
        truth = rng.random() < 0.35
        truths[f"q{i}"] = truth
        members = [
            {"member": name, "model": "m", "parse_ok": True,
             "probability": min(max(p + rng.gauss(0, 0.05), 0.01), 0.99)}
            for name, p in [
                ("sharp", 0.85 if truth else 0.15),
                ("permabear", min(0.95, (0.85 if truth else 0.15) + 0.35)),
                ("noise", 0.5),
            ]
        ]
        (tmp_path / f"r{i}.json").write_text(json.dumps({
            "run_id": f"r{i}",
            "question": {"id": f"q{i}", "text": f"Will X close below {1000+i} points?",
                         "resolution_date": str(dt.date.today() - dt.timedelta(days=5)),
                         "resolution_source": "TEST"},
            "verdict": {"probability": sum(m["probability"] for m in members) / 3,
                        "member_forecasts": members},
        }))
    return truths


# ------------------------------------------------------------- the loop


def test_the_loop_closes(tmp_path):
    """Without this the whole scoring apparatus is inert."""
    truths = _make_runs(tmp_path)
    track = TrackRecord(tmp_path / "tr.jsonl")
    rep = resolve_due(log_dir=tmp_path, track=track,
                      resolver=lambda q: (truths[q["id"]], "sim"))
    assert rep.resolved == 60
    assert rep.scored_forecasts == 180
    assert len(track.rows) > 180  # members + the pooled council


def test_resolution_is_idempotent(tmp_path):
    """A daily job reruns constantly; double-scoring would corrupt every weight."""
    truths = _make_runs(tmp_path, n=10)
    track = TrackRecord(tmp_path / "tr.jsonl")
    r1 = resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    n_after_first = len(track.rows)
    r2 = resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    assert r1.resolved == 10
    assert r2.resolved == 0 and r2.checked == 0
    assert len(track.rows) == n_after_first


def test_future_questions_stay_pending(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({
        "run_id": "future", "question": {
            "id": "qf", "text": "Will X close below 100 points?",
            "resolution_date": str(dt.date.today() + dt.timedelta(days=30)),
            "resolution_source": "TEST"},
        "verdict": {"probability": 0.4, "member_forecasts": []}}))
    rep = resolve_due(log_dir=tmp_path, track=TrackRecord(tmp_path / "t.jsonl"),
                      resolver=lambda q: (True, "should not be called"))
    assert rep.still_pending == 1 and rep.resolved == 0


def test_unresolvable_questions_do_not_poison_the_record(tmp_path):
    """A wrong outcome is worse than no outcome -- it corrupts every later weight."""
    (tmp_path / "r.json").write_text(json.dumps({
        "run_id": "vague", "question": {
            "id": "qv", "text": "Will the market feel optimistic?",
            "resolution_date": str(dt.date.today() - dt.timedelta(days=1)),
            "resolution_source": "TEST"},
        "verdict": {"probability": 0.5, "member_forecasts": [
            {"member": "a", "model": "m", "probability": 0.5, "parse_ok": True}]}}))
    track = TrackRecord(tmp_path / "t.jsonl")
    rep = resolve_due(log_dir=tmp_path, track=track,
                      resolver=lambda q: (None, "cannot resolve"))
    assert rep.unresolvable == 1 and rep.resolved == 0
    assert track.rows == []


def test_one_bad_run_does_not_stop_the_batch(tmp_path):
    truths = _make_runs(tmp_path, n=5)

    def flaky(q):
        if q["id"] == "q2":
            raise RuntimeError("upstream exploded")
        return truths[q["id"]], "ok"

    rep = resolve_due(log_dir=tmp_path, track=TrackRecord(tmp_path / "t.jsonl"),
                      resolver=flaky)
    assert rep.resolved == 4 and rep.unresolvable == 1
    assert any("exploded" in e for e in rep.errors)


# ----------------------------------------------------------- retuning


def test_retune_learns_who_is_good(tmp_path):
    truths = _make_runs(tmp_path)
    track = TrackRecord(tmp_path / "tr.jsonl")
    resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    out = retune(track=track, log_dir=tmp_path)
    w = out["applied"]["weights"]
    assert w["sharp"] > w["permabear"] > w["noise"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_bias_measure_is_not_dominated_by_the_base_rate(tmp_path):
    """A calibrated member must show ~0 bias even when the base rate is not 0.5.

    The naive mean(logit(p) - logit(y)) is dominated by the clamp constant and
    hands a well-calibrated forecaster a large spurious correction.
    """
    truths = _make_runs(tmp_path)
    track = TrackRecord(tmp_path / "tr.jsonl")
    resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    b = retune(track=track, log_dir=tmp_path)["applied"]["bias_corrections"]
    assert abs(b["sharp"]) < 0.25, f"calibrated member got bias {b['sharp']}"
    assert b["permabear"] > b["sharp"], "the permabear must read as biased high"


def test_retune_withholds_everything_on_thin_evidence(tmp_path):
    truths = _make_runs(tmp_path, n=5)
    track = TrackRecord(tmp_path / "tr.jsonl")
    resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    out = retune(track=track, log_dir=tmp_path)
    assert out["applied"] == {}
    assert {"weights", "bias_corrections", "extremise_cap"} <= set(out["withheld"])


def test_thresholds_are_ordered_sensibly():
    assert MIN_FOR_WEIGHTS <= MIN_FOR_BIAS <= MIN_FOR_EXTREMISE


def test_council_is_scored_against_its_own_members(tmp_path):
    truths = _make_runs(tmp_path)
    track = TrackRecord(tmp_path / "tr.jsonl")
    resolve_due(log_dir=tmp_path, track=track, resolver=lambda q: (truths[q["id"]], "s"))
    out = retune(track=track, log_dir=tmp_path)
    cv = out["council_vs_members"]
    assert cv["council_brier"] is not None
    assert isinstance(cv["aggregation_is_helping"], bool)


# ------------------------------------------------- multiple comparisons


def test_bh_rejects_nothing_when_all_null():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 200)          # uniform p-values = pure noise
    assert benjamini_hochberg(p, q=0.10).sum() <= 2


def test_bh_finds_a_real_effect_among_noise():
    p = np.concatenate([[1e-8, 1e-7], np.random.default_rng(1).uniform(0.2, 1, 98)])
    assert benjamini_hochberg(p, q=0.10)[:2].all()


def test_bh_is_stricter_than_naive_alpha():
    rng = np.random.default_rng(3)
    p = rng.uniform(0, 1, 100)
    assert benjamini_hochberg(p, q=0.05).sum() <= (p < 0.05).sum()


def test_adjusted_pvalues_are_monotone_and_bounded():
    p = np.array([0.001, 0.01, 0.04, 0.2, 0.9])
    adj = adjusted_pvalues(p)
    assert np.all(np.diff(adj) >= -1e-12)
    assert adj.min() >= 0 and adj.max() <= 1
    assert np.all(adj >= p - 1e-12)


def test_expected_false_positives_is_reported():
    assert expected_false_positives(100, 0.05) == pytest.approx(5.0)


def test_pure_noise_batch_yields_no_survivors():
    """The headline guarantee: screening junk must not manufacture discoveries."""
    rng = np.random.default_rng(11)
    dates = pd.date_range("2010-01-31", periods=190, freq="ME")
    target = pd.Series(rng.standard_normal(190) * 0.05, index=dates)
    cands = {f"n{i}": pd.DataFrame(
        {"date": dates, "value": np.cumsum(rng.standard_normal(190)) + 100})
        for i in range(60)}
    s = summarise(validate_candidates(cands, target))
    assert s["survive_fdr"] == 0
    assert s["expected_by_chance"] > 0


def test_a_real_signal_is_found():
    rng = np.random.default_rng(5)
    dates = pd.date_range("2010-01-31", periods=190, freq="ME")
    sig = np.cumsum(rng.standard_normal(190)) + 100
    lead = pd.Series(sig, index=dates).pct_change().fillna(0).to_numpy()
    target = pd.Series(np.roll(lead, 1) * 3.0 + rng.standard_normal(190) * 0.02, index=dates)
    cands = {"real": pd.DataFrame({"date": dates, "value": sig})}
    cands.update({f"n{i}": pd.DataFrame(
        {"date": dates, "value": np.cumsum(rng.standard_normal(190)) + 100})
        for i in range(30)})
    s = summarise(validate_candidates(cands, target))
    assert "real" in s["survivors"]


def test_short_series_is_not_tested():
    dates = pd.date_range("2024-01-31", periods=12, freq="ME")
    r = validate_one("short", pd.DataFrame({"date": dates, "value": range(12)}),
                     pd.Series(np.zeros(12), index=dates))
    assert r.tested is False and "aligned observations" in r.note


def test_sign_flip_is_rejected_as_a_fluke():
    """A relationship that reverses between fit and holdout is the clearest
    signature of a fluke, so it must be thrown out even if p is small."""
    rng = np.random.default_rng(4)
    n = 200
    dates = pd.date_range("2008-01-31", periods=n, freq="ME")
    x = np.cumsum(rng.standard_normal(n)) + 100
    dx = pd.Series(x, index=dates).pct_change().fillna(0).to_numpy()
    half = n // 2
    # Positively related in the first half, negatively in the second.
    y = np.where(np.arange(n) < half, np.roll(dx, 1) * 3, np.roll(dx, 1) * -3)
    target = pd.Series(y + rng.standard_normal(n) * 0.01, index=dates)

    results = validate_candidates(
        {"flipper": pd.DataFrame({"date": dates, "value": x})}, target
    )
    r = results[0]
    assert r.tested is True
    assert r.diagnostics["sign_consistent"] is False
    assert r.survives_fdr is False
    assert "flipped sign" in r.note


def test_validation_records_the_batch_size():
    """A p-value means nothing without knowing how many tests produced it."""
    rng = np.random.default_rng(2)
    dates = pd.date_range("2010-01-31", periods=180, freq="ME")
    target = pd.Series(rng.standard_normal(180) * 0.04, index=dates)
    cands = {f"c{i}": pd.DataFrame(
        {"date": dates, "value": np.cumsum(rng.standard_normal(180)) + 50})
        for i in range(12)}
    for r in validate_candidates(cands, target):
        if r.tested:
            assert r.batch_size == 12


# ------------------------------------------------------------ registry


def test_candidates_never_skip_states(tmp_path):
    reg = CandidateRegistry(tmp_path / "c.json")
    assert reg.add(CandidateRecord(key="k1", name="n", url="u", source="s"))
    assert reg.records["k1"].state == "proposed"
    reg.set_state("k1", "verified")
    assert reg.records["k1"].verified_at
    reg.set_state("k1", "validated")
    assert reg.records["k1"].validated_at


def test_rejections_are_sticky(tmp_path):
    """Otherwise a daily loop rediscovers the same dead source every morning."""
    reg = CandidateRegistry(tmp_path / "c.json")
    reg.add(CandidateRecord(key="dead", name="n", url="u", source="s"))
    reg.set_state("dead", "rejected", rejected_reason="404")
    assert reg.add(CandidateRecord(key="dead", name="n", url="u", source="s")) is False


def test_registry_round_trips(tmp_path):
    p = tmp_path / "c.json"
    reg = CandidateRegistry(p)
    reg.add(CandidateRecord(key="k", name="Name", url="http://x", source="s"))
    reg.set_state("k", "verified")
    reg.save()
    assert CandidateRegistry(p).records["k"].state == "verified"


def test_unknown_state_rejected(tmp_path):
    reg = CandidateRegistry(tmp_path / "c.json")
    reg.add(CandidateRecord(key="k", name="n", url="u", source="s"))
    with pytest.raises(ValueError, match="unknown state"):
        reg.set_state("k", "definitely-true")


# ------------------------------------------------------------ discovery


def test_irrelevant_datasets_are_filtered():
    from vyuha.learn.discover import _relevant

    assert _relevant("Wholesale Price Index of cement")
    assert _relevant("Monthly electricity generation")
    assert not _relevant("Sample Data for Stacked Chart")
    assert not _relevant("List of district headquarters")


def test_candidate_without_url_fails_verification():
    from vyuha.learn.discover import Candidate, verify_candidate

    ok, note, _ = verify_candidate(Candidate(key="k", name="n", url="", source="s"))
    assert ok is False and "URL" in note


def test_hypotheses_are_marked_speculative():
    from vyuha.learn.discover import Candidate

    c = Candidate(key="k", name="n", url="u", source="llm_hypothesis", speculative=True)
    assert c.to_record().evidence["speculative"] is True
