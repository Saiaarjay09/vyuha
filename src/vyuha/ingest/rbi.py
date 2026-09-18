"""Reserve Bank of India.

The RBI publishes an enormous amount, almost none of it as an API. The
Database on Indian Economy (DBIE) at data.rbi.org.in is an Angular
single-page app whose data layer is not documented; the Weekly Statistical
Supplement and the various archives are ASP.NET pages returning HTML tables.

What works reliably, and what this module provides, is the **current rates
block on the RBI homepage** -- policy rates, reserve ratios and reference
exchange rates, all in one place, updated the moment they change. For a risk
system that is the highest-value RBI data per unit of parsing effort, and it
is the set the `hawk`, `dove` and `policy` personas reason from directly.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any

import pandas as pd

from vyuha.ingest.base import fetch

RBI_HOME = "https://www.rbi.org.in/"

# Label on the RBI site -> (our series id, unit)
_RATE_MAP: dict[str, tuple[str, str]] = {
    "policy repo rate": ("REPO_RATE", "pct"),
    "standing deposit facility rate": ("SDF_RATE", "pct"),
    "marginal standing facility rate": ("MSF_RATE", "pct"),
    "bank rate": ("BANK_RATE", "pct"),
    "fixed reverse repo rate": ("REVERSE_REPO_RATE", "pct"),
    "crr": ("CRR", "pct"),
    "slr": ("SLR", "pct"),
    "inr / 1 usd": ("USDINR", "INR"),
    "inr / 1 gbp": ("GBPINR", "INR"),
    "inr / 1 eur": ("EURINR", "INR"),
    "inr / 100 jpy": ("JPYINR_100", "INR"),
}


def _tokens(page: str) -> list[str]:
    """Flatten the rates block to an alternating label/value token list."""
    low = page.lower()
    i = low.find("policy repo rate")
    if i == -1:
        raise RuntimeError(
            "RBI homepage no longer contains a 'Policy Repo Rate' block -- layout changed"
        )
    seg = page[max(0, i - 400): i + 4000]
    seg = re.sub(r"<script.*?</script>", "", seg, flags=re.S)
    seg = re.sub(r"<[^>]+>", "\x01", seg)
    seg = html.unescape(seg).replace("\xa0", " ")
    return [t.strip() for t in seg.split("\x01") if t.strip()]


def rbi_current_rates(ttl: int = 3_600) -> pd.DataFrame:
    """Current policy rates, reserve ratios and reference FX rates.

    Returns tidy rows: series_id, label, value, unit.

    The RBI site needs a browser User-Agent. Values are the *current* level,
    so ``event_date`` is the fetch date -- these are not a history. For a
    history of policy changes you need the MPC statement archive.
    """
    page = fetch(RBI_HOME, ttl=ttl, browser_ua=True).text()
    toks = _tokens(page)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, tok in enumerate(toks):
        key = re.sub(r"\s+", " ", tok.strip().rstrip(":")).lower()
        if key not in _RATE_MAP or key in seen:
            continue
        # The value is in one of the next couple of tokens, as ": 5.25%".
        for nxt in toks[idx + 1: idx + 4]:
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%?", nxt)
            if m and (":" in nxt or "%" in nxt or nxt.strip()[0].isdigit()):
                sid, unit = _RATE_MAP[key]
                rows.append({
                    "series_id": sid, "label": tok.strip().rstrip(":"),
                    "value": float(m.group(1)), "unit": unit,
                    "date": dt.date.today(), "source": "RBI",
                })
                seen.add(key)
                break

    if not rows:
        raise RuntimeError("RBI rates block found but no values parsed -- layout changed")
    df = pd.DataFrame(rows)
    df.attrs["source"] = "rbi"
    df.attrs["fetched_at"] = dt.datetime.now().isoformat()
    return df


def rbi_reference_rate_archive(ttl: int = 43_200) -> pd.DataFrame:
    """RBI daily reference rates for USD, EUR, GBP and JPY.

    Parses the archive page's HTML table. FRAGILE: an ASP.NET page whose
    markup changes without notice.
    """
    url = "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx"
    page = fetch(url, ttl=ttl, browser_ua=True).text()
    try:
        tables = pd.read_html(page)
    except ValueError as exc:
        raise RuntimeError(f"no HTML tables found on {url}") from exc

    best = max(tables, key=len) if tables else None
    if best is None or best.empty:
        raise RuntimeError("RBI reference rate archive returned no usable table")
    best.attrs["source"] = "rbi"
    return best


def to_observations(df: pd.DataFrame) -> list:
    """Convert :func:`rbi_current_rates` output to PIT Observations.

    ``available_at`` is the fetch time: these are scraped current levels, and
    we genuinely do not know when each last changed, so claiming an earlier
    availability would be a lie the point-in-time store would then propagate.
    """
    from vyuha.store.pit import Observation

    now = dt.datetime.now()
    return [
        Observation(
            series_id=str(r["series_id"]), event_date=r["date"], available_at=now,
            value=float(r["value"]), unit=str(r["unit"]), source="RBI",
            meta={"label": r["label"]},
        )
        for _, r in df.iterrows()
    ]
