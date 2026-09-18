"""Concrete fetchers.

Every function here returns a tidy DataFrame and records where the data came
from. Anything that cannot be fetched raises -- no silent empty frames, because
an empty frame flowing into a risk model produces a confident zero.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pandas as pd

from vyuha.config import settings
from vyuha.ingest.base import NSESession, fetch

# --------------------------------------------------------------------- equity


def stooq_history(symbol: str = "^nsei", ttl: int = 86_400) -> pd.DataFrame:
    """Stooq daily OHLCV -- CURRENTLY BLOCKED.

    Stooq put its CSV endpoint behind a JavaScript proof-of-work challenge
    (a SHA-256 grind posted back to /__verify) some time before 2026-09. Plain
    HTTP clients get an HTML challenge page instead of data, regardless of
    headers. Solving it would mean running a JS engine and deliberately
    defeating an anti-bot measure, which is not something this project does.

    Use :func:`yahoo_history` for index history instead. Kept in the catalogue
    with status BLOCKED so the change is visible rather than silently rotting.
    """
    raise NotImplementedError(
        "Stooq is behind a JS proof-of-work challenge and is no longer usable "
        "from a plain HTTP client. Use yahoo_history() for index OHLCV."
    )


def yahoo_history(
    symbol: str = "^NSEI", range_: str = "5y", interval: str = "1d", ttl: int = 86_400
) -> pd.DataFrame:
    """OHLCV from Yahoo's chart endpoint.

    NSE equities use the ``.NS`` suffix (``RELIANCE.NS``), BSE uses ``.BO``.
    """
    res = fetch(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": range_, "interval": interval, "events": "div,split"},
        ttl=ttl,
    )
    payload = res.json()
    result = (payload.get("chart") or {}).get("result")
    if not result:
        err = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"yahoo returned no data for {symbol!r}: {err}")
    r = result[0]
    quote = r["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC")
                      .tz_convert("Asia/Kolkata").tz_localize(None).normalize(),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        }
    )
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj:
        df["adj_close"] = adj
    df.attrs["source"] = "yahoo"
    df.attrs["symbol"] = symbol
    return df.dropna(subset=["close"]).reset_index(drop=True)


# ---------------------------------------------------------------------- funds


def amfi_nav(ttl: int = 43_200) -> pd.DataFrame:
    """Every Indian mutual fund NAV for the latest published day.

    AMFI publishes one semicolon-delimited text file covering every scheme in
    India, grouped under AMC and scheme-category header lines. Genuinely open,
    no API key.

    The parser is **header-driven** rather than positional, deliberately. AMFI
    has changed this layout before -- it gained separate ``Plan`` and ``Option``
    columns, which silently shifted NAV from field 4 to field 6 and turned a
    positional parser into one that produced zero rows with no error. Reading
    the header means a future column insertion is survivable, and a column
    *rename* raises loudly instead of returning an empty frame.
    """
    res = fetch("https://portal.amfiindia.com/spages/NAVAll.txt", ttl=ttl,
                browser_ua=False)
    lines = res.text().replace("\r\n", "\n").replace("\r", "\n").splitlines()

    header_idx = next((i for i, ln in enumerate(lines) if ln.startswith("Scheme Code;")), None)
    if header_idx is None:
        raise RuntimeError("AMFI file has no 'Scheme Code;' header row -- format changed")

    cols = [c.strip() for c in lines[header_idx].split(";")]

    def find(*needles: str) -> int:
        for i, c in enumerate(cols):
            low = c.lower()
            if all(n in low for n in needles):
                return i
        raise RuntimeError(f"AMFI header missing a column matching {needles}; got {cols}")

    i_code, i_name = find("scheme", "code"), find("scheme", "name")
    i_nav, i_date = find("net asset value"), find("date")
    i_isin_g = find("isin", "growth")
    i_plan = next((i for i, c in enumerate(cols) if c.strip().lower() == "plan"), None)
    i_option = next((i for i, c in enumerate(cols) if c.strip().lower() == "option"), None)
    width = len(cols)

    rows: list[dict[str, Any]] = []
    amc = category = ""
    skipped_na = 0
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            # Category headers look like "Open Ended Schemes(...)"; anything
            # else at this level is an AMC name.
            if "Schemes(" in line or line.endswith(")"):
                category = line
            else:
                amc = line
            continue
        parts = line.split(";")
        if len(parts) < width:
            continue
        try:
            nav = float(parts[i_nav])
        except ValueError:
            skipped_na += 1       # schemes quoting "N.A."
            continue
        try:
            d = pd.to_datetime(parts[i_date].strip(), format="%d-%b-%Y").date()
        except (ValueError, TypeError):
            continue
        rows.append({
            "scheme_code": parts[i_code].strip(),
            "isin_growth": (parts[i_isin_g].strip() or None),
            "scheme_name": parts[i_name].strip(),
            "plan": parts[i_plan].strip() if i_plan is not None else None,
            "option": parts[i_option].strip() if i_option is not None else None,
            "nav": nav, "date": d, "amc": amc, "category": category,
        })

    if not rows:
        raise RuntimeError(
            f"AMFI NAV parsed to zero rows from {len(lines)} lines (header at "
            f"{header_idx}, columns={cols}) -- format may have changed again"
        )
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.attrs["source"] = "amfi"
    df.attrs["schemes_skipped_na"] = skipped_na
    return df


# --------------------------------------------------------------------- global


def fred_series(series_id: str = "DGS10", ttl: int = 43_200) -> pd.DataFrame:
    """A FRED series via the public CSV endpoint (no API key required).

    Handy ids: ``DGS10`` US 10Y, ``DTWEXBGS`` broad dollar index,
    ``DFF`` fed funds, ``DCOILBRENTEU`` Brent, ``CPIAUCSL`` US CPI.
    """
    res = fetch(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series_id}, ttl=ttl, browser_ua=False,
    )
    df = pd.read_csv(io.StringIO(res.text()))
    date_col = df.columns[0]
    df = df.rename(columns={date_col: "date", df.columns[1]: "value"})
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    df.attrs["source"] = "fred"
    df.attrs["series_id"] = series_id
    return df.dropna(subset=["value"]).reset_index(drop=True)


def world_bank(indicator: str = "NY.GDP.MKTP.KD.ZG", country: str = "IND",
               ttl: int = 604_800) -> pd.DataFrame:
    """Annual World Bank indicator. CC-BY 4.0 -- redistributable."""
    res = fetch(
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
        params={"format": "json", "per_page": "500"}, ttl=ttl, browser_ua=False,
    )
    payload = res.json()
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise RuntimeError(f"world bank returned no data for {indicator}/{country}")
    df = pd.DataFrame(
        [{"date": pd.Timestamp(f"{r['date']}-12-31"), "value": r["value"]}
         for r in payload[1] if r.get("value") is not None]
    ).sort_values("date").reset_index(drop=True)
    df.attrs["source"] = "world_bank"
    df.attrs["indicator"] = indicator
    return df


def gdelt_tone(
    query: str = "india economy", timespan: str = "3months", ttl: int = 3_600
) -> pd.DataFrame:
    """News tone timeline from GDELT.

    Tone runs roughly -10 (very negative) to +10. The absolute level is not
    meaningful across queries -- normalise against a trailing window.
    """
    res = fetch(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={"query": query, "mode": "timelinetone", "timespan": timespan,
                "format": "json"},
        ttl=ttl, browser_ua=False,
    )
    body = res.text()
    if "limit requests" in body[:300].lower():
        raise RuntimeError(
            "GDELT rate limit hit (it asks for one request every 5 seconds). "
            "HOST_RATE_LIMITS already enforces this -- if you see it, something "
            "is bypassing the throttle or another process is querying GDELT."
        )
    try:
        payload = res.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GDELT returned non-JSON: {body[:200]!r}") from exc
    tl = payload.get("timeline") or []
    if not tl:
        raise RuntimeError(
            f"GDELT returned an empty timeline for {query!r}. Either the query "
            "matched nothing in this window, or the response was throttled."
        )
    df = pd.DataFrame(tl[0]["data"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.rename(columns={"value": "tone"})
    df.attrs["source"] = "gdelt"
    df.attrs["query"] = query
    return df[["date", "tone"]]


# ------------------------------------------------------------------------ NSE


def nse_all_indices(session: NSESession | None = None, ttl: int = 300) -> pd.DataFrame:
    """Live levels for every NSE index, including India VIX.

    FRAGILE: undocumented endpoint behind bot protection. Fails politely.
    """
    own = session is None
    s = session or NSESession()
    try:
        data = s.get_json("/api/allIndices", ttl=ttl)
        df = pd.DataFrame(data["data"])
        df.attrs["source"] = "nse"
        df.attrs["fetched_at"] = dt.datetime.now().isoformat()
        return df
    finally:
        if own:
            s.close()


def nse_fii_dii(session: NSESession | None = None, ttl: int = 3_600) -> pd.DataFrame:
    """Daily FII and DII cash-segment activity. FRAGILE."""
    own = session is None
    s = session or NSESession()
    try:
        data = s.get_json("/api/fiidiiTradeReact", ttl=ttl)
        df = pd.DataFrame(data)
        df.attrs["source"] = "nse"
        return df
    finally:
        if own:
            s.close()


def nse_option_expiries(
    symbol: str = "NIFTY", session: NSESession | None = None, ttl: int = 3_600
) -> list[str]:
    """Available expiry dates for an index option chain."""
    own = session is None
    s = session or NSESession()
    try:
        info = s.get_json("/api/option-chain-contract-info",
                          params={"symbol": symbol}, ttl=ttl)
        return list(info.get("expiryDates") or [])
    finally:
        if own:
            s.close()


def nse_option_chain(
    symbol: str = "NIFTY",
    session: NSESession | None = None,
    expiry: str | None = None,
    all_expiries: bool = False,
    ttl: int = 300,
) -> pd.DataFrame:
    """Index option chain: strike, OI, change in OI, IV, volume per side.

    The implied distribution recoverable from this is the market's own
    forecast, which makes it the natural benchmark to score the council
    against -- the best calibration check freely available for this market.

    NSE replaced ``/api/option-chain-indices`` with ``/api/option-chain-v3``,
    which returns an empty object unless an ``expiry`` is supplied. When none
    is given we resolve the nearest expiry first. FRAGILE: undocumented and
    subject to change without notice, as this very migration demonstrates.
    """
    own = session is None
    s = session or NSESession()
    try:
        expiries = [expiry] if expiry else nse_option_expiries(symbol, s, ttl=3_600)
        if not expiries or expiries == [None]:
            raise RuntimeError(f"no expiries returned for {symbol!r}")
        if not all_expiries:
            expiries = expiries[:1]

        rows: list[dict[str, Any]] = []
        underlying = None
        timestamp = None
        for exp in expiries:
            data = s.get_json(
                "/api/option-chain-v3",
                params={"type": "Indices", "symbol": symbol, "expiry": exp}, ttl=ttl,
            )
            records = data.get("records") or {}
            underlying = records.get("underlyingValue", underlying)
            timestamp = records.get("timestamp", timestamp)
            for rec in records.get("data") or []:
                for side in ("CE", "PE"):
                    leg = rec.get(side)
                    if not leg:
                        continue
                    rows.append({
                        "strike": leg.get("strikePrice", rec.get("strikePrice")),
                        "expiry": rec.get("expiryDates", exp),
                        "side": side,
                        "oi": leg.get("openInterest"),
                        "change_oi": leg.get("changeinOpenInterest"),
                        "volume": leg.get("totalTradedVolume"),
                        "iv": leg.get("impliedVolatility"),
                        "ltp": leg.get("lastPrice"),
                        "bid": leg.get("buyPrice1"),
                        "ask": leg.get("sellPrice1"),
                    })
        if not rows:
            raise RuntimeError(
                f"option chain for {symbol!r} parsed to zero rows "
                f"(expiries tried: {expiries})"
            )
        df = pd.DataFrame(rows)
        df.attrs["source"] = "nse"
        df.attrs["underlying"] = underlying
        df.attrs["timestamp"] = timestamp
        df.attrs["expiries"] = expiries
        return df
    finally:
        if own:
            s.close()


def put_call_ratio(chain: pd.DataFrame) -> float:
    """OI-weighted put-call ratio. Above ~1.3 is historically crowded-bearish,
    below ~0.7 crowded-bullish -- but the thresholds drift, so z-score it."""
    oi = chain.groupby("side")["oi"].sum(min_count=1)
    ce = float(oi.get("CE", 0.0))
    if ce <= 0:
        return float("nan")
    return float(oi.get("PE", 0.0) / ce)
