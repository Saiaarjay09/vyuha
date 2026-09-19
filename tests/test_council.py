import datetime as dt

import numpy as np
import pytest

from vyuha.council.aggregate import (
    PoolConfig,
    aggregate,
    directional_agreement,
    effective_independence,
    pool_binary,
    pool_categorical,
    pool_quantiles,
)
from vyuha.council.evidence import EvidencePacket
from vyuha.council.personas import PERSONAS, select
from vyuha.council.providers import EchoProvider, extract_json
from vyuha.council.schema import EvidenceRef, Forecast, Question, QuestionKind
from vyuha.council.scoring import (
    TrackRecord,
    brier_score,
    crps_from_quantiles,
    expected_calibration_error,
    log_score,
    murphy_decomposition,
    pinball_loss,
)


@pytest.fixture
def binary_q():
    return Question(
        id="q1", kind=QuestionKind.BINARY, text="Will Nifty close below 24000?",
        resolution_criteria="NSE official close", resolution_date=dt.date(2026, 12, 31),
        resolution_source="NIFTY50_CLOSE",
    )


# ------------------------------------------------------------------- pooling


def test_log_pool_is_sharper_than_linear_when_members_agree():
    probs = [0.8, 0.85, 0.75, 0.82]
    lin = pool_binary(probs, config=PoolConfig(method="linear", extremise=False))[0]
    log = pool_binary(probs, config=PoolConfig(method="log", extremise=False))[0]
    assert log > lin


def test_extremisation_sharpens_a_unanimous_underconfident_panel():
    probs = [0.62, 0.58, 0.71, 0.55, 0.66]
    raw = pool_binary(probs, config=PoolConfig(extremise=False))[0]
    ext = pool_binary(probs, config=PoolConfig(extremise=True))[0]
    assert ext > raw


def test_polarised_panel_is_not_over_extremised():
    """The bug this guards: a 5%/95% deadlock has huge spread but no shared
    signal. Treating spread alone as independence manufactured 85% confidence
    out of a panel that fundamentally disagreed."""
    polarised = [0.05, 0.95, 0.20, 0.99, 0.55]
    unanimous = [0.62, 0.58, 0.71, 0.55, 0.66]
    assert effective_independence(polarised) < effective_independence(unanimous)
    p = pool_binary(polarised, config=PoolConfig(extremise=True))[0]
    assert 0.3 < p < 0.8, f"deadlocked panel extremised to {p:.2%}"


def test_directional_agreement_bounds():
    assert directional_agreement([0.6, 0.7, 0.8]) == 1.0      # all one side
    assert directional_agreement([0.4, 0.6]) == 0.0            # dead split
    assert 0.0 < directional_agreement([0.4, 0.6, 0.7]) < 1.0


def test_pooling_is_order_invariant():
    probs = [0.2, 0.9, 0.55, 0.31]
    a = pool_binary(probs, config=PoolConfig())[0]
    b = pool_binary(list(reversed(probs)), config=PoolConfig())[0]
    assert a == pytest.approx(b)


def test_weights_shift_the_pool_toward_the_trusted_member():
    probs, members = [0.2, 0.8], ["a", "b"]
    cfg = PoolConfig(extremise=False)
    even = pool_binary(probs, members, config=cfg)[0]
    to_a = pool_binary(probs, members, weights={"a": 0.9, "b": 0.1}, config=cfg)[0]
    assert to_a < even


def test_bias_correction_removes_a_known_skew():
    """A member 1.0 in log-odds too bullish, corrected, matches an unbiased one."""
    cfg = PoolConfig(extremise=False, bias_correct=True)
    corrected = pool_binary([0.73], ["bull"], bias={"bull": 1.0}, config=cfg)[0]
    assert corrected == pytest.approx(0.5, abs=0.03)


def test_categorical_pool_normalises_and_stays_a_distribution():
    outcomes = ["cut", "hold", "hike"]
    dists = [{"cut": 0.2, "hold": 0.7, "hike": 0.1},
             {"cut": 0.1, "hold": 0.8, "hike": 0.1}]
    pooled, info = pool_categorical(dists, outcomes)
    assert sum(pooled.values()) == pytest.approx(1.0)
    assert pooled["hold"] == max(pooled.values())
    assert info["entropy_bits"] > 0


