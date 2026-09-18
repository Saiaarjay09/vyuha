"""data.gov.in -- the Open Government Data platform.

This is the best redistribution story of anything in the catalogue: the
Government Open Data Licence - India actually permits reuse, unlike the
exchange endpoints which are merely reachable. It carries MOSPI's CPI and IIP
series, power generation, vehicle registrations and roughly 288,000 other
resources.

Two things to know before relying on it:

1. **There is no working full-text search in the API.** The ``/lists``
   endpoint accepts a ``q`` parameter and silently ignores it -- you get the
   same first page whatever you ask for. Searching therefore means paging the
   catalogue and filtering locally, which :func:`search_catalogue` does with
   an on-disk cache so you pay the cost once.

2. **Resource schemas are not uniform.** Each dataset defines its own field
   names, so a generic fetcher can only hand you a DataFrame; mapping columns
   to series is per-dataset work.

The published sample key below is data.gov.in's own public demo key. It works
and is rate-limited; get a free key of your own at
https://data.gov.in/help/how-use-datasets-apis and set ``VYUHA_DATA_GOV_IN_KEY``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from vyuha.config import settings
from vyuha.ingest.base import fetch

BASE = "https://api.data.gov.in"
SAMPLE_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"


def _key() -> str:
    return settings.data_gov_in_key or SAMPLE_KEY


def resource(
    resource_id: str, limit: int = 1000, offset: int = 0, ttl: int = 43_200,
    **filters: str,
) -> pd.DataFrame:
    """Fetch one data.gov.in resource as a DataFrame.

    ``filters`` are passed through as ``filters[field]=value``.
    """
    params: dict[str, Any] = {
        "api-key": _key(), "format": "json", "limit": str(limit), "offset": str(offset),
    }
    for k, v in filters.items():
        params[f"filters[{k}]"] = v

    payload = fetch(f"{BASE}/resource/{resource_id}", params=params, ttl=ttl,
                    browser_ua=False).json()
    if payload.get("status") == "error":
        raise RuntimeError(
            f"data.gov.in error for resource {resource_id!r}: "
            f"{payload.get('message', 'unknown')}"
        )
    records = payload.get("records") or []
    if not records:
        raise RuntimeError(
            f"resource {resource_id!r} returned zero records "
            f"(total reported: {payload.get('total')})"
        )
    df = pd.DataFrame(records)
    df.attrs["source"] = "data.gov.in"
    df.attrs["resource_id"] = resource_id
    df.attrs["total_available"] = payload.get("total")
    return df


def _catalogue_page(limit: int, offset: int, ttl: int) -> list[dict]:
    payload = fetch(
        f"{BASE}/lists",
        params={"api-key": _key(), "format": "json",
                "limit": str(limit), "offset": str(offset)},
        ttl=ttl, browser_ua=False,
    ).json()
    return payload.get("records") or []


def iter_catalogue(
    max_records: int = 20_000, page_size: int = 500, ttl: int = 604_800
) -> Iterator[dict]:
    """Page through the resource catalogue.

    The full catalogue is ~288,000 resources, which at 500 per request is 576
    calls -- slow but cached for a week. ``max_records`` bounds it so an
    interactive search does not stall for ten minutes.
    """
    fetched = 0
    offset = 0
    while fetched < max_records:
        page = _catalogue_page(min(page_size, max_records - fetched), offset, ttl)
        if not page:
            return
        yield from page
        fetched += len(page)
        offset += len(page)


def search_catalogue(
    query: str, max_records: int = 20_000, index_path: Path | None = None
) -> pd.DataFrame:
    """Find resources whose title or description matches every word in ``query``.

    Builds and caches a local index the first time, because the upstream API's
    own ``q`` parameter does not work.
    """
    index_path = index_path or (settings.cache_dir / "data_gov_index.jsonl")
    if not index_path.exists() or index_path.stat().st_size == 0:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("w") as fh:
            for rec in iter_catalogue(max_records=max_records):
                fh.write(json.dumps({
                    "id": rec.get("index_name"), "title": rec.get("title", ""),
                    "desc": (rec.get("desc") or "")[:300],
                    "org": rec.get("org_type", ""), "source": rec.get("source", ""),
                }) + "\n")

    words = [w for w in query.lower().split() if w]
    rows = []
    with index_path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            hay = f"{rec['title']} {rec['desc']}".lower()
            if all(w in hay for w in words):
                rows.append(rec)
    return pd.DataFrame(rows)


def index_size(index_path: Path | None = None) -> int:
    p = index_path or (settings.cache_dir / "data_gov_index.jsonl")
    if not p.exists():
        return 0
    return sum(1 for _ in p.open())
