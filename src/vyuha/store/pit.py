"""Point-in-time (bitemporal) observation store.

The single most common way a backtest lies to you is lookahead: using a number
today that was not actually published until later, or using a *revised* figure
where only the *first print* was knowable. India makes this especially easy to
get wrong -- CPI and IIP are released with a ~12 day lag and revised twice, GDP
is revised for years, and index constituents are changed with a two-week notice.

So every fact in Vyuha is stored bitemporally:

    event_date    the date the observation *describes* (e.g. "CPI for March")
    available_at  the timestamp the observation became *publicly knowable*
    revision      monotonically increasing per (series_id, event_date)

A query is always made ``as_of`` some timestamp, and returns only the latest
revision whose ``available_at <= as_of``. If you cannot state when a number
became public, you may not put it in the store.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from vyuha.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    series_id     VARCHAR  NOT NULL,
    entity        VARCHAR,
    event_date    DATE     NOT NULL,
    available_at  TIMESTAMP NOT NULL,
    value         DOUBLE,
    text_value    VARCHAR,
    unit          VARCHAR,
    source        VARCHAR  NOT NULL,
    revision      INTEGER  NOT NULL DEFAULT 0,
    meta          VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_obs_lookup ON observations (series_id, event_date, available_at);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations (entity, event_date);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id        VARCHAR PRIMARY KEY,
    source        VARCHAR NOT NULL,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    rows_written  BIGINT,
    status        VARCHAR,
    detail        VARCHAR
);
"""


@dataclass(slots=True)
class Observation:
    """One bitemporal fact."""

    series_id: str
    event_date: dt.date
    available_at: dt.datetime
    source: str
    value: float | None = None
    text_value: str | None = None
    entity: str | None = None
    unit: str | None = None
    revision: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> tuple:
        return (
            self.series_id,
            self.entity,
            self.event_date,
            self.available_at,
            self.value,
            self.text_value,
            self.unit,
            self.source,
            self.revision,
            json.dumps(self.meta, default=str) if self.meta else None,
        )


