"""Global markets: commodities, world indices, FX and country macro.

Built for an Indian investor looking outward, which changes what matters.

The central point most global data tools miss: **a rupee investor's return on a
foreign asset is not the foreign return.** It is

    (1 + local return) x (1 + INR depreciation) - 1

Gold rising 10% in dollars while the rupee strengthens 5% is a 5% gain in
Delhi, not 10%. Over the last decade rupee depreciation has contributed a large
share of the return Indian investors earned on US equities -- they were paid
partly for holding dollars, not only for holding stocks. Every price this
module returns can therefore be converted with :func:`to_inr`, and
:func:`inr_return_decomposition` splits a foreign return into the asset part
and the currency part so you can see which one you were actually paid for.

Sources, all free and all verified 2026-09-18:
  LBMA          the authoritative gold and silver benchmark, daily since 1968
  FRED          crude, gas, industrial metals, world indices, global rates
  frankfurter   ECB-published FX, 30 currencies with history
  open.er-api   166 currencies, spot only
  World Bank    217 countries of annual macro
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

import pandas as pd

from vyuha.ingest.base import fetch
from vyuha.ingest.sources import fred_series

# --------------------------------------------------------------- commodities

LBMA_FEEDS = {
    "gold": "gold_pm", "gold_am": "gold_am", "silver": "silver",
}

#: Commodity series that exist on FRED and actually update. Gold and silver are
#: deliberately NOT here -- FRED's LBMA feeds were discontinued and return 404,
#: so precious metals come straight from LBMA instead.
FRED_COMMODITIES = {
    "brent": ("DCOILBRENTEU", "USD/bbl", "daily"),
    "wti": ("DCOILWTICO", "USD/bbl", "daily"),
    "natural_gas": ("DHHNGSP", "USD/MMBtu", "daily"),
    "copper": ("PCOPPUSDM", "USD/tonne", "monthly"),
    "aluminium": ("PALUMUSDM", "USD/tonne", "monthly"),
    "wheat": ("PWHEAMTUSDM", "USD/tonne", "monthly"),
    "commodity_index": ("PALLFNFINDEXM", "index", "monthly"),
}

#: World indices and global rates, all from FRED.
FRED_GLOBAL = {
    "sp500": ("SP500", "index", "United States"),
    "nasdaq": ("NASDAQCOM", "index", "United States"),
    "dow": ("DJIA", "index", "United States"),
    "vix": ("VIXCLS", "index", "United States"),
    "us_10y": ("DGS10", "pct", "United States"),
    "us_2y": ("DGS2", "pct", "United States"),
    "fed_funds": ("DFF", "pct", "United States"),
    "dollar_index": ("DTWEXBGS", "index", "Global"),
    "euro_10y": ("IRLTLT01EZM156N", "pct", "Euro area"),
    "japan_10y": ("IRLTLT01JPM156N", "pct", "Japan"),
    "uk_10y": ("IRLTLT01GBM156N", "pct", "United Kingdom"),
}


def lbma_price(metal: str = "gold", ttl: int = 43_200) -> pd.DataFrame:
    """Daily LBMA precious-metal benchmark in USD, GBP and EUR.

    The London fix is the price the physical market actually settles on, which
    makes it the right benchmark rather than a futures quote. Gold runs back to
    1968 -- roughly 14,700 observations.
    """
    if metal not in LBMA_FEEDS:
        raise ValueError(f"unknown metal {metal!r}; choose from {sorted(LBMA_FEEDS)}")
    payload = fetch(
        f"https://prices.lbma.org.uk/json/{LBMA_FEEDS[metal]}.json",
        ttl=ttl, browser_ua=False,
    ).json()

    rows = []
    for rec in payload:
        vals = rec.get("v") or []
        if not vals or vals[0] is None:
            continue
        rows.append({
            "date": pd.Timestamp(rec["d"]),
            "usd": float(vals[0]),
            "gbp": float(vals[1]) if len(vals) > 1 and vals[1] is not None else None,
            "eur": float(vals[2]) if len(vals) > 2 and vals[2] is not None else None,
        })
    if not rows:
        raise RuntimeError(f"LBMA returned no usable prices for {metal!r}")
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.attrs["source"] = "lbma"
    df.attrs["metal"] = metal
    return df


def commodity(name: str, ttl: int = 43_200) -> pd.DataFrame:
    """One commodity as a tidy date/value frame, from whichever source has it."""
    if name in ("gold", "silver", "gold_am"):
        df = lbma_price(name, ttl=ttl)[["date", "usd"]].rename(columns={"usd": "value"})
        df.attrs.update(source="lbma", unit="USD/oz", commodity=name)
        return df
    if name not in FRED_COMMODITIES:
        raise ValueError(
            f"unknown commodity {name!r}; choose from "
            f"{sorted(set(FRED_COMMODITIES) | set(LBMA_FEEDS) | {'silver'})}"
        )
    sid, unit, freq = FRED_COMMODITIES[name]
    df = fred_series(sid, ttl=ttl)
    df.attrs.update(source="fred", unit=unit, frequency=freq, commodity=name)
    return df


def commodity_snapshot(names: Iterable[str] | None = None) -> pd.DataFrame:
    """Latest value for each commodity, with its date and unit.

    Failures are reported as a row with an ``error`` rather than dropped, so a
    dead upstream source is visible instead of silently narrowing coverage.
    """
    names = list(names or ["gold", "silver", "brent", "wti", "natural_gas",
                           "copper", "aluminium", "wheat"])
    rows = []
    for n in names:
        try:
            df = commodity(n)
            last = df.dropna(subset=["value"]).iloc[-1]
            rows.append({"commodity": n, "value": float(last["value"]),
                         "unit": df.attrs.get("unit"), "date": last["date"].date(),
                         "source": df.attrs.get("source"), "error": ""})
        except Exception as exc:  # noqa: BLE001
            rows.append({"commodity": n, "value": None, "unit": None, "date": None,
                         "source": None, "error": str(exc)[:120]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- indices


def global_index(name: str, ttl: int = 43_200) -> pd.DataFrame:
    """A world index or global rate series."""
    if name not in FRED_GLOBAL:
        raise ValueError(f"unknown series {name!r}; choose from {sorted(FRED_GLOBAL)}")
    sid, unit, region = FRED_GLOBAL[name]
    df = fred_series(sid, ttl=ttl)
    df.attrs.update(source="fred", unit=unit, region=region, series=name)
    return df


def global_snapshot(names: Iterable[str] | None = None) -> pd.DataFrame:
    names = list(names or FRED_GLOBAL)
    rows = []
    for n in names:
        try:
            df = global_index(n)
            last = df.dropna(subset=["value"]).iloc[-1]
            rows.append({"series": n, "value": float(last["value"]),
                         "unit": df.attrs.get("unit"), "region": df.attrs.get("region"),
                         "date": last["date"].date(), "error": ""})
        except Exception as exc:  # noqa: BLE001
            rows.append({"series": n, "value": None, "unit": None, "region": None,
                         "date": None, "error": str(exc)[:120]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------ FX


def fx_spot(base: str = "USD", ttl: int = 3_600) -> dict[str, float]:
    """Spot rates for ~166 currencies against ``base``."""
    payload = fetch(f"https://open.er-api.com/v6/latest/{base.upper()}",
                    ttl=ttl, browser_ua=False).json()
    rates = payload.get("rates") or {}
    if not rates:
        raise RuntimeError(f"no FX rates returned for base {base!r}")
    return {k: float(v) for k, v in rates.items()}


def fx_history(
    base: str = "USD", quote: str = "INR",
    start: str | dt.date | None = None, end: str | dt.date | None = None,
    ttl: int = 43_200,
) -> pd.DataFrame:
    """Daily FX history from frankfurter (ECB reference rates).

    Covers 30 major currencies. ECB publishes on business days only, so there
    are no weekend observations -- do not forward-fill blindly into a daily
    return series without deciding what a non-trading day means.
    """
    start = pd.Timestamp(start or (dt.date.today() - dt.timedelta(days=365))).date()
    end = pd.Timestamp(end).date() if end else dt.date.today()
    payload = fetch(
        f"https://api.frankfurter.dev/v1/{start}..{end}",
        params={"base": base.upper(), "symbols": quote.upper()},
        ttl=ttl, browser_ua=False,
    ).json()
    rates = payload.get("rates") or {}
    if not rates:
        raise RuntimeError(f"no FX history for {base}/{quote} in {start}..{end}")
    rows = [{"date": pd.Timestamp(d), "value": float(v[quote.upper()])}
            for d, v in sorted(rates.items()) if quote.upper() in v]
    df = pd.DataFrame(rows)
    df.attrs.update(source="frankfurter", pair=f"{base.upper()}{quote.upper()}")
    return df


# ------------------------------------------------------- the rupee lens


def to_inr(
    df: pd.DataFrame, from_currency: str = "USD", value_col: str = "value",
    fx: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convert a foreign-currency price series into rupees, date by date.

    Uses the *contemporaneous* exchange rate for each observation, not today's
    rate for the whole history. Converting a ten-year gold series at today's
    USDINR would silently rewrite a decade of returns.
    """
    fx = fx if fx is not None else fx_history(
        from_currency, "INR",
        start=pd.Timestamp(df["date"].min()).date() - dt.timedelta(days=7),
    )
    merged = pd.merge_asof(
        df.sort_values("date"), fx.sort_values("date").rename(columns={"value": "fx"}),
        on="date", direction="backward",
    )
    out = merged.copy()
    out["value_inr"] = out[value_col] * out["fx"]
    out.attrs.update(df.attrs)
    out.attrs["converted_from"] = from_currency
    # Observations before the FX history starts cannot be converted; they are
    # left as NaN rather than filled with a rate that did not exist.
    out.attrs["unconverted_rows"] = int(out["value_inr"].isna().sum())
    return out


