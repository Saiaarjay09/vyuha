"""Registry of free / open data sources for Indian markets.

This is the map of what Vyuha can see. It is deliberately a *data structure*
rather than prose, so the CLI can list it, tests can check it, coverage reports
can diff against it, and nobody has to trust a README that drifted.

Each entry records a ``status`` you should actually read:

    WORKING   fetcher implemented and verified against the live source, on the
              date in ``last_verified``
    FRAGILE   verified working, but the endpoint is undocumented, rate-limited
              or otherwise liable to change without notice (every NSE JSON path
              is in this category -- the option chain moved from
              /api/option-chain-indices to /api/option-chain-v3 and started
              requiring an expiry parameter, with no announcement)
    BLOCKED   was usable, now actively prevents automated access
    PLANNED   catalogued, fetcher not yet written

and a ``licence`` field, because "publicly reachable" is not the same as
"licensed for redistribution". Several of these -- NSE and BSE especially --
are website endpoints under terms of use, not open data feeds. Vyuha fetches
them at low rates for personal research. Redistributing the raw data or using
it commercially is between you and the exchange, and you should read their
terms before doing either.

``update_freq`` and ``typical_lag`` feed the point-in-time layer: they are how
the system knows a CPI print for March is not knowable until mid-April.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    WORKING = "working"
    BLOCKED = "blocked"
    PLANNED = "planned"
    FRAGILE = "fragile"


class Domain(str, Enum):
    EQUITY = "equity"
    DERIVATIVES = "derivatives"
    FIXED_INCOME = "fixed_income"
    FX = "fx"
    COMMODITY = "commodity"
    MACRO = "macro"
    FLOWS = "flows"
    CREDIT = "credit"
    FUNDS = "funds"
    CORPORATE = "corporate"
    ALT = "alternative"
    GLOBAL = "global"
    SENTIMENT = "sentiment"
    POLICY = "policy"


@dataclass(slots=True, frozen=True)
class SourceSpec:
    key: str
    name: str
    domain: Domain
    url: str
    description: str
    status: Status = Status.PLANNED
    update_freq: str = "daily"
    typical_lag: str = "1 day"
    licence: str = "see site terms"
    needs_key: bool = False
    series: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    last_verified: str = ""   # ISO date this fetcher was last run against the live source


CATALOGUE: tuple[SourceSpec, ...] = (
    # ------------------------------------------------------------ EQUITY ----
    SourceSpec(
        "nse_bhavcopy", "NSE Daily Bhavcopy (UDiFF)", Domain.EQUITY,
        "https://nsearchives.nseindia.com/content/cm/",
        "Full end-of-day OHLCV for every NSE cash-market security.",
        Status.FRAGILE, "daily", "same day ~18:00 IST", "NSE terms of use",
        series=("EQ_OPEN", "EQ_HIGH", "EQ_LOW", "EQ_CLOSE", "EQ_VOLUME", "EQ_DELIV_PCT"),
        notes="Prices are NOT adjusted for corporate actions. Join to the corporate "
              "actions feed before computing returns or every split becomes a -50% day.",
    ),
    SourceSpec(
        "nse_indices", "NSE Index Levels", Domain.EQUITY,
        "https://www.nseindia.com/api/allIndices",
        "Live and EOD levels for Nifty 50, Bank Nifty, sectoral and thematic indices.",
        Status.FRAGILE, "realtime", "seconds", "NSE terms of use",
        series=("NIFTY50_CLOSE", "BANKNIFTY_CLOSE", "NIFTY_MIDCAP_CLOSE"),
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "niftyindices_hist", "NIFTY Indices Historical", Domain.EQUITY,
        "https://niftyindices.com/reports/historical-data",
        "Long index history plus daily P/E, P/B and dividend yield per index.",
        Status.PLANNED, "daily", "1 day", "NSE Indices terms",
        series=("NIFTY_PE", "NIFTY_PB", "NIFTY_DIV_YIELD"),
        notes="The valuation series here are the cleanest free source of index P/E "
              "for India and are what the valuation persona reasons from.",
    ),
    SourceSpec(
        "bse_bhavcopy", "BSE Daily Bhavcopy", Domain.EQUITY,
        "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
        "End-of-day OHLCV for BSE-listed securities; wider small-cap coverage than NSE.",
        Status.PLANNED, "daily", "same day", "BSE terms of use",
    ),
    SourceSpec(
        "stooq_index", "Stooq Index History", Domain.EQUITY,
        "https://stooq.com/q/d/l/?s=^nsei&i=d",
        "Free CSV daily history for world indices including ^NSEI and ^SNX.",
        Status.BLOCKED, "daily", "1 day", "free for personal use",
        series=("NIFTY50_CLOSE", "SENSEX_CLOSE"),
        notes="BLOCKED as of 2026-09: Stooq now serves a JavaScript proof-of-work "
              "challenge instead of CSV to non-browser clients. Use Yahoo instead.",
    ),
    SourceSpec(
        "yahoo_chart", "Yahoo Finance Chart API", Domain.EQUITY,
        "https://query1.finance.yahoo.com/v8/finance/chart/",
        "OHLCV for NSE tickers (SYMBOL.NS), indices and global assets.",
        Status.FRAGILE, "daily", "1 day", "Yahoo terms; personal use",
        series=("PX_CLOSE", "PX_VOLUME"),
        notes="Split/dividend adjusted series available, which makes it a useful "
              "cross-check against unadjusted bhavcopy prices.",
    ),

    # ------------------------------------------------------- DERIVATIVES ----
    SourceSpec(
        "nse_option_chain", "NSE Option Chain", Domain.DERIVATIVES,
        "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY",
        "Full option chain: strikes, OI, change in OI, IV, volume for index options.",
        Status.FRAGILE, "realtime", "seconds", "NSE terms of use",
        series=("PCR_NIFTY", "NIFTY_OI", "NIFTY_IV_ATM", "MAX_PAIN"),
        notes="The richest free forward-looking dataset in Indian markets. The implied "
              "distribution from the chain is a market-priced view to compare the "
              "council's forecast against -- the single best calibration check available.",
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "nse_vix", "India VIX", Domain.DERIVATIVES,
        "https://www.nseindia.com/api/allIndices",
        "NSE's implied volatility index, derived from Nifty option prices.",
        Status.FRAGILE, "realtime", "seconds", "NSE terms of use",
        series=("INDIA_VIX",),
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "nse_fo_bhavcopy", "NSE F&O Bhavcopy", Domain.DERIVATIVES,
        "https://nsearchives.nseindia.com/content/fo/",
        "EOD futures and options: settlement price, OI, contracts traded.",
        Status.PLANNED, "daily", "same day", "NSE terms of use",
    ),
    SourceSpec(
        "nse_participant_oi", "Participant-wise Open Interest", Domain.FLOWS,
        "https://www.nseindia.com/reports/fii-derivatives",
        "FII / DII / Pro / Client long-short positioning in index and stock derivatives.",
        Status.PLANNED, "daily", "1 day", "NSE terms of use",
        series=("FII_INDEX_FUT_LS", "FII_INDEX_OPT_LS", "CLIENT_LS"),
        notes="Directly feeds the positioning persona. Extremes here have historically "
              "preceded reversals better than any valuation measure.",
    ),

    # ------------------------------------------------------------- FLOWS ----
    SourceSpec(
        "nse_fii_dii", "FII / DII Cash Flows", Domain.FLOWS,
        "https://www.nseindia.com/api/fiidiiTradeReact",
        "Daily net FII and DII buying/selling in the cash segment.",
        Status.FRAGILE, "daily", "1 day", "NSE terms of use",
        series=("FII_NET_CASH", "DII_NET_CASH"),
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "sebi_fpi", "SEBI FPI Investment Data", Domain.FLOWS,
        "https://www.sebi.gov.in/statistics/1392982252002.html",
        "Foreign portfolio investor flows by asset class and month.",
        Status.PLANNED, "monthly", "5 days", "SEBI - public",
        series=("FPI_NET_EQUITY", "FPI_NET_DEBT"),
    ),
    SourceSpec(
        "amfi_sip", "AMFI SIP & Industry Flows", Domain.FUNDS,
        "https://www.amfiindia.com/research-information/amfi-monthly",
        "Monthly SIP contributions, net inflows by scheme category, industry AUM.",
        Status.PLANNED, "monthly", "~8 days", "AMFI - public",
        series=("SIP_INFLOW", "EQUITY_FUND_NET_FLOW", "INDUSTRY_AUM"),
        notes="The structural domestic bid. Monthly SIP flow is arguably the most "
              "important single number for Indian equities over a 1-3 year horizon.",
    ),
    SourceSpec(
        "amfi_nav", "AMFI Daily NAV (all schemes)", Domain.FUNDS,
        "https://portal.amfiindia.com/spages/NAVAll.txt",
        "Daily NAV for every mutual fund scheme in India, as a plain text file.",
        Status.WORKING, "daily", "same day ~23:00 IST", "AMFI - public",
        series=("MF_NAV",),
        notes="No key, no rate limit, genuinely open. ~10k schemes per file.",
        last_verified="2026-09-18",
    ),

    # -------------------------------------------------------- MACRO / RBI ----
    SourceSpec(
        "rbi_current_rates", "RBI Current Rates (homepage block)", Domain.MACRO,
        "https://www.rbi.org.in/",
        "Policy repo, SDF, MSF, bank rate, reverse repo, CRR, SLR and RBI "
        "reference FX rates -- the whole current-rates block in one fetch.",
        Status.WORKING, "on change", "immediate", "RBI - public",
        series=("REPO_RATE", "SDF_RATE", "MSF_RATE", "BANK_RATE",
                "REVERSE_REPO_RATE", "CRR", "SLR", "USDINR", "GBPINR",
                "EURINR", "JPYINR_100"),
        last_verified="2026-09-18",
        notes="Highest value per unit of parsing effort of anything RBI publishes. "
              "Current levels only, not a history -- for the path of policy you need "
              "the MPC statement archive. Requires a browser User-Agent.",
    ),
    SourceSpec(
        "rbi_dbie", "RBI Database on Indian Economy", Domain.MACRO,
        "https://data.rbi.org.in/",
        "The canonical source for Indian monetary, banking, external and fiscal data.",
        Status.PLANNED, "varies", "varies", "RBI - public",
        series=("REPO_RATE", "CRR", "SLR", "M3_YOY", "BANK_CREDIT_YOY",
                "FX_RESERVES", "CAD_PCT_GDP", "GSEC_10Y"),
        notes="Deepest single macro source for India, but data.rbi.org.in is an "
              "Angular single-page app with no documented data API (confirmed "
              "2026-09-18) -- the bundle would have to be reverse-engineered. "
              "Use rbi_current_rates for policy rates today.",
    ),
    SourceSpec(
        "rbi_policy", "RBI Policy Statements & MPC Minutes", Domain.POLICY,
        "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
        "Monetary policy decisions, statements, and MPC member voting records.",
        Status.PLANNED, "bi-monthly", "same day", "RBI - public",
        notes="Text, not numbers. Feeds the policy persona directly; MPC vote splits "
              "are a genuinely predictive and under-used signal.",
    ),
    SourceSpec(
        "mospi_cpi", "MOSPI Consumer Price Index", Domain.MACRO,
        "https://mospi.gov.in/web/mospi/download-tables-data",
        "CPI headline, core, rural/urban split, and component-level indices.",
        Status.PLANNED, "monthly", "~12 days", "MOSPI - public / open",
        series=("CPI_COMBINED_YOY", "CPI_CORE_YOY", "CPI_FOOD_YOY"),
        notes="Released ~12th of the following month -- the lag is the whole reason the "
              "store is bitemporal. mospi.gov.in is a JS shell and api.mospi.gov.in "
              "serves an UNCONFIGURED stock Swagger UI still pointing at "
              "petstore.swagger.io (checked 2026-09-18), so there is no MOSPI API. "
              "Route via data.gov.in, or parse the monthly press-release PDFs.",
    ),
    SourceSpec(
        "mospi_iip", "MOSPI Index of Industrial Production", Domain.MACRO,
        "https://mospi.gov.in/iip", "IIP headline and sectoral, use-based classification.",
        Status.PLANNED, "monthly", "~42 days", "MOSPI - public / open",
        series=("IIP_YOY", "IIP_MANUFACTURING", "IIP_CAPITAL_GOODS"),
        notes="Six-week lag and heavily revised. Nowcast it from power demand and "
              "e-way bills rather than waiting for the print.",
    ),
    SourceSpec(
        "mospi_gdp", "MOSPI National Accounts (GDP)", Domain.MACRO,
        "https://mospi.gov.in/national-accounts",
        "Quarterly and annual GDP, GVA by sector, at constant and current prices.",
        Status.PLANNED, "quarterly", "~60 days", "MOSPI - public / open",
        series=("GDP_YOY", "GVA_YOY"),
        notes="Revised for years afterwards. Backtests MUST use the first print.",
    ),
    SourceSpec(
        "data_gov_in", "data.gov.in Open Government Data", Domain.MACRO,
        "https://api.data.gov.in/resource/",
        "Thousands of government datasets behind one free API key.",
        Status.WORKING, "varies", "varies", "Government Open Data Licence - India",
        needs_key=True, last_verified="2026-09-18",
        series=("CPI_ARCHIVE", "IIP_ARCHIVE", "POWER_SUPPLY_POSITION"),
        notes="Genuinely open licence -- the cleanest redistribution rights of anything "
              "here, and ~288,000 resources. Two caveats: the API's own `q` search "
              "parameter is silently ignored, so search_catalogue() pages and indexes "
              "locally; and most CPI/IIP resources are ARCHIVAL (ending 2014-2017) "
              "rather than the current monthly series.",
    ),

    # ------------------------------------------------ FIXED INCOME / FX ----
    SourceSpec(
        "ccil_gsec", "CCIL G-Sec & Money Market", Domain.FIXED_INCOME,
        "https://www.ccilindia.com/",
        "Government bond trading, yields, the NDS-OM curve, CBLO/TREPS rates.",
        Status.PLANNED, "daily", "same day", "CCIL terms",
        series=("GSEC_10Y", "GSEC_CURVE", "TREPS_RATE"),
    ),
    SourceSpec(
        "fbil_rates", "FBIL Benchmark Rates", Domain.FX,
        "https://www.fbil.org.in/",
        "Official INR reference rate, MIBOR, T-bill and G-sec valuation curves.",
        Status.PLANNED, "daily", "same day", "FBIL terms",
        series=("USDINR_REF", "MIBOR_ON", "TBILL_91D"),
        notes="The authoritative INR fixing -- use this rather than a broker quote "
              "for anything that needs to be defensible.",
    ),
    SourceSpec(
        "rbi_fx_reference", "RBI Reference Rate", Domain.FX,
        "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx",
        "Daily RBI reference rates for USD, EUR, GBP and JPY against INR.",
        Status.PLANNED, "daily", "same day", "RBI - public",
        series=("USDINR", "EURINR", "GBPINR", "JPYINR"),
    ),

    # -------------------------------------------------- ALTERNATIVE DATA ----
    SourceSpec(
        "grid_india_power", "Grid-India (POSOCO) Power Demand", Domain.ALT,
        "https://report.grid-india.in/",
        "Daily and block-wise all-India electricity generation and demand.",
        Status.BLOCKED, "daily", "1 day", "Grid-India - public",
        series=("POWER_DEMAND_MU", "PEAK_DEMAND_MW"), last_verified="2026-09-18",
        notes="BLOCKED: report.grid-india.in no longer resolves (NXDOMAIN, checked "
              "2026-09-18) and posoco.in returns 502. Still the best high-frequency "
              "proxy for real activity in India -- daily, barely revised, six weeks "
              "ahead of the IIP print it anticipates -- so power.grid_india_available() "
              "probes live and the module starts working again if the host returns. "
              "npp.gov.in is reachable as an alternative route.",
    ),
    SourceSpec(
        "npci_upi", "NPCI UPI Statistics", Domain.ALT,
        "https://www.npci.org.in/what-we-do/upi/product-statistics",
        "Monthly UPI transaction volume and value; per-bank and per-app breakdowns.",
        Status.PLANNED, "monthly", "~5 days", "NPCI - public",
        series=("UPI_VOLUME", "UPI_VALUE"),
        notes="Proxy for consumption and formalisation. Structurally trending, so "
              "use the deviation from trend, never the level.",
    ),
    SourceSpec(
        "gst_eway", "GST Collections & E-Way Bills", Domain.ALT,
        "https://www.gst.gov.in/",
        "Monthly GST revenue and e-way bill generation counts.",
        Status.PLANNED, "monthly", "1 day", "GSTN - public",
        series=("GST_COLLECTIONS", "EWAY_BILLS"),
        notes="GST collections print on the 1st for the prior month -- among the "
              "fastest real-activity reads available anywhere in India.",
    ),
    SourceSpec(
        "vahan_registrations", "VAHAN Vehicle Registrations", Domain.ALT,
        "https://vahan.parivahan.gov.in/vahan4dashboard/",
        "Daily vehicle registrations by category, state and manufacturer.",
        Status.PLANNED, "daily", "1 day", "MoRTH - public",
        series=("AUTO_REGISTRATIONS", "TWO_WHEELER_REG", "TRACTOR_REG"),
        notes="Two-wheeler and tractor registrations are the standard rural demand "
              "proxy and lead reported auto-sector earnings.",
    ),
    SourceSpec(
        "imd_rainfall", "IMD Rainfall & Monsoon", Domain.ALT,
        "https://mausam.imd.gov.in/",
        "District and subdivision rainfall, monsoon progress, departure from normal.",
        Status.PLANNED, "daily", "1 day", "IMD - public",
        series=("MONSOON_DEPARTURE_PCT", "RESERVOIR_LEVEL"),
        notes="Monsoon -> kharif output -> food inflation -> RBI policy -> rates -> "
              "equity multiples. One of the longest genuinely causal chains in this "
              "market, and it starts with weather.",
    ),

    # ------------------------------------------------------------ GLOBAL ----
    SourceSpec(
        "fred", "FRED (St. Louis Fed)", Domain.GLOBAL,
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        "US rates, dollar index, global macro. CSV endpoint needs no key.",
        Status.WORKING, "daily", "1 day", "free; see FRED terms",
        series=("US10Y", "DXY", "FED_FUNDS", "US_CPI"),
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "world_bank", "World Bank Open Data API", Domain.GLOBAL,
        "https://api.worldbank.org/v2/country/IND/indicator/",
        "Long-run annual macro series for India and comparators.",
        Status.WORKING, "annual", "months", "CC-BY 4.0",
        series=("GDP_PC", "INFLATION_ANNUAL", "TRADE_PCT_GDP"),
        notes="Genuinely open licence. Annual only -- context, not signal.",
        last_verified="2026-09-18",
    ),
    SourceSpec(
        "eia_oil", "US EIA Petroleum Prices", Domain.COMMODITY,
        "https://api.eia.gov/v2/petroleum/",
        "Brent and WTI spot prices, global supply and inventory.",
        Status.PLANNED, "daily", "1 day", "US Gov - public domain", needs_key=True,
        series=("BRENT", "WTI"),
        notes="India imports over 85% of its crude. Brent in INR is the single "
              "highest-leverage external variable for this economy.",
    ),

    # --------------------------------------------------------- SENTIMENT ----
    SourceSpec(
        "gdelt", "GDELT Global Knowledge Graph", Domain.SENTIMENT,
        "https://api.gdeltproject.org/api/v2/doc/doc",
        "World news volume and tone, filterable to India and to topics.",
        Status.FRAGILE, "15 min", "15 min", "GDELT - open",
        series=("NEWS_TONE_INDIA", "NEWS_VOLUME_INDIA"),
        notes="Tone is noisy and its baseline drifts. Use the z-score against a "
              "trailing window, never the raw level.",
    ),
    SourceSpec(
        "rbi_sebi_circulars", "SEBI & RBI Circulars", Domain.POLICY,
        "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7",
        "Regulatory circulars, consultation papers and enforcement orders.",
        Status.PLANNED, "daily", "same day", "SEBI - public",
        notes="Unstructured text, high impact. A margin or position-limit change can "
              "reprice an entire market segment overnight -- this is exactly the kind "
              "of discrete regime shift a purely statistical model cannot anticipate.",
    ),

    # --------------------------------------------------------- CORPORATE ----
    SourceSpec(
        "nse_corp_actions", "NSE Corporate Actions", Domain.CORPORATE,
        "https://www.nseindia.com/api/corporates-corporateActions",
        "Splits, bonuses, dividends, rights, mergers with ex-dates.",
        Status.PLANNED, "daily", "1 day", "NSE terms of use",
        notes="Mandatory for correct returns. Without it every split is a fake crash.",
    ),
    SourceSpec(
        "nse_announcements", "NSE Corporate Announcements", Domain.CORPORATE,
        "https://www.nseindia.com/api/corporate-announcements",
        "Company filings, results, board meetings, insider trades.",
        Status.PLANNED, "realtime", "minutes", "NSE terms of use",
    ),
    SourceSpec(
        "nse_shareholding", "Shareholding Patterns", Domain.CORPORATE,
        "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
        "Quarterly promoter, FII, DII and public shareholding, plus pledged shares.",
        Status.PLANNED, "quarterly", "~21 days", "NSE terms of use",
        series=("PROMOTER_HOLDING", "PROMOTER_PLEDGE_PCT"),
        notes="Rising promoter pledging has preceded a large share of Indian mid-cap "
              "blowups. A high-value, under-watched risk signal.",
    ),
)

BY_KEY: dict[str, SourceSpec] = {s.key: s for s in CATALOGUE}


def by_domain(domain: Domain | str) -> list[SourceSpec]:
    d = Domain(domain) if isinstance(domain, str) else domain
    return [s for s in CATALOGUE if s.domain is d]


def by_status(status: Status | str) -> list[SourceSpec]:
    st = Status(status) if isinstance(status, str) else status
    return [s for s in CATALOGUE if s.status is st]


def all_series() -> dict[str, str]:
    """series_id -> source key, for every series the catalogue claims to provide."""
    out: dict[str, str] = {}
    for s in CATALOGUE:
        for ser in s.series:
            out.setdefault(ser, s.key)
    return out


def coverage_summary() -> dict[str, int]:
    return {
        "sources_total": len(CATALOGUE),
        "working": len(by_status(Status.WORKING)),
        "blocked": len(by_status(Status.BLOCKED)),
        "fragile": len(by_status(Status.FRAGILE)),
        "planned": len(by_status(Status.PLANNED)),
        "verified": sum(1 for s in CATALOGUE if s.last_verified),
        "domains": len({s.domain for s in CATALOGUE}),
        "series_declared": len(all_series()),
        "need_api_key": sum(1 for s in CATALOGUE if s.needs_key),
    }
