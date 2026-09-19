"""Structured types for council questions and forecasts.

The council is not a chatbot round-table. Every member answers a *precisely
resolvable* question with a *calibrated distribution*, cites the evidence it
used by ID, and is scored against the outcome. Free-form opinion is captured
too, but it never enters the aggregate -- only the numbers do.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class QuestionKind(str, Enum):
    BINARY = "binary"            # P(event)
    CATEGORICAL = "categorical"  # distribution over named outcomes
    NUMERIC = "numeric"          # quantiles of a continuous quantity


class Question(BaseModel):
    """A question that a clock and a data feed can settle without a human."""

    id: str
    kind: QuestionKind
    text: str
    resolution_criteria: str = Field(
        ..., description="Exactly how this resolves, including the source series and timestamp."
    )
    resolution_date: dt.date
    resolution_source: str = Field(..., description="series_id in the PIT store that settles it.")
    outcomes: list[str] | None = None          # CATEGORICAL
    quantiles: list[float] = Field(default_factory=lambda: [0.05, 0.25, 0.5, 0.75, 0.95])
    unit: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Question:
        if self.kind is QuestionKind.CATEGORICAL and not self.outcomes:
            raise ValueError("categorical questions need outcomes")
        if self.kind is QuestionKind.CATEGORICAL and len(set(self.outcomes or [])) < 2:
            raise ValueError("categorical questions need >= 2 distinct outcomes")
        return self


class EvidenceRef(BaseModel):
    """A citation. ``id`` must match an item in the evidence packet -- a member
    that cites an ID we never gave it is hallucinating and gets flagged."""

    id: str
    used_for: str = Field("", description="What this datum supports in the argument.")


class Forecast(BaseModel):
    """One member's answer."""

    question_id: str
    member: str
    model: str
    round: int = 0

    probability: float | None = None            # BINARY
    distribution: dict[str, float] | None = None  # CATEGORICAL
    quantile_values: dict[str, float] | None = None  # NUMERIC, keyed by quantile as str

    confidence: float = Field(0.5, ge=0.0, le=1.0,
                              description="Self-reported; used only as a diagnostic, never as a weight.")
    reasoning: str = ""
    key_driver: str = Field("", description="The single variable that would most change this view.")
    would_change_mind_if: str = ""
    citations: list[EvidenceRef] = Field(default_factory=list)

    latency_s: float | None = None
    raw_response: str | None = None
    parse_ok: bool = True
    parse_error: str | None = None

    @field_validator("probability")
    @classmethod
    def _prob_range(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {v}")
        return v

    @model_validator(mode="after")
    def _normalise_categorical(self) -> Forecast:
        if self.distribution:
            total = sum(self.distribution.values())
            if total <= 0:
                raise ValueError("categorical distribution sums to <= 0")
            if abs(total - 1.0) > 1e-6:
                self.distribution = {k: v / total for k, v in self.distribution.items()}
        if self.quantile_values:
            items = sorted((float(k), v) for k, v in self.quantile_values.items())
            vals = [v for _, v in items]
            if any(b < a for a, b in zip(vals, vals[1:], strict=False)):
                raise ValueError(f"quantiles must be non-decreasing, got {vals}")
        return self

    def as_vector(self, question: Question) -> list[float]:
        """The forecast as a plain numeric vector, for pooling."""
        if question.kind is QuestionKind.BINARY:
            return [float(self.probability if self.probability is not None else 0.5)]
        if question.kind is QuestionKind.CATEGORICAL:
            d = self.distribution or {}
            n = len(question.outcomes or [])
            return [d.get(o, 1.0 / n) for o in (question.outcomes or [])]
        qv = self.quantile_values or {}
        return [float(qv.get(str(q), float("nan"))) for q in question.quantiles]


class CouncilVerdict(BaseModel):
    """The pooled answer, with the disagreement preserved rather than averaged away."""

    question_id: str
    kind: QuestionKind
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    probability: float | None = None
    distribution: dict[str, float] | None = None
    quantile_values: dict[str, float] | None = None

    n_members: int = 0
    method: str = ""
    weights: dict[str, float] = Field(default_factory=dict)
    bias_corrections: dict[str, float] = Field(default_factory=dict)

    # Disagreement is a first-class output, not noise to be smoothed.
    dispersion: float = 0.0
    dissent: list[str] = Field(default_factory=list)
    strongest_counterargument: str = ""

    member_forecasts: list[Forecast] = Field(default_factory=list)
    uncited_claims_flagged: int = 0
    notes: list[str] = Field(default_factory=list)

    def summary_line(self) -> str:
        if self.probability is not None:
            head = f"P = {self.probability:.1%}"
        elif self.distribution:
            top = max(self.distribution.items(), key=lambda kv: kv[1])
            head = f"{top[0]} @ {top[1]:.1%}"
        elif self.quantile_values:
            head = f"median = {self.quantile_values.get('0.5', float('nan')):.4g}"
        else:
            head = "no answer"
        return f"{head}  [{self.n_members} members, dispersion {self.dispersion:.3f}]"


class Resolution(BaseModel):
    """Ground truth, once it is known."""

    question_id: str
    resolved_at: dt.datetime
    outcome_binary: bool | None = None
    outcome_category: str | None = None
    outcome_value: float | None = None
    source_note: str = ""


def question_id_for(text: str, resolution_date: dt.date) -> str:
    h = hashlib.sha256(f"{text}|{resolution_date}".encode()).hexdigest()[:12]
    return f"q_{resolution_date:%Y%m%d}_{h}"


def dumps(obj: BaseModel) -> str:
    return json.dumps(obj.model_dump(mode="json"), indent=2, default=str)