def test_quantile_pool_stays_monotonic():
    qs = [0.05, 0.25, 0.5, 0.75, 0.95]
    sets = [{"0.05": 23000, "0.25": 24000, "0.5": 24800, "0.75": 25500, "0.95": 26500},
            {"0.05": 22000, "0.25": 23500, "0.5": 24200, "0.75": 25000, "0.95": 26000}]
    pooled, _ = pool_quantiles(sets, qs)
    vals = [pooled[str(q)] for q in qs]
    assert all(b >= a for a, b in zip(vals, vals[1:], strict=False))
    assert 24200 <= pooled["0.5"] <= 24800


def test_empty_panel_returns_uninformative_prior(binary_q):
    v = aggregate(binary_q, [])
    assert v.probability == 0.5
    assert v.n_members == 0


# ------------------------------------------------------------------ verdicts


def test_verdict_preserves_dispersion_and_dissent(binary_q):
    fcs = [
        Forecast(question_id="q1", member=m, model="x", probability=p,
                 reasoning=f"{m} reasoning", key_driver="flows",
                 citations=[EvidenceRef(id="E01")])
        for m, p in [("a", 0.10), ("b", 0.55), ("c", 0.60), ("d", 0.62)]
    ]
    v = aggregate(binary_q, fcs)
    assert v.dispersion > 0
    assert any("a" in d for d in v.dissent)
    assert v.strongest_counterargument != ""
    assert v.uncited_claims_flagged == 0


def test_unparseable_members_are_excluded_not_counted(binary_q):
    fcs = [
        Forecast(question_id="q1", member="ok", model="x", probability=0.7),
        Forecast(question_id="q1", member="bad", model="x", parse_ok=False,
                 parse_error="no json"),
    ]
    v = aggregate(binary_q, fcs)
    assert v.n_members == 1


def test_forecast_rejects_out_of_range_probability():
    with pytest.raises(ValueError):
        Forecast(question_id="q", member="m", model="x", probability=1.4)


def test_forecast_rejects_non_monotonic_quantiles():
    with pytest.raises(ValueError, match="non-decreasing"):
        Forecast(question_id="q", member="m", model="x",
                 quantile_values={"0.05": 100, "0.5": 90, "0.95": 120})


def test_categorical_distribution_is_renormalised():
    f = Forecast(question_id="q", member="m", model="x",
                 distribution={"a": 2.0, "b": 2.0})
    assert sum(f.distribution.values()) == pytest.approx(1.0)


# ------------------------------------------------------------------ scoring


def test_brier_and_log_score_reward_being_right():
    assert brier_score(0.9, True) < brier_score(0.6, True)
    assert log_score(0.9, True) < log_score(0.6, True)


def test_confident_and_wrong_is_punished_hardest():
    assert log_score(0.01, True) > log_score(0.4, True) > log_score(0.9, True)


def test_murphy_decomposition_identity():
    """Brier must equal reliability - resolution + uncertainty."""
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 2000)
    y = rng.random(2000) < p
    d = murphy_decomposition(p, y, n_bins=10)
    assert d["brier"] == pytest.approx(
        d["reliability"] - d["resolution"] + d["uncertainty"], abs=2e-3
    )


def test_calibrated_forecaster_has_low_ece():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.05, 0.95, 5000)
    y = rng.random(5000) < p
    assert expected_calibration_error(p, y) < 0.05


def test_overconfident_forecaster_has_high_ece():
    rng = np.random.default_rng(1)
    true_p = rng.uniform(0.3, 0.7, 5000)
    y = rng.random(5000) < true_p
    stated = np.where(true_p > 0.5, 0.98, 0.02)   # always shouts
    assert expected_calibration_error(stated, y) > 0.2


def test_pinball_loss_is_minimised_at_the_true_quantile():
    rng = np.random.default_rng(2)
    sample = rng.standard_normal(20_000)
    true_q90 = np.quantile(sample, 0.9)
    at_truth = np.mean([pinball_loss(0.9, true_q90, a) for a in sample])
    for wrong in (true_q90 - 0.5, true_q90 + 0.5):
        assert at_truth < np.mean([pinball_loss(0.9, wrong, a) for a in sample])


def test_crps_prefers_the_sharper_correct_forecast():
    tight = {"0.05": 98, "0.5": 100, "0.95": 102}
    wide = {"0.05": 80, "0.5": 100, "0.95": 120}
    assert crps_from_quantiles(tight, 100.0) < crps_from_quantiles(wide, 100.0)


def test_track_record_weights_favour_the_better_forecaster(tmp_path):
    tr = TrackRecord(tmp_path / "tr.jsonl")
    rng = np.random.default_rng(4)
    for i in range(60):
        y = bool(rng.random() < 0.5)
        tr.record("sharp", f"q{i}", probability=0.85 if y else 0.15, outcome_binary=y)
        tr.record("noise", f"q{i}", probability=0.5, outcome_binary=y)
    w = tr.weights(["sharp", "noise"])
    assert w["sharp"] > w["noise"]
    assert sum(w.values()) == pytest.approx(1.0)