def inr_return_decomposition(
    df: pd.DataFrame, from_currency: str = "USD", value_col: str = "value",
    periods: int | None = None,
) -> dict[str, Any]:
    """Split a rupee investor's return into the asset part and the currency part.

    This is the number an Indian investor in a foreign asset actually needs and
    almost never sees. A US fund reporting "+12% this year" delivered something
    different in Delhi, and the difference is not a rounding error: rupee
    depreciation has at times contributed more than half the realised return on
    US equity for Indian holders.
    """
    conv = to_inr(df, from_currency, value_col)
    conv = conv.dropna(subset=["value_inr", value_col, "fx"])
    if len(conv) < 2:
        raise ValueError("need at least two convertible observations")
    if periods:
        conv = conv.tail(periods + 1)

    a0, a1 = float(conv[value_col].iloc[0]), float(conv[value_col].iloc[-1])
    f0, f1 = float(conv["fx"].iloc[0]), float(conv["fx"].iloc[-1])
    asset_ret = a1 / a0 - 1
    fx_ret = f1 / f0 - 1
    total = (1 + asset_ret) * (1 + fx_ret) - 1

    return {
        "start": conv["date"].iloc[0].date(), "end": conv["date"].iloc[-1].date(),
        "local_return": asset_ret,
        "currency_return": fx_ret,
        "total_inr_return": total,
        "interaction": total - asset_ret - fx_ret,
        "currency_share_of_return": (fx_ret / total) if total not in (0.0,) else float("nan"),
        "start_price_local": a0, "end_price_local": a1,
        "start_price_inr": a0 * f0, "end_price_inr": a1 * f1,
        "start_fx": f0, "end_fx": f1,
        "currency": from_currency,
    }