class PITStore:
    """DuckDB-backed bitemporal store.

    Usage::

        with PITStore() as store:
            store.write(observations)
            df = store.as_of("2024-03-31", series_id="CPI_COMBINED_YOY")
    """

    def __init__(self, path: Path | str | None = None, read_only: bool = False):
        self.path = Path(path) if path is not None else settings.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            self.con.execute(SCHEMA)

    # ------------------------------------------------------------------ write

    def write(self, observations: Iterable[Observation], auto_revision: bool = True) -> int:
        """Insert observations. With ``auto_revision`` the revision number is
        derived from what is already stored for that (series_id, event_date),
        so re-ingesting a revised print appends rather than overwrites."""
        obs = list(observations)
        if not obs:
            return 0

        if auto_revision:
            keys = {(o.series_id, o.event_date) for o in obs}
            existing = self._max_revisions(keys)
            bumped: dict[tuple[str, dt.date], int] = {}
            for o in obs:
                k = (o.series_id, o.event_date)
                if k in bumped:
                    bumped[k] += 1
                else:
                    prev = existing.get(k)
                    bumped[k] = 0 if prev is None else prev + 1
                o.revision = bumped[k]

        self.con.executemany(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)",
            [o.as_row() for o in obs],
        )
        return len(obs)

    def _max_revisions(
        self, keys: set[tuple[str, dt.date]]
    ) -> dict[tuple[str, dt.date], int]:
        if not keys:
            return {}
        series = sorted({k[0] for k in keys})
        placeholders = ",".join("?" * len(series))
        rows = self.con.execute(
            f"""SELECT series_id, event_date, MAX(revision)
                FROM observations WHERE series_id IN ({placeholders})
                GROUP BY 1, 2""",
            series,
        ).fetchall()
        return {(r[0], r[1]): r[2] for r in rows if (r[0], r[1]) in keys}

    # ------------------------------------------------------------------- read

    def as_of(
        self,
        as_of: dt.datetime | dt.date | str,
        series_id: str | Sequence[str] | None = None,
        entity: str | Sequence[str] | None = None,
        start: dt.date | str | None = None,
        end: dt.date | str | None = None,
    ) -> pd.DataFrame:
        """Return the world as it was knowable at ``as_of``.

        For each (series_id, entity, event_date) only the highest-revision row
        with ``available_at <= as_of`` survives. Rows published later are
        invisible -- that is the whole point.
        """
        ts = _to_timestamp(as_of)
        where = ["available_at <= ?"]
        params: list[Any] = [ts]

        for col, val in (("series_id", series_id), ("entity", entity)):
            if val is None:
                continue
            vals = [val] if isinstance(val, str) else list(val)
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        if start is not None:
            where.append("event_date >= ?")
            params.append(pd.Timestamp(start).date())
        if end is not None:
            where.append("event_date <= ?")
            params.append(pd.Timestamp(end).date())

        sql = f"""
        WITH visible AS (
            SELECT * FROM observations WHERE {' AND '.join(where)}
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY series_id, entity, event_date
                ORDER BY revision DESC, available_at DESC
            ) AS rn
            FROM visible
        )
        SELECT series_id, entity, event_date, available_at, value, text_value,
               unit, source, revision, meta
        FROM ranked WHERE rn = 1
        ORDER BY series_id, entity, event_date
        """
        return self.con.execute(sql, params).fetch_df()

    def wide(
        self,
        as_of: dt.datetime | dt.date | str,
        series_id: Sequence[str] | None = None,
        **kw: Any,
    ) -> pd.DataFrame:
        """``as_of`` reshaped to a date x series matrix of numeric values."""
        df = self.as_of(as_of, series_id=series_id, **kw)
        if df.empty:
            return pd.DataFrame()
        df["col"] = df["series_id"] + df["entity"].fillna("").radd("|").where(
            df["entity"].notna(), ""
        )
        return (
            df.pivot_table(index="event_date", columns="col", values="value", aggfunc="last")
            .sort_index()
        )

    def revision_history(self, series_id: str, event_date: dt.date | str) -> pd.DataFrame:
        """Every print ever made for one observation -- first print through
        latest revision. Useful for measuring how much a series gets restated."""
        return self.con.execute(
            """SELECT revision, available_at, value, source
               FROM observations WHERE series_id = ? AND event_date = ?
               ORDER BY revision""",
            [series_id, pd.Timestamp(event_date).date()],
        ).fetch_df()

    def coverage(self) -> pd.DataFrame:
        """What do we actually have? Rows, date span and latency per series."""
        return self.con.execute(
            """SELECT series_id, source, COUNT(*) AS rows,
                      COUNT(DISTINCT event_date) AS observations,
                      MIN(event_date) AS first_event, MAX(event_date) AS last_event,
                      MAX(available_at) AS last_seen,
                      AVG(date_diff('day', event_date, CAST(available_at AS DATE)))
                        AS mean_publication_lag_days
               FROM observations GROUP BY 1, 2 ORDER BY 1"""
        ).fetch_df()

    # -------------------------------------------------------------- provenance

    def log_run(
        self, run_id: str, source: str, started: dt.datetime, rows: int, status: str,
        detail: str = "",
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO ingest_runs VALUES (?,?,?,?,?,?,?)",
            [run_id, source, started, dt.datetime.now(dt.UTC).replace(tzinfo=None),
             rows, status, detail[:2000]],
        )

    # ------------------------------------------------------------------ dunder

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> PITStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _to_timestamp(x: dt.datetime | dt.date | str) -> dt.datetime:
    ts = pd.Timestamp(x)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    # A bare date means "end of that day" so same-day publications are visible.
    if ts.normalize() == ts and not isinstance(x, dt.datetime):
        ts = ts + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return ts.to_pydatetime()


def observations_from_frame(
    df: pd.DataFrame,
    series_id: str,
    source: str,
    value_col: str = "value",
    date_col: str = "date",
    available_at: dt.datetime | None = None,
    publication_lag: dt.timedelta | None = None,
    entity_col: str | None = None,
    unit: str | None = None,
) -> list[Observation]:
    """Convert a tidy dataframe to Observations.

    Exactly one of ``available_at`` (a fixed stamp, e.g. now, for data scraped
    today) or ``publication_lag`` (event_date + lag, for series with a known
    release schedule) should be given.
    """
    if (available_at is None) == (publication_lag is None):
        raise ValueError("pass exactly one of available_at or publication_lag")

    out: list[Observation] = []
    for _, row in df.iterrows():
        ed = pd.Timestamp(row[date_col]).date()
        avail = (
            available_at
            if available_at is not None
            else dt.datetime.combine(ed, dt.time(18, 0)) + publication_lag
        )
        val = row[value_col]
        out.append(
            Observation(
                series_id=series_id,
                entity=str(row[entity_col]) if entity_col else None,
                event_date=ed,
                available_at=avail,
                value=None if pd.isna(val) else float(val),
                source=source,
                unit=unit,
            )
        )
    return out
