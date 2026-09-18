"""Council orchestration -- the deliberation loop.

Round structure, and why it is this shape:

  Round 0  every member answers *independently*, seeing only the evidence.
           No member sees any other member's view. This is deliberate: the
           dominant failure of multi-agent systems is anchoring, where an early
           confident answer collapses the panel onto one view and the ensemble
           silently becomes a single forecaster with extra steps.

  Round 1+ members see an *anonymised* summary of the distribution of views and
           the strongest argument against the emerging consensus, and may
           revise. Anonymised because attribution triggers deference to
           whichever member sounds most authoritative rather than to whichever
           argument is best.

  Stop     when the pooled estimate moves less than a threshold between rounds,
           or the round budget is exhausted. Convergence is reported, not
           assumed -- a council that never converges is telling you something
           real about the question.

Everything -- prompts, raw responses, parse failures, timings, the evidence
fingerprint -- is written to a run log so any verdict can be reconstructed.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from vyuha.config import settings
from vyuha.council.aggregate import PoolConfig, aggregate
from vyuha.council.evidence import EvidencePacket
from vyuha.council.personas import Persona, select
from vyuha.council.providers import Provider, default_provider, extract_json
from vyuha.council.schema import (
    CouncilVerdict,
    EvidenceRef,
    Forecast,
    Question,
    QuestionKind,
)
from vyuha.council.scoring import TrackRecord

_OUTPUT_SPEC = {
    QuestionKind.BINARY: """Respond with ONLY this JSON object:
{
  "probability": <number between 0 and 1, your true belief the event occurs>,
  "confidence": <0-1, how much evidence you feel you have>,
  "reasoning": "<2-4 sentences. Cite evidence ids in [brackets].>",
  "key_driver": "<the single variable that most determines your answer>",
  "would_change_mind_if": "<what observation would move you most>",
  "citations": [{"id": "E01", "used_for": "<what it supports>"}]
}""",
    QuestionKind.CATEGORICAL: """Respond with ONLY this JSON object:
{
  "distribution": {"<outcome>": <probability>, ...},   // must sum to 1
  "confidence": <0-1>,
  "reasoning": "<2-4 sentences with [E..] citations>",
  "key_driver": "<...>",
  "would_change_mind_if": "<...>",
  "citations": [{"id": "E01", "used_for": "<...>"}]
}""",
    QuestionKind.NUMERIC: """Respond with ONLY this JSON object:
{
  "quantile_values": {"0.05": <v>, "0.25": <v>, "0.5": <v>, "0.75": <v>, "0.95": <v>},
  "confidence": <0-1>,
  "reasoning": "<2-4 sentences with [E..] citations>",
  "key_driver": "<...>",
  "would_change_mind_if": "<...>",
  "citations": [{"id": "E01", "used_for": "<...>"}]
}
Values must be non-decreasing. The 5%-95% interval should be wide enough that
you would genuinely be surprised 1 time in 10 to fall outside it.""",
}


@dataclass(slots=True)
class CouncilConfig:
    rounds: int = 2
    convergence_threshold: float = 0.02   # stop when pooled estimate moves less than this
    pool: PoolConfig = field(default_factory=PoolConfig)
    max_tokens: int = 1600
    log_dir: Path | None = None
    use_track_record: bool = True
    track_record_path: Path | None = None
    fail_open: bool = True                # a dead model must not kill the run


class Council:
    """Runs a bias-diverse panel over one question and pools the result."""

    def __init__(
        self,
        provider: Provider | None = None,
        personas: list[Persona] | list[str] | None = None,
        config: CouncilConfig | None = None,
    ):
        self.provider = provider or default_provider()
        if personas and isinstance(personas[0], str):
            personas = select(names=list(personas))  # type: ignore[arg-type]
        self.personas: list[Persona] = list(personas) if personas else select()  # type: ignore[arg-type]
        self.config = config or CouncilConfig()
        self.track = TrackRecord(
            self.config.track_record_path
            or (settings.council_log_dir / "track_record.jsonl")
        )
        self._model_for: dict[str, str] = {}
        self._substitutions: list[str] = []
        self._resolve_models()

    def _resolve_models(self) -> None:
        for p in self.personas:
            m = self.provider.resolve_model(p.preferred_models)
            self._model_for[p.name] = m or "unavailable"
            if m and m not in p.preferred_models and m.split(":")[0] != p.preferred_models[0].split(":")[0]:
                self._substitutions.append(
                    f"{p.name}: wanted {p.preferred_models[0]}, using {m}"
                )

    # ------------------------------------------------------------------ prompts

    def _user_prompt(
        self, question: Question, packet: EvidencePacket, persona: Persona,
        peer_summary: str | None, prior: Forecast | None,
    ) -> str:
        parts = [
            packet.render(),
            "",
            "QUESTION",
            question.text,
            f"Resolves on {question.resolution_date} by: {question.resolution_criteria}",
        ]
        if question.kind is QuestionKind.CATEGORICAL and question.outcomes:
            parts.append(f"Outcomes: {', '.join(question.outcomes)}")
        if question.unit:
            parts.append(f"Unit: {question.unit}")

        if peer_summary:
            parts += [
                "",
                "THE COUNCIL SO FAR (members anonymised on purpose)",
                peer_summary,
                "",
                "You may revise your estimate or keep it. If you keep it, say why the "
                "contrary argument does not move you. Do NOT converge merely because "
                "others disagree with you -- an ensemble is only worth anything if its "
                "members stay independent. Change your mind for evidence, not for company.",
            ]
        if prior is not None:
            parts.append(f"\nYour previous answer was: {_short(prior)}")

        parts += ["", _OUTPUT_SPEC[question.kind]]
        return "\n".join(parts)

    def _peer_summary(self, question: Question, forecasts: list[Forecast],
                      verdict: CouncilVerdict) -> str:
        ok = [f for f in forecasts if f.parse_ok]
        if not ok:
            return ""
        lines = []
        if question.kind is QuestionKind.BINARY:
            ps = sorted(f.probability for f in ok if f.probability is not None)
            lines.append(
                f"{len(ps)} members answered. Range {min(ps):.0%} to {max(ps):.0%}, "
                f"median {np.median(ps):.0%}, pooled {verdict.probability:.0%}."
            )
        elif question.kind is QuestionKind.NUMERIC and verdict.quantile_values:
            lines.append(
                f"{len(ok)} members answered. Pooled median "
                f"{verdict.quantile_values.get('0.5', float('nan')):.4g}, "
                f"90% interval [{verdict.quantile_values.get('0.05', float('nan')):.4g}, "
                f"{verdict.quantile_values.get('0.95', float('nan')):.4g}]."
            )
        elif verdict.distribution:
            top = sorted(verdict.distribution.items(), key=lambda kv: -kv[1])[:3]
            lines.append("Pooled: " + ", ".join(f"{k} {v:.0%}" for k, v in top))

        lines.append("")
        lines.append("Arguments on the table:")
        for i, f in enumerate(ok, 1):
            if f.reasoning:
                lines.append(f"  (Member {i}) {_short(f)} - {f.reasoning.strip()[:300]}")
        if verdict.strongest_counterargument:
            lines += ["", "STRONGEST ARGUMENT AGAINST THE EMERGING CONSENSUS:",
                      f"  {verdict.strongest_counterargument}"]
        return "\n".join(lines)

    # ------------------------------------------------------------------- asking

    def _ask(
        self, persona: Persona, question: Question, packet: EvidencePacket,
        round_no: int, peer_summary: str | None = None, prior: Forecast | None = None,
    ) -> Forecast:
        model = self._model_for.get(persona.name, "unavailable")
        fc = Forecast(question_id=question.id, member=persona.name, model=model, round=round_no)

        if model == "unavailable":
            fc.parse_ok = False
            fc.parse_error = "no model available for this persona"
            return fc

        user = self._user_prompt(question, packet, persona, peer_summary, prior)
        resp = self.provider.generate(
            system=persona.system_prompt, user=user, model=model,
            temperature=persona.temperature, max_tokens=self.config.max_tokens,
        )
        fc.latency_s = resp.latency_s
        fc.raw_response = resp.text[:8000]

        if not resp.ok:
            fc.parse_ok = False
            fc.parse_error = resp.error or "empty response"
            return fc

        data, err = extract_json(resp.text)
        if data is None:
            fc.parse_ok = False
            fc.parse_error = err
            return fc

        try:
            self._fill(fc, data, question)
        except Exception as exc:  # noqa: BLE001
            fc.parse_ok = False
            fc.parse_error = f"schema error: {exc}"
        return fc

    def _fill(self, fc: Forecast, data: dict[str, Any], question: Question) -> None:
        if question.kind is QuestionKind.BINARY:
            p = data.get("probability")
            if p is None:
                raise ValueError("missing 'probability'")
            p = float(p)
            if p > 1.0:          # models occasionally answer in percent
                p /= 100.0
            fc.probability = min(max(p, 0.0), 1.0)
        elif question.kind is QuestionKind.CATEGORICAL:
            d = data.get("distribution")
            if not isinstance(d, dict) or not d:
                raise ValueError("missing 'distribution'")
            fc.distribution = {str(k): float(v) for k, v in d.items()}
        else:
            q = data.get("quantile_values")
            if not isinstance(q, dict) or not q:
                raise ValueError("missing 'quantile_values'")
            fc.quantile_values = {str(k): float(v) for k, v in q.items()}

        fc.confidence = float(np.clip(float(data.get("confidence", 0.5)), 0.0, 1.0))
        fc.reasoning = str(data.get("reasoning", ""))[:4000]
        fc.key_driver = str(data.get("key_driver", ""))[:500]
        fc.would_change_mind_if = str(data.get("would_change_mind_if", ""))[:500]

        cits = data.get("citations") or []
        refs: list[EvidenceRef] = []
        for c in cits:
            if isinstance(c, dict) and c.get("id"):
                refs.append(EvidenceRef(id=str(c["id"]), used_for=str(c.get("used_for", ""))[:200]))
            elif isinstance(c, str):
                refs.append(EvidenceRef(id=c))
        fc.citations = refs
        # Re-validate through pydantic (normalises distributions, checks monotonicity).
        Forecast.model_validate(fc.model_dump())

    # -------------------------------------------------------------------- run

    def run(self, question: Question, packet: EvidencePacket) -> CouncilVerdict:
        run_id = f"{question.id}_{uuid.uuid4().hex[:8]}"
        weights = (
            self.track.weights([p.name for p in self.personas])
            if self.config.use_track_record else None
        )
        bias = (
            self.track.bias_corrections([p.name for p in self.personas])
            if self.config.use_track_record else None
        )

        history: list[CouncilVerdict] = []
        current: dict[str, Forecast] = {}
        peer_summary: str | None = None
        verdict: CouncilVerdict | None = None

        for rnd in range(self.config.rounds):
            forecasts = [
                self._ask(p, question, packet, rnd, peer_summary, current.get(p.name))
                for p in self.personas
            ]
            if not any(f.parse_ok for f in forecasts) and not self.config.fail_open:
                raise RuntimeError("every council member failed to produce a forecast")

            current = {f.member: f for f in forecasts}
            verdict = aggregate(question, forecasts, weights, bias, self.config.pool)
            history.append(verdict)

            # Flag anyone citing evidence they were never given.
            halluc = [
                f.member for f in forecasts
                if f.parse_ok and packet.validate_citations(f)["has_hallucinated_citation"]
            ]
            if halluc:
                verdict.notes.append(f"hallucinated citation ids from: {', '.join(halluc)}")

            if rnd + 1 < self.config.rounds:
                if _converged(history, self.config.convergence_threshold):
                    verdict.notes.append(f"converged after round {rnd}; stopping early")
                    break
                peer_summary = self._peer_summary(question, forecasts, verdict)

        assert verdict is not None
        verdict.notes.append(f"rounds_run={len(history)}")
        verdict.notes.append(f"evidence_fingerprint={packet.fingerprint()}")
        if self._substitutions:
            verdict.notes.append("model substitutions -> " + "; ".join(self._substitutions))
        if len(history) > 1 and history[0].probability is not None and verdict.probability is not None:
            verdict.notes.append(
                f"movement_from_round0={verdict.probability - history[0].probability:+.3f}"
            )

        self._log(run_id, question, packet, history, verdict)
        return verdict

    def _log(self, run_id, question, packet, history, verdict) -> None:
        d = self.config.log_dir or settings.council_log_dir
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": run_id,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "question": question.model_dump(mode="json"),
            "evidence": {
                "as_of": packet.as_of.isoformat(),
                "fingerprint": packet.fingerprint(),
                "items": [
                    {"id": i.id, "label": i.label, "value": i.value,
                     "event_date": str(i.event_date), "source": i.source}
                    for i in packet.items
                ],
                "caveats": packet.caveats,
            },
            "provider": self.provider.name,
            "models": self._model_for,
            "rounds": [v.model_dump(mode="json") for v in history],
            "verdict": verdict.model_dump(mode="json"),
        }
        (d / f"{run_id}.json").write_text(json.dumps(payload, indent=2, default=str))


def _short(f: Forecast) -> str:
    if f.probability is not None:
        return f"{f.probability:.0%}"
    if f.quantile_values:
        return f"median {f.quantile_values.get('0.5', float('nan')):.4g}"
    if f.distribution:
        top = max(f.distribution.items(), key=lambda kv: kv[1])
        return f"{top[0]} {top[1]:.0%}"
    return "no answer"


def _converged(history: list[CouncilVerdict], threshold: float) -> bool:
    if len(history) < 2:
        return False
    a, b = history[-2], history[-1]
    if a.probability is not None and b.probability is not None:
        return abs(a.probability - b.probability) < threshold
    if a.quantile_values and b.quantile_values:
        am, bm = a.quantile_values.get("0.5"), b.quantile_values.get("0.5")
        if am is not None and bm is not None and am != 0:
            return abs(bm - am) / abs(am) < threshold
    return False