def test_weight_floor_keeps_every_member_in_the_room(tmp_path):
    """A bias-diverse council only works if the currently-worst member still
    has a voice -- it is the one that catches the regime change."""
    tr = TrackRecord(tmp_path / "tr.jsonl")
    for i in range(50):
        tr.record("good", f"q{i}", probability=0.99, outcome_binary=True)
        tr.record("awful", f"q{i}", probability=0.01, outcome_binary=True)
    w = tr.weights(["good", "awful"], floor=0.05)
    assert w["awful"] >= 0.05


def test_bias_correction_detects_a_permabear(tmp_path):
    tr = TrackRecord(tmp_path / "tr.jsonl")
    rng = np.random.default_rng(6)
    for i in range(80):
        y = bool(rng.random() < 0.7)          # base rate 70%
        tr.record("bear", f"q{i}", probability=0.25, outcome_binary=y)
    b = tr.bias_corrections(["bear"])
    assert b["bear"] < 0, "a persistently low forecaster should show negative bias"


def test_new_member_is_not_penalised(tmp_path):
    tr = TrackRecord(tmp_path / "tr.jsonl")
    for i in range(30):
        tr.record("veteran", f"q{i}", probability=0.8, outcome_binary=True)
    w = tr.weights(["veteran", "rookie"])
    assert w["rookie"] > 0
    assert tr.bias_corrections(["rookie"])["rookie"] == 0.0


# ----------------------------------------------------------------- evidence


def test_evidence_packet_ids_and_rendering():
    p = EvidencePacket(as_of=dt.datetime(2026, 9, 18))
    p.add("CPI_YOY", 5.4, unit="pct", source="MOSPI")
    p.add("REPO", 6.5, unit="pct", source="RBI")
    assert p.ids == {"E01", "E02"}
    assert "[E01] CPI_YOY" in p.render()


def test_hallucinated_citation_is_caught():
    p = EvidencePacket(as_of=dt.datetime(2026, 9, 18))
    p.add("CPI_YOY", 5.4, source="MOSPI")
    f = Forecast(question_id="q", member="m", model="x", probability=0.5,
                 citations=[EvidenceRef(id="E01"), EvidenceRef(id="E99")])
    v = p.validate_citations(f)
    assert v["has_hallucinated_citation"] is True
    assert v["hallucinated_ids"] == ["E99"]


def test_packet_fingerprint_is_stable_and_sensitive():
    def build(v):
        p = EvidencePacket(as_of=dt.datetime(2026, 9, 18))
        p.add("CPI_YOY", v, source="MOSPI")
        return p.fingerprint()
    assert build(5.4) == build(5.4)
    assert build(5.4) != build(5.5)


# ----------------------------------------------------------------- plumbing


def test_all_personas_have_distinct_documented_bias():
    names = [p.name for p in PERSONAS]
    assert len(names) == len(set(names))
    for p in PERSONAS:
        assert p.bias and len(p.bias) > 30
        assert "HARD RULES" in p.system_prompt
        assert p.preferred_models


def test_default_council_spans_opposing_views():
    names = {p.name for p in select()}
    assert {"hawk", "dove"} <= names          # opposed on inflation
    assert {"value_bear", "momentum_bull"} <= names   # opposed on valuation
    assert "red_team" in names


def test_json_extraction_survives_common_model_sloppiness():
    for raw, want in [
        ('{"probability": 0.3}', 0.3),
        ('```json\n{"probability": 0.3}\n```', 0.3),
        ('Sure! {"probability": 0.3} Hope that helps.', 0.3),
        ('{"probability": 0.3,}', 0.3),
    ]:
        data, err = extract_json(raw)
        assert err is None and data["probability"] == want


def test_json_extraction_reports_failure_rather_than_guessing():
    data, err = extract_json("I cannot answer that.")
    assert data is None and err


def test_echo_provider_runs_the_pipeline_without_a_model(binary_q):
    from vyuha.council.debate import Council, CouncilConfig
    c = Council(provider=EchoProvider(probability=0.42),
                personas=["hawk", "dove", "quant"],
                config=CouncilConfig(rounds=1, use_track_record=False))
    p = EvidencePacket(as_of=dt.datetime(2026, 9, 18))
    p.add("NIFTY", 24800, source="NSE")
    v = c.run(binary_q, p)
    assert v.n_members == 3
    assert v.probability == pytest.approx(0.42, abs=0.02)
