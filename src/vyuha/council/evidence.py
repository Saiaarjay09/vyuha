"""Evidence packets.

Council members never touch the database and never browse. They receive a
frozen, numbered packet of facts, and every claim they make must cite one by
id. This is what keeps a language model from doing the thing language models do
-- producing a fluent, confident, entirely invented number for the March CPI
print.

Three properties are enforced:

  grounded      every item carries series_id, event_date, available_at, source
  point-in-time the packet is built ``as_of`` a timestamp, so a backtest of the
                council in March 2024 cannot see an April 2024 release
  auditable     the packet is hashed and logged with the verdict, so any past
                forecast can be reproduced exactly
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

from vyuha.council.schema import Forecast


@dataclass(slots=True)
class EvidenceItem:
    id: str
    label: str
    value: Any
    unit: str | None = None
    event_date: dt.date | None = None
    available_at: dt.datetime | None = None
    source: str = ""
    note: str = ""
    history: list[tuple[str, float]] = field(default_factory=list)

    def render(self) -> str:
        v = f"{self.value:,.4g}" if isinstance(self.value, (int, float)) else str(self.value)
        bits = [f"[{self.id}] {self.label}: {v}"]
        if self.unit:
            bits.append(self.unit)
        parts = " ".join(bits)
        meta = []
        if self.event_date:
            meta.append(f"as of {self.event_date}")
        if self.available_at:
            meta.append(f"published {self.available_at:%Y-%m-%d}")
        if self.source:
            meta.append(f"src: {self.source}")
        if meta:
            parts += f"  ({'; '.join(meta)})"
        if self.history:
            trail = ", ".join(f"{d}: {v:,.4g}" for d, v in self.history[-6:])
            parts += f"\n      recent: {trail}"
        if self.note:
            parts += f"\n      note: {self.note}"
        return parts


@dataclass(slots=True)
class EvidencePacket:
    as_of: dt.datetime
    items: list[EvidenceItem] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def add(self, label: str, value: Any, **kw: Any) -> EvidenceItem:
        item = EvidenceItem(id=f"E{len(self.items) + 1:02d}", label=label, value=value, **kw)
        self.items.append(item)
        return item

    @property
    def ids(self) -> set[str]:
        return {i.id for i in self.items}

    def render(self) -> str:
        if not self.items:
            return "EVIDENCE\n(none available -- answer from base rates and say so)"
        lines = [f"EVIDENCE (point-in-time as of {self.as_of:%Y-%m-%d %H:%M} IST)", ""]
        lines += [i.render() for i in self.items]
        if self.caveats:
            lines += ["", "DATA CAVEATS"] + [f"  - {c}" for c in self.caveats]
        return "\n".join(lines)

    def fingerprint(self) -> str:
        blob = json.dumps(
            [[i.id, i.label, str(i.value), str(i.event_date)] for i in self.items],
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    # ------------------------------------------------------------- validation

    def validate_citations(self, forecast: Forecast) -> dict[str, Any]:
        """Check a member's citations against what it was actually given.

        ``hallucinated_ids`` is the one that matters: a member citing [E42] when
        the packet has 12 items is inventing support, and that is a scoring
        event, not a formatting nit.
        """
        cited = {c.id for c in forecast.citations}
        bad = sorted(cited - self.ids)
        return {
            "n_citations": len(cited),
            "hallucinated_ids": bad,
            "has_hallucinated_citation": bool(bad),
            "uncited": not cited,
            "coverage": len(cited & self.ids) / max(len(self.ids), 1),
        }


# ----------------------------------------------------------------- builders


def packet_from_store(
    store: Any,
    as_of: dt.datetime | dt.date | str,
    series: Sequence[str],
    lookback_days: int = 400,
    history_points: int = 6,
) -> EvidencePacket:
    """Build a packet from the point-in-time store.

    Only the latest revision visible at ``as_of`` is used, and the publication
    lag is shown so a member can see that it is reasoning about a CPI print that
    is already five weeks stale.
    """
    ts = pd.Timestamp(as_of)
    packet = EvidencePacket(as_of=ts.to_pydatetime())
    start = (ts - pd.Timedelta(days=lookback_days)).date()

    df = store.as_of(as_of, series_id=list(series), start=start)
    if df.empty:
        packet.caveats.append(
            f"No observations available as of {ts:%Y-%m-%d} for: {', '.join(series)}"
        )
        return packet

    for sid, grp in df.groupby("series_id"):
        grp = grp.sort_values("event_date")
        last = grp.iloc[-1]
        hist = [
            (str(pd.Timestamp(r.event_date).date()), float(r.value))
            for r in grp.tail(history_points).itertuples()
            if pd.notna(r.value)
        ]
        lag = (pd.Timestamp(last["available_at"]).date() - pd.Timestamp(last["event_date"]).date()).days
        packet.add(
            label=str(sid),
            value=last["value"] if pd.notna(last["value"]) else last["text_value"],
            unit=last.get("unit"),
            event_date=pd.Timestamp(last["event_date"]).date(),
            available_at=pd.Timestamp(last["available_at"]).to_pydatetime(),
            source=str(last["source"]),
            history=hist[:-1],
            note=f"publication lag {lag}d" if lag > 3 else "",
        )

    missing = sorted(set(series) - set(df["series_id"].unique()))
    if missing:
        packet.caveats.append(
            f"Requested but unavailable at this timestamp: {', '.join(missing)}. "
            "Treat the corresponding questions as more uncertain, do not guess values."
        )
    return packet


def add_risk_evidence(packet: EvidencePacket, risk: dict[str, Any]) -> EvidencePacket:
    """Fold risk-engine output into the packet so members reason from the same
    numbers the risk system produced, not from their own arithmetic."""
    for label, value in risk.items():
        if isinstance(value, (int, float)) and pd.notna(value):
            packet.add(label=label, value=float(value), source="vyuha.risk")
    return packet
