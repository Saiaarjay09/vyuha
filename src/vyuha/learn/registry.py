"""Persistent store of candidate variables and their lifecycle.

A candidate moves through states, and never skips one:

    proposed   something suggested it might matter. No evidence yet.
    verified   its endpoint actually returns parseable data. Still no evidence
               that it matters.
    validated  it survived out-of-sample statistical testing WITH multiple-
               comparison correction.
    promoted   a human merged it into the catalogue.
    rejected   it failed at some stage; the reason is kept so the same dead end
               is not rediscovered every morning.

The separation matters because the interesting failure is silent promotion:
an automated loop that finds a variable, notices a correlation, and starts
using it. Test a hundred random series against Nifty returns and about five
clear p<0.05 on noise alone. Only ``validated`` candidates are ever proposed
for promotion, and only a person promotes them.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vyuha.config import settings

STATES = ("proposed", "verified", "validated", "promoted", "rejected")


@dataclass(slots=True)
class CandidateRecord:
    key: str
    name: str
    url: str
    source: str                      # which discovery channel found it
    rationale: str = ""              # why it might matter
    state: str = "proposed"
    discovered_at: str = ""
    verified_at: str = ""
    validated_at: str = ""
    rejected_reason: str = ""
    asset_classes: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class CandidateRegistry:
    """JSON-backed, human-readable, diffable in a pull request."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else (settings.data_dir / "candidates.json")
        self.records: dict[str, CandidateRecord] = {}
        if self.path.exists():
            try:
                for row in json.loads(self.path.read_text()):
                    self.records[row["key"]] = CandidateRecord(**row)
            except (json.JSONDecodeError, OSError, TypeError):
                self.records = {}

    # ------------------------------------------------------------------ write

    def add(self, rec: CandidateRecord) -> bool:
        """Add a candidate. Returns False if already known in any state.

        Re-proposing something already rejected is the commonest waste in a
        daily loop, so rejections are sticky.
        """
        if rec.key in self.records:
            return False
        rec.discovered_at = rec.discovered_at or dt.datetime.now(dt.UTC).isoformat()
        self.records[rec.key] = rec
        return True

    def set_state(self, key: str, state: str, **fields: Any) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}; choose from {STATES}")
        rec = self.records.get(key)
        if rec is None:
            raise KeyError(key)
        rec.state = state
        stamp = dt.datetime.now(dt.UTC).isoformat()
        if state == "verified":
            rec.verified_at = stamp
        elif state == "validated":
            rec.validated_at = stamp
        for k, v in fields.items():
            setattr(rec, k, v)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [r.to_dict() for r in sorted(self.records.values(), key=lambda r: r.key)]
        self.path.write_text(json.dumps(rows, indent=2, sort_keys=False))

    # ------------------------------------------------------------------- read

    def by_state(self, state: str) -> list[CandidateRecord]:
        return [r for r in self.records.values() if r.state == state]

    def known_keys(self) -> set[str]:
        return set(self.records)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATES}
        for r in self.records.values():
            out[r.state] = out.get(r.state, 0) + 1
        return out

    def summary(self) -> str:
        c = self.counts()
        return " | ".join(f"{k} {v}" for k, v in c.items() if v)
