"""Electricity demand -- the best high-frequency real-activity proxy for India.

Daily all-India power demand is barely revised, published within a day, and
available roughly six weeks before the IIP print it anticipates. For nowcasting
Indian industrial activity there is nothing else this good that is also free.

**The upstream situation changed.** Grid-India (formerly POSOCO) served daily
system reports from ``report.grid-india.in``; that hostname no longer resolves
(NXDOMAIN as of 2026-09-18), and ``posoco.in`` returns 502. The reports appear
to have moved behind the main ``grid-india.in`` site, which serves a
JavaScript shell rather than fetchable documents.

So this module routes through the National Power Portal and data.gov.in
instead, and is explicit that the direct Grid-India daily-report path is
currently unavailable rather than pretending otherwise.
"""

from __future__ import annotations

import pandas as pd

from vyuha.ingest.base import fetch
from vyuha.ingest.govdata import resource, search_catalogue

NPP_BASE = "https://npp.gov.in"
GRID_INDIA_STATUS = (
    "report.grid-india.in does not resolve (checked 2026-09-18); posoco.in "
    "returns 502. Daily PSP reports are not currently fetchable from their "
    "historical location."
)


def grid_india_available() -> tuple[bool, str]:
    """Check whether the Grid-India report host is reachable again.

    Kept as a live probe rather than a hardcoded 'broken' so the module starts
    working again by itself if the host comes back.
    """
    try:
        fetch("https://report.grid-india.in/", ttl=0, retries=1, browser_ua=True)
        return True, "report.grid-india.in is reachable"
    except Exception as exc:  # noqa: BLE001
        return False, f"{GRID_INDIA_STATUS} ({type(exc).__name__})"


def search_power_datasets(query: str = "power supply position") -> pd.DataFrame:
    """Find power-related resources on data.gov.in."""
    return search_catalogue(query)


def power_resource(resource_id: str, **kw) -> pd.DataFrame:
    """Fetch a specific data.gov.in power dataset by resource id."""
    return resource(resource_id, **kw)


def npp_reachable() -> tuple[bool, str]:
    """Is the National Power Portal serving?"""
    try:
        r = fetch(f"{NPP_BASE}/publishedReports", ttl=0, retries=1, browser_ua=True)
        return True, f"npp.gov.in reachable ({len(r.content)} bytes)"
    except Exception as exc:  # noqa: BLE001
        return False, f"npp.gov.in unreachable: {exc}"
