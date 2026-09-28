"""Writing the world into the point-in-time store, every day.

Without this the learning loop cannot function, and the failure is silent: the
council logs forecasts, `resolve_due` looks for outcomes, finds no price
history, marks everything unresolvable, and every member stays equally
weighted forever. The store was empty for the project's entire life and
nothing complained.

Each snapshot records what was observable today, with ``available_at`` set to
now. That is honest -- we fetched it now -- and it is what lets a later
resolution ask "did NIFTY50_CLOSE ever go below X between these dates" and get
an answer grounded in data rather than in a model's recollection.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from vyuha.store.pit import Observation, PITStore


@dataclass(slots=True)
class SnapshotReport:
    written: int = 0
    series: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"wrote {self.written} observation(s) across {len(self.series)} series"
            + (f"; {len(self.errors)} source(s) failed" if self.errors else "")
        )


def snapshot_today(store: PITStore | None = None,
                   as_of: dt.datetime | None = None) -> SnapshotReport:
    """Capture today's observable market state into the PIT store."""
    own = store is None
    store = store or PITStore()
    now = as_of or dt.datetime.now()
    today = now.date()
    report = SnapshotReport()
    obs: list[Observation] = []

    def add(series_id: str, value: float, unit: str = "", source: str = "",
            event_date: dt.date | None = None) -> None:
        obs.append(Observation(
            series_id=series_id, event_date=event_date or today, available_at=now,
            value=float(value), unit=unit or None, source=source,
        ))
        report.series.append(series_id)

    # --- Indian indices and volatility
    try:
        from vyuha.ingest.base import NSESession
        from vyuha.ingest.sources import nse_all_indices, nse_fii_dii

        with NSESession() as s:
            idx = nse_all_indices(s)
            wanted = {
                "NIFTY 50": "NIFTY50_CLOSE", "NIFTY BANK": "BANKNIFTY_CLOSE",
                "INDIA VIX": "INDIA_VIX", "NIFTY MIDCAP 100": "NIFTY_MIDCAP_CLOSE",
                "NIFTY NEXT 50": "NIFTY_NEXT50_CLOSE",
            }
            for name, sid in wanted.items():
                row = idx[idx["index"].str.upper() == name]
                if len(row):
                    add(sid, float(row["last"].iloc[0]), "index", "NSE")
            for r in nse_fii_dii(s).to_dict("records"):
                cat = str(r.get("category", "")).replace("/", "_").upper()
                if cat and r.get("netValue") not in (None, ""):
                    add(f"{cat}_NET_CASH", float(r["netValue"]), "INR cr", "NSE")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"NSE: {type(exc).__name__}: {str(exc)[:90]}")

    # --- policy rates and reference FX
    try:
        from vyuha.ingest.rbi import rbi_current_rates

        for _, r in rbi_current_rates().iterrows():
            add(str(r["series_id"]), float(r["value"]), str(r["unit"]), "RBI")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"RBI: {type(exc).__name__}: {str(exc)[:90]}")

    # --- commodities and global rates
    try:
        from vyuha.ingest.globalmarkets import commodity_snapshot, global_snapshot

        for _, r in commodity_snapshot(["gold", "silver", "brent"]).iterrows():
            if r["value"] is not None and not r["error"]:
                add(f"{str(r['commodity']).upper()}_USD", float(r["value"]),
                    str(r["unit"]), "LBMA/FRED", event_date=r["date"])
        for _, r in global_snapshot(["sp500", "vix", "us_10y", "dollar_index"]).iterrows():
            if r["value"] is not None and not r["error"]:
                add(str(r["series"]).upper(), float(r["value"]), str(r["unit"]),
                    "FRED", event_date=r["date"])
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"global: {type(exc).__name__}: {str(exc)[:90]}")

    try:
        report.written = store.write(obs)
        report.series = sorted(set(report.series))
    finally:
        if own:
            store.close()
    return report


def series_history(series_id: str, days: int = 400,
                   store: PITStore | None = None) -> Any:
    """Everything we have recorded for one series, latest revision per day."""
    own = store is None
    store = store or PITStore(read_only=True)
    try:
        return store.as_of(
            dt.datetime.now(), series_id=series_id,
            start=dt.date.today() - dt.timedelta(days=days),
        )
    finally:
        if own:
            store.close()