# --------------------------------------------------------------- country macro

WB_INDICATORS = {
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "inflation": "FP.CPI.TOTL.ZG",
    "unemployment": "SL.UEM.TOTL.ZS",
    "current_account": "BN.CAB.XOKA.GD.ZS",
    "govt_debt": "GC.DOD.TOTL.GD.ZS",
    "market_cap_gdp": "CM.MKT.LCAP.GD.ZS",
    "fdi_inflow": "BX.KLT.DINV.WD.GD.ZS",
}


def countries(ttl: int = 604_800) -> pd.DataFrame:
    """All 217 World Bank countries (aggregates such as 'World' excluded)."""
    payload = fetch("https://api.worldbank.org/v2/country",
                    params={"format": "json", "per_page": "400"},
                    ttl=ttl, browser_ua=False).json()
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError("world bank country list unavailable")
    rows = [
        {"iso3": c["id"], "iso2": c["iso2Code"], "name": c["name"],
         "region": c["region"]["value"], "income": c["incomeLevel"]["value"],
         "capital": c.get("capitalCity", "")}
        for c in payload[1] if c["region"]["value"] != "Aggregates"
    ]
    return pd.DataFrame(rows)


def country_macro(iso3: str = "IND", indicator: str = "gdp_growth",
                  ttl: int = 604_800) -> pd.DataFrame:
    """One World Bank indicator for one country.

    Annual and revised for years afterwards, so this is context rather than a
    trading signal. Useful for comparing economies, useless for timing.
    """
    code = WB_INDICATORS.get(indicator, indicator)
    payload = fetch(f"https://api.worldbank.org/v2/country/{iso3}/indicator/{code}",
                    params={"format": "json", "per_page": "500"},
                    ttl=ttl, browser_ua=False).json()
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise RuntimeError(f"no World Bank data for {iso3}/{indicator}")
    rows = [{"date": pd.Timestamp(f"{r['date']}-12-31"), "value": r["value"]}
            for r in payload[1] if r.get("value") is not None]
    if not rows:
        raise RuntimeError(f"World Bank returned only nulls for {iso3}/{indicator}")
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.attrs.update(source="world_bank", country=iso3, indicator=indicator)
    return df


def compare_countries(iso3s: Iterable[str], indicator: str = "gdp_growth") -> pd.DataFrame:
    """One indicator across several countries, aligned by year."""
    out = {}
    for c in iso3s:
        try:
            out[c] = country_macro(c, indicator).set_index("date")["value"]
        except Exception:  # noqa: BLE001 - a missing country is a blank column
            continue
    if not out:
        raise RuntimeError(f"no data for any of {list(iso3s)} / {indicator}")
    return pd.DataFrame(out).sort_index()
