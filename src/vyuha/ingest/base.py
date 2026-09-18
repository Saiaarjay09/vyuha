"""HTTP plumbing for data ingestion: caching, retries, politeness, provenance.

Design rules, learned the hard way from Indian public data sources:

  cache first     Most of these endpoints are slow, rate-limited, or flaky.
                  Everything is cached on disk keyed by URL+params, so a
                  re-run of a pipeline costs nothing and a source going down
                  does not destroy a day's work.
  be polite       A fixed minimum interval between requests to the same host.
                  These are public services, several of them run by government
                  bodies on modest infrastructure. Do not hammer them.
  session warmup  NSE in particular rejects requests without cookies obtained
                  by first visiting the homepage with a browser-like UA.
  never silently  A failed fetch raises or returns None with the reason logged.
  fabricate       Nothing in Vyuha ever substitutes a plausible value for a
                  missing one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from vyuha.config import settings

log = logging.getLogger("vyuha.ingest")

_last_request: dict[str, float] = {}

# Per-host minimum seconds between requests. Several of these are stated
# politely in the providers' own documentation and we honour them rather than
# discovering them via 429s: GDELT asks for one request every 5 seconds, and
# will hand back a plain-text scolding instead of JSON if you do not listen.
HOST_RATE_LIMITS: dict[str, float] = {
    "api.gdeltproject.org": 5.5,
    "query1.finance.yahoo.com": 2.0,
    "query2.finance.yahoo.com": 2.0,
    "www.nseindia.com": 1.0,
    "nsearchives.nseindia.com": 1.0,
    "api.worldbank.org": 1.0,
    "fred.stlouisfed.org": 1.0,
    "portal.amfiindia.com": 2.0,
}


@dataclass(slots=True)
class FetchResult:
    content: bytes
    url: str
    from_cache: bool
    status: int = 200
    fetched_at: float = 0.0

    def json(self) -> Any:
        return json.loads(self.content)

    def text(self, encoding: str = "utf-8") -> str:
        return self.content.decode(encoding, errors="replace")


def _cache_path(url: str, params: dict | None) -> Path:
    key = hashlib.sha256(f"{url}|{json.dumps(params or {}, sort_keys=True)}".encode()).hexdigest()
    host = httpx.URL(url).host or "unknown"
    d = settings.cache_dir / host
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.bin"


def _throttle(url: str) -> None:
    host = httpx.URL(url).host or ""
    interval = HOST_RATE_LIMITS.get(host, settings.min_request_interval)
    now = time.time()
    wait = interval - (now - _last_request.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.time()


def fetch(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    use_cache: bool = True,
    ttl: int | None = None,
    client: httpx.Client | None = None,
    retries: int | None = None,
    browser_ua: bool = True,
) -> FetchResult:
    """GET with disk cache, exponential backoff and host throttling.

    ``browser_ua`` selects which User-Agent identity to present. This is not
    cosmetic: bot-detection policies across these sources actively conflict.
    NSE refuses anything that does not look like a browser, while FRED's CDN
    silently *black-holes* requests carrying a Chrome User-Agent (the
    connection opens and the body never arrives). Pass ``browser_ua=False``
    for plain API endpoints, which is also the more honest identification.
    """
    path = _cache_path(url, params)
    ttl = settings.cache_ttl_seconds if ttl is None else ttl

    if use_cache and path.exists() and (ttl <= 0 or time.time() - path.stat().st_mtime < ttl):
        return FetchResult(path.read_bytes(), url, True, fetched_at=path.stat().st_mtime)

    hdrs = {
        "User-Agent": settings.user_agent if browser_ua else settings.api_user_agent,
        "Accept": "application/json, text/plain, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        **(headers or {}),
    }
    own = client is None
    c = client or httpx.Client(timeout=settings.http_timeout, follow_redirects=True)
    attempts = settings.http_retries if retries is None else retries
    last: Exception | None = None
    try:
        for attempt in range(attempts):
            try:
                _throttle(url)
                r = c.get(url, params=params, headers=hdrs)
                r.raise_for_status()
                path.write_bytes(r.content)
                return FetchResult(r.content, str(r.url), False, r.status_code, time.time())
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < attempts - 1:
                    rate_limited = isinstance(exc, httpx.HTTPStatusError) and (
                        exc.response.status_code == 429
                    )
                    host = httpx.URL(url).host or ""
                    base_wait = HOST_RATE_LIMITS.get(host, settings.min_request_interval)
                    # A 429 means back off by at least the host's stated interval.
                    delay = max(base_wait * 2, 1.5 * (2**attempt)) if rate_limited \
                        else 1.5 * (2**attempt)
                    time.sleep(delay)
                    log.warning("retry %d/%d for %s (wait %.1fs): %s",
                                attempt + 1, attempts, url, delay, exc)
    finally:
        if own:
            c.close()

    # Stale cache beats no data, as long as the staleness is announced.
    if path.exists():
        log.warning("fetch failed for %s (%s); serving STALE cache", url, last)
        return FetchResult(path.read_bytes(), url, True, 0, path.stat().st_mtime)
    raise RuntimeError(f"fetch failed for {url}: {last}")


class NSESession:
    """NSE's public JSON API refuses to talk to you without a warmed-up cookie jar.

    The sequence that works: hit the homepage with a browser-like User-Agent,
    keep the cookies, then call the api/ endpoints with a Referer. Cookies
    expire, so the session re-warms on a 401/403.

    These are the same public endpoints the nseindia.com site itself calls.
    Keep request rates low and respect the site's terms; this is not a licensed
    market-data feed and must not be treated as one.
    """

    BASE = "https://www.nseindia.com"

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=settings.http_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "*/*",
            },
        )
        self._warm = False

    def warm(self, force: bool = False) -> None:
        if self._warm and not force:
            return
        try:
            _throttle(self.BASE)
            self.client.get(self.BASE, timeout=20.0)
            _throttle(self.BASE)
            self.client.get(f"{self.BASE}/market-data/live-equity-market", timeout=20.0)
            self._warm = True
        except Exception as exc:  # noqa: BLE001
            log.warning("NSE session warmup failed: %s", exc)

    def get_json(self, path: str, params: dict | None = None, use_cache: bool = True,
                 ttl: int | None = None) -> Any:
        self.warm()
        url = f"{self.BASE}{path}"
        try:
            res = fetch(url, params=params, headers={"Referer": f"{self.BASE}/"},
                        use_cache=use_cache, ttl=ttl, client=self.client)
            return res.json()
        except Exception:
            self.warm(force=True)
            res = fetch(url, params=params, headers={"Referer": f"{self.BASE}/"},
                        use_cache=False, client=self.client)
            return res.json()

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "NSESession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
