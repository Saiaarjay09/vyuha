"""Vyuha web interface.

A text-first console: you ask a question the way you would ask a chatbot, and
a bias-diverse council answers with a calibrated probability, the evidence it
used, and -- importantly -- the disagreement between its members.

Deliberately not a chatbot. The council does not do small talk, and a question
it cannot resolve objectively gets pushed back on rather than answered
plausibly. Three request types are routed:

    council   a forecastable question -> probability + dispersion + dissent
    data      "what is the repo rate" -> a direct lookup, no LLM involved
    risk      "stress test" / "var on nifty" -> the risk engine

The routing is intentionally simple and inspectable. A misrouted question is
better than a confidently hallucinated answer, so anything unrecognised is
routed to the council with its resolution criteria left explicit.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from vyuha import __version__
from vyuha.config import settings

app = FastAPI(title="Vyuha", version=__version__, docs_url="/api/docs")

#: Paths that cost real compute and are therefore gated. Everything else --
#: the page, /status, /api/health -- stays open so a shared link still loads
#: and remains diagnosable without the key.
PROTECTED_PREFIXES: tuple[str, ...] = ("/api/ask", "/api/evidence")


@app.middleware("http")
async def _access_middleware(request: Request, call_next):
    """Check the key BEFORE FastAPI validates the request body.

    Doing this with a route dependency instead looks equivalent and is not:
    FastAPI validates the body first, so a malformed request returns 422
    whether or not a key was supplied. That lets anyone map the request schema
    by trial and error without ever holding the key. Running as middleware
    means unauthorised requests are refused before anything else is examined.
    """
    path = request.url.path
    if any(p in path for p in PROTECTED_PREFIXES):
        try:
            check_access(request, request.headers.get("x-vyuha-key"))
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)

# ----------------------------------------------------------------- access

_REQUESTS: dict[str, list[float]] = {}


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "?"))


def check_access(request: Request, token: str | None) -> None:
    """Gate the routes that cost real compute.

    The page itself, /status and /api/health stay open, so a shared link still
    loads and remains diagnosable. Only inference is gated -- that is the part
    someone else can run up a bill on.

    The token may arrive as an X-Vyuha-Key header or a ?key= query parameter.
    The query form exists so a single shareable URL works; it is the weaker
    option, since URLs end up in browser history and server logs.
    """
    expected = settings.access_token
    if not expected:
        return  # open by default: correct for localhost, not for a public URL

    supplied = token or request.query_params.get("key", "")
    # Constant-time comparison: a plain == leaks the token one byte at a time
    # to anyone patient enough to measure the difference.
    import hmac

    if not supplied or not hmac.compare_digest(str(supplied), str(expected)):
        raise HTTPException(
            status_code=401,
            detail="This instance requires an access key. Append ?key=... to the "
                   "URL, or send an X-Vyuha-Key header.",
        )

    now = time.time()
    key = _client_key(request)
    window = [t for t in _REQUESTS.get(key, []) if now - t < 3600]
    if len(window) >= settings.rate_limit_per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached ({settings.rate_limit_per_hour}/hour). "
                   "Each question runs a language model on a personal machine.",
        )
    window.append(now)
    _REQUESTS[key] = window


# Cheap in-process cache so a page reload does not re-scrape NSE and RBI.
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300.0


def _cached(key: str, fn, ttl: float = _CACHE_TTL):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    members: list[str] | None = None
    rounds: int = Field(2, ge=1, le=4)
    horizon_days: int = Field(30, ge=1, le=365)


# --------------------------------------------------------------------- routing

_DATA_PAT = re.compile(
    r"\b(repo rate|crr\b|slr\b|bank rate|reverse repo|usdinr|usd/inr|rupee|"
    r"vix|nifty|sensex|bank nifty|fii|dii|put.?call|pcr|option chain|"
    r"nav|mutual fund|gold|silver|brent|crude|wti|copper|wheat|"
    r"s&p|sp500|nasdaq|dow|vix|dollar|treasury|fed funds)\b", re.I,
)
_RISK_PAT = re.compile(r"\b(var\b|value at risk|stress|scenario|drawdown|volatility|"
                       r"tail risk|expected shortfall)\b", re.I)
# Asking about something we hold no data on must produce an admission, not an
# improvisation. A language model will happily answer a housing question from
# training-data memory; that is exactly the failure this system exists to avoid.
_ASSET_HINTS: dict[str, tuple[str, ...]] = {
    "real_estate": ("hous", "property", "real estate", "realty", "flat", "apartment",
                    "rent", "mortgage", "home loan", "residex", "land price"),
    "commodity": ("gold", "silver", "crude", "oil price", "commodity", "commodities",
                  "copper", "aluminium", "aluminum", "wheat", "brent", "wti",
                  "natural gas", "bullion"),
    "bond": ("bond", "g-sec", "gsec", "gilt", "debenture", "yield curve",
             "fixed income", "debt fund"),
    "etf": ("etf", "exchange traded", "index fund", "niftybees", "goldbees"),
    "mutual_fund": ("mutual fund", "sip", "nav", "amc "),
    "equity": ("share", "stock", "nifty", "sensex", "equity", "midcap", "smallcap"),
}


# Substring matching is not safe here. "Will Brent go above 140?" matched the
# real-estate hint "rent" and was refused as an unanswerable housing question.
# Hints are matched on word boundaries instead, with a trailing wildcard so
# "hous" still catches housing, house and houses.
_HINT_RE: dict[str, re.Pattern[str]] = {
    ac: re.compile(
        r"(?<![a-z])(" + "|".join(re.escape(h.strip()) for h in hints) + r")[a-z]*",
        re.I,
    )
    for ac, hints in _ASSET_HINTS.items()
}


def detect_asset_class(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for ac, pat in _HINT_RE.items():
        score = len(pat.findall(text))
        if score and (best is None or score > best[0]):
            best = (score, ac)
    return best[1] if best else None


def coverage_gap(text: str) -> dict | None:
    """Return a refusal payload if the question is about an asset class we
    have no working data source for."""
    from vyuha.ingest.catalogue import asset_class_coverage

    ac = detect_asset_class(text)
    if ac is None:
        return None
    cov = asset_class_coverage().get(ac)
    if cov and cov["can_answer"]:
        return None
    from vyuha.ingest.catalogue import by_asset_class

    planned = [s for s in by_asset_class(ac)]
    return {
        "route": "no_data",
        "asset_class": ac,
        "message": (
            f"I don't have a working data source for {ac.replace('_', ' ')} yet, "
            f"so I can't answer this honestly. I'd rather say that than guess."
        ),
        "catalogued": [{"name": s.name, "url": s.url, "status": s.status.value,
                        "note": s.notes} for s in planned],
    }


# --- projection ("what will X become?") --------------------------------------
_PROJECT_PAT = re.compile(
    r"\b(invest|investing|investment|sip|lump\s?sum|lumpsum|put in|"
    r"grow to|worth in|returns? on|corpus|maturity)\b", re.I,
)
_AMOUNT_PAT = re.compile(
    r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|k|thousand)?",
    re.I,
)
_YEARS_PAT = re.compile(r"([\d.]+)\s*(year|yr|y|month|mo)s?\b", re.I)

_ASSET_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("indian_equity", ("nifty", "sensex", "indian equity", "indian stock", "equity",
                       "shares", "stock market", "index fund", "mutual fund", "elss")),
    ("gold", ("gold", "sovereign gold", "gold etf", "bullion")),
    ("silver", ("silver",)),
    ("us_equity", ("us stock", "us equity", "s&p", "nasdaq", "american stock")),
    ("fixed_deposit", ("fixed deposit", "fd", "term deposit", "recurring deposit")),
    ("debt_fund", ("debt fund", "bond fund", "debt mutual", "liquid fund")),
]

_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
         "crore": 1e7, "crores": 1e7, "cr": 1e7,
         "k": 1e3, "thousand": 1e3}


def parse_projection(text: str) -> dict | None:
    """Pull amount, horizon, asset and mode out of a plain-English question.

    Returns None when there is no amount or no horizon -- projecting without
    both would mean inventing one, and an invented horizon changes the answer
    more than almost anything else.
    """
    low = text.lower()

    ym = _YEARS_PAT.search(low)
    if not ym:
        return None
    n = float(ym.group(1))
    years = n / 12 if ym.group(2).lower().startswith("mo") else n
    if not 0 < years <= 50:
        return None

    amount = None
    for m in _AMOUNT_PAT.finditer(low):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        # Skip the number that formed the horizon.
        if m.start() == ym.start() or raw == ym.group(1) and not unit:
            continue
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        val *= _MULT.get(unit, 1.0)
        if val >= 500:
            amount = val
            break
    if amount is None:
        return None

    asset = "indian_equity"
    for key, words in _ASSET_WORDS:
        if any(w in low for w in words):
            asset = key
            break

    mode = "sip" if re.search(r"\b(sip|monthly|every month|per month)\b", low) else "lumpsum"
    return {"amount": amount, "years": years, "asset": asset, "mode": mode}


_FORECAST_PAT = re.compile(r"\b(will|would|probability|odds|chance|likely|forecast|"
                           r"expect|predict|by (?:next|the end)|before)\b", re.I)


def classify(text: str) -> str:
    # An amount plus a horizon plus a named asset is already an unambiguous
    # projection request ("50,000 in a fixed deposit for 10 years"), with or
    # without a verb like "invest". But "will the Nifty fall below 22,900 in
    # 30 days" also carries a number and a horizon, so a forecast phrasing
    # still wins -- that is a question about an event, not about a balance.
    proj = parse_projection(text)
    if proj and not _FORECAST_PAT.search(text):
        return "projection"
    if proj and _PROJECT_PAT.search(text):
        return "projection"
    if _RISK_PAT.search(text):
        return "risk"
    if _FORECAST_PAT.search(text):
        return "council"
    if _DATA_PAT.search(text):
        return "data"
    return "council"


# ------------------------------------------------------------------- evidence


_GLOBAL_HINTS = (
    # commodities
    "gold", "silver", "crude", "brent", "wti", "oil", "copper", "aluminium",
    "aluminum", "wheat", "commodity", "commodities", "natural gas", "bullion",
    # US markets and policy
    "s&p", "sp500", "s&p500", "nasdaq", "dow", "nyse", "wall street",
    "us stock", "us equit", "us market", "us share", "america", "american",
    "usa", "fed ", "federal reserve", "treasury", "dollar",
    # general international framing
    "global", "world", "international", "abroad", "overseas", "foreign",
    "outside india", "other countries", "developed market", "emerging market",
    # major economies an Indian investor might ask about
    "europe", "european", "euro ", "eurozone", "japan", "japanese", "china",
    "chinese", "uk ", "u.k.", "britain", "british", "germany", "german",
    "singapore", "dubai", "uae", "brazil", "russia", "korea", "taiwan",
)


def wants_global(text: str) -> bool:
    low = f" {text.lower()} "
    return any(h in low for h in _GLOBAL_HINTS)


def build_global_evidence(packet) -> None:
    """Add commodities, world indices and FX, plus their rupee equivalents.

    The rupee conversions are the point. A question about gold asked from India
    is really a question about gold *in rupees*, and the two can diverge sharply
    -- the dollar price and the rupee price of the same ounce have moved in
    opposite directions for months at a time.
    """
    from vyuha.ingest.globalmarkets import commodity_snapshot, fx_spot, global_snapshot

    usdinr = None
    try:
        rates = _cached("fx_spot", lambda: fx_spot("USD"), ttl=3600)
        usdinr = float(rates.get("INR")) if rates.get("INR") else None
        if usdinr:
            packet.add("USDINR_SPOT", round(usdinr, 3), source="open.er-api",
                       event_date=dt.date.today())
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"FX spot unavailable: {exc}")

    try:
        existing = {i.label for i in packet.items}
        for _, r in _cached("commodities", commodity_snapshot).iterrows():
            if r["error"] or r["value"] is None:
                continue
            name = str(r["commodity"]).upper()
            # BRENT already arrives in the India block via FRED; adding it again
            # under a second label would let a member cite the same fact twice
            # as if it were two pieces of corroborating evidence.
            if name in existing:
                continue
            packet.add(f"{name}_USD", float(r["value"]),
                       unit=str(r["unit"]), event_date=r["date"], source=str(r["source"]))
            # Gold and crude are what an Indian reader actually prices in rupees.
            if usdinr and str(r["commodity"]) in ("gold", "silver", "brent"):
                packet.add(f"{name}_INR",
                           round(float(r["value"]) * usdinr, 1),
                           unit=f"INR per {str(r['unit']).split('/')[-1]}",
                           event_date=r["date"], source="vyuha (converted)")
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"commodities unavailable: {exc}")

    try:
        for _, r in _cached("global_idx", global_snapshot).iterrows():
            if r["error"] or r["value"] is None:
                continue
            packet.add(str(r["series"]).upper(), float(r["value"]),
                       unit=str(r["unit"]), event_date=r["date"], source="FRED")
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"global indices unavailable: {exc}")


def add_retrieved_context(packet, question: str) -> None:
    """Attach a handful of filtered, sanitised headlines to the packet.

    Failure here is never fatal: the numeric evidence is what the council
    mainly reasons from, and losing the headlines costs less than losing the
    answer.
    """
    from vyuha.knowledge.filter import filter_documents
    from vyuha.knowledge.retrieve import retrieve

    try:
        docs = _cached(
            "retrieval",
            lambda: retrieve(max_age_hours=settings.retrieval_max_age_hours),
            ttl=900,
        )
        verdict = filter_documents(docs, question, keep=settings.retrieval_keep)
        for d in verdict.kept:
            packet.add_context(
                title=d.title, source=d.source, tier=d.tier.value,
                age_hours=d.age_hours, url=d.url, flags=d.flags,
            )
        if verdict.injection_attempts:
            packet.caveats.append(
                f"{len(verdict.injection_attempts)} retrieved item(s) contained "
                "instruction-shaped text, which was stripped. Treat all "
                "headlines with corresponding suspicion."
            )
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"headline retrieval unavailable: {str(exc)[:90]}")


def build_evidence(as_of: dt.datetime | None = None, include_global: bool = False,
                   question: str | None = None):
    """Assemble a live evidence packet from the sources verified working."""
    from vyuha.council import EvidencePacket
    from vyuha.ingest.base import NSESession
    from vyuha.ingest.rbi import rbi_current_rates
    from vyuha.ingest.sources import nse_all_indices, nse_fii_dii, nse_option_chain, put_call_ratio

    packet = EvidencePacket(as_of=as_of or dt.datetime.now())
    today = dt.date.today()

    try:
        for _, r in _cached("rbi", rbi_current_rates).iterrows():
            packet.add(str(r["series_id"]), float(r["value"]), unit=str(r["unit"]),
                       event_date=today, source="RBI")
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"RBI rates unavailable: {exc}")

    try:
        def _nse():
            with NSESession() as s:
                idx = nse_all_indices(s)
                flows = nse_fii_dii(s)
                chain = nse_option_chain("NIFTY", s)
                return idx, flows, chain

        idx, flows, chain = _cached("nse", _nse)

        for name in ("NIFTY 50", "NIFTY BANK", "INDIA VIX", "NIFTY MIDCAP 100"):
            row = idx[idx["index"].str.upper() == name]
            if len(row):
                packet.add(name.replace(" ", "_"), float(row["last"].iloc[0]),
                           event_date=today, source="NSE")
        for r in flows.to_dict("records"):
            packet.add(f"{r['category'].replace('/', '_')}_NET_CASH",
                       float(r["netValue"]), unit="INR cr", event_date=today, source="NSE")
        packet.add("NIFTY_PUT_CALL_RATIO", round(put_call_ratio(chain), 3),
                   event_date=today, source="NSE")
        live = chain[chain["iv"] > 0]
        if len(live) and chain.attrs.get("underlying"):
            spot = float(chain.attrs["underlying"])
            near = live.iloc[(live["strike"] - spot).abs().argsort()[:6]]
            packet.add("NIFTY_ATM_IV", round(float(near["iv"].mean()), 2),
                       unit="pct", event_date=today, source="NSE")
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"NSE data unavailable: {exc}")

    try:
        from vyuha.ingest.sources import fred_series

        for sid, label in (("DGS10", "US10Y"), ("DCOILBRENTEU", "BRENT")):
            s = _cached(f"fred_{sid}", lambda sid=sid: fred_series(sid), ttl=3600)
            packet.add(label, float(s["value"].iloc[-1]),
                       event_date=s["date"].iloc[-1].date(), source="FRED")
    except Exception as exc:  # noqa: BLE001
        packet.caveats.append(f"FRED unavailable: {exc}")

    if include_global:
        build_global_evidence(packet)

    if question and settings.retrieval_enabled:
        add_retrieved_context(packet, question)

    if not packet.items:
        packet.caveats.append(
            "No live evidence could be fetched. Members must answer from base "
            "rates and say so explicitly."
        )
    return packet


# ---------------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict:
    from vyuha.council.providers import EchoProvider, default_provider

    provider = default_provider()
    try:
        models = provider.available_models()
    except Exception:  # noqa: BLE001
        models = []
    usable = not isinstance(provider, EchoProvider)
    return {
        "status": "ok", "version": __version__,
        "provider": provider.name,
        "models": models[:12],
        "distinct_model_families": len({m.split(":")[0].split("/")[-1] for m in models}),
        "council_available": usable,
        "requires_key": bool(settings.access_token),
        # Data and risk answers never need a model, so the app is useful even
        # when inference is unavailable.
        "data_routes_available": True,
    }


@app.get("/api/evidence")
def evidence(request: Request, scope: str = "india",
             x_vyuha_key: str | None = Header(None)) -> dict:
    p = build_evidence(include_global=scope in ("global", "all"))
    return {
        "as_of": p.as_of.isoformat(),
        "fingerprint": p.fingerprint(),
        "items": [
            {"id": i.id, "label": i.label, "value": i.value, "unit": i.unit,
             "source": i.source, "event_date": str(i.event_date)}
            for i in p.items
        ],
        "caveats": p.caveats,
    }


@app.get("/api/personas")
def personas() -> list[dict]:
    from vyuha.council.personas import PERSONAS

    return [
        {"name": p.name, "title": p.title, "bias": p.bias,
         "models": list(p.preferred_models), "tags": list(p.tags)}
        for p in PERSONAS
    ]


@app.get("/api/coverage")
def coverage() -> dict:
    """Which asset classes can actually be answered, and which cannot."""
    from vyuha.ingest.catalogue import asset_class_coverage

    return asset_class_coverage()


@app.get("/api/sources")
def sources() -> dict:
    from vyuha.ingest.catalogue import CATALOGUE, coverage_summary

    return {
        "summary": coverage_summary(),
        "sources": [
            {"key": s.key, "name": s.name, "domain": s.domain.value,
             "status": s.status.value, "verified": s.last_verified,
             "series": list(s.series), "notes": s.notes}
            for s in CATALOGUE
        ],
    }


@app.post("/api/ask")
async def ask(req: AskRequest, request: Request,
              x_vyuha_key: str | None = Header(None)) -> JSONResponse:
    """Non-streaming ask. Use /api/ask/stream for progress."""
    result = await asyncio.to_thread(_run_ask, req)
    return JSONResponse(result)


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest, request: Request,
                     x_vyuha_key: str | None = Header(None)) -> StreamingResponse:
    """Server-sent events, so the user sees members answering as they finish."""

    async def gen():
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(kind: str, payload: Any) -> None:
            loop.call_soon_threadsafe(q.put_nowait, (kind, payload))

        task = asyncio.create_task(asyncio.to_thread(_run_ask, req, emit))
        while True:
            if task.done() and q.empty():
                break
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=0.4)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
        try:
            result = task.result()
            yield f"event: done\ndata: {json.dumps(result, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _run_ask(req: AskRequest, emit=None) -> dict:
    gap = coverage_gap(req.question)
    if gap is not None:
        if emit:
            emit("status", {"stage": "checking data coverage"})
        return gap

    kind = classify(req.question)
    if emit:
        emit("status", {"stage": "classified", "route": kind})

    if kind == "data":
        return _answer_data(req.question, emit)
    if kind == "projection":
        return _answer_projection(req.question, emit)
    if kind == "risk":
        return _answer_risk(req.question, emit)
    return _answer_council(req, emit)


def _answer_data(question: str, emit=None) -> dict:
    if emit:
        emit("status", {"stage": "fetching live data"})
    p = build_evidence(include_global=wants_global(question))
    words = [w for w in re.split(r"\W+", question.lower()) if len(w) > 2]
    matches = [
        i for i in p.items
        if any(w in i.label.lower().replace("_", " ") for w in words)
    ]
    return {
        "route": "data",
        "answer": None,
        "matches": [
            {"label": i.label, "value": i.value, "unit": i.unit,
             "source": i.source, "event_date": str(i.event_date)}
            for i in (matches or p.items)
        ],
        "exact_match": bool(matches),
        "as_of": p.as_of.isoformat(),
        "caveats": p.caveats,
        "note": "Direct lookup from live sources. No model involved, nothing inferred.",
    }


def _answer_projection(question: str, emit=None) -> dict:
    """Project an investment. Returns a distribution, never a single number."""
    from vyuha.projection import ASSET_SOURCES, FIXED_RATE_ASSETS, compare_assets, project

    spec = parse_projection(question)
    if spec is None:
        return {"route": "projection_unparsed",
                "message": "I need both an amount and a time period, e.g. "
                           "'5 lakh in equity for 7 years'."}
    if emit:
        emit("status", {"stage": "simulating outcomes"})

    r = project(**spec)
    cmp_df = compare_assets(spec["amount"], spec["years"], **{"mode": spec["mode"]})

    return {
        "route": "projection",
        "question": question,
        "asset": r.asset, "asset_label": r.asset_label,
        "amount": r.amount, "years": r.years, "mode": r.mode,
        "total_invested": r.total_invested,
        "percentiles": r.percentiles,
        "real_percentiles": r.real_percentiles,
        "post_tax_percentiles": r.post_tax_percentiles,
        "net_real_percentiles": r.net_real_percentiles,
        "prob_loss": r.prob_loss,
        "prob_below_inflation": r.prob_below_inflation,
        "prob_below_fd": r.prob_below_fd,
        "median_cagr": r.median_cagr,
        "max_drawdown_median": r.max_drawdown_median,
        "n_simulations": r.n_simulations,
        "sample": f"{r.sample_start} to {r.sample_end} ({r.sample_years}y)",
        "inflation_assumed": r.inflation_assumed,
        "tax_note": r.tax_note,
        "caveats": r.caveats,
        "comparison": [
            {k: (None if pd_isna(v) else v) for k, v in row.items()}
            for row in cmp_df.to_dict("records")
        ],
        "available_assets": sorted(set(ASSET_SOURCES) | set(FIXED_RATE_ASSETS)),
    }


def pd_isna(v) -> bool:
    import math

    return isinstance(v, float) and math.isnan(v)


def _answer_risk(question: str, emit=None) -> dict:
    from vyuha.risk.stress import run_all, unmodelled_exposures

    if emit:
        emit("status", {"stage": "running stress scenarios"})

    import pandas as pd

    book = pd.DataFrame(
        {"value": [40e6, 25e6, 15e6, 12e6, 8e6],
         "beta": [0.85, 1.15, 1.45, 1.30, 0.20],
         "cap_segment": ["large", "large", "mid", "small", "large"],
         "duration": [0.0, 0.0, 0.0, 0.0, 6.2]},
        index=["RELIANCE", "HDFCBANK", "MIDCAP_BASKET", "SMALLCAP_BASKET", "GSEC_2033"],
    )
    res = run_all(book)
    return {
        "route": "risk",
        "note": ("Illustrative book -- the API does not yet accept your positions. "
                 "Scenarios are calibrated on India's own crisis record."),
        "unmodelled_exposures": unmodelled_exposures(book),
        "scenarios": [
            {"name": r["name"], "pnl_pct": round(float(r["pnl_pct"]), 4),
             "pnl_inr_cr": round(float(r["pnl"]) / 1e7, 2), "tags": r["tags"]}
            for _, r in res.iterrows()
        ],
    }


def _answer_council(req: AskRequest, emit=None) -> dict:
    from vyuha.council import Council, CouncilConfig, Question, QuestionKind, default_provider
    from vyuha.council.providers import EchoProvider
    from vyuha.council.schema import question_id_for

    provider = default_provider()
    if isinstance(provider, EchoProvider):
        # A stub provider returns a fixed 0.5, which would render as a real
        # forecast. Saying there is no model is the only honest option; the
        # data and risk routes keep working regardless.
        return {
            "route": "no_model",
            "question": req.question,
            "message": (
                "No language model is available, so the council cannot meet. "
                "Live figures and stress tests still work."
            ),
            "how_to_fix": [
                "Locally: install Ollama and run `ollama pull llama3.1:8b`.",
                "Hosted: set VYUHA_LLM_BASE_URL (e.g. 'groq') and "
                "VYUHA_LLM_API_KEY in your deployment's environment.",
            ],
        }

    if emit:
        emit("status", {"stage": "assembling point-in-time evidence"})
    packet = build_evidence(include_global=wants_global(req.question),
                            question=req.question)

    resolves = dt.date.today() + dt.timedelta(days=req.horizon_days)
    q = Question(
        id=question_id_for(req.question, resolves),
        kind=QuestionKind.BINARY,
        text=req.question,
        resolution_criteria=(
            "Resolved from the named source on the resolution date. If this "
            "question is not objectively resolvable as stated, members should "
            "say so and widen their uncertainty."
        ),
        resolution_date=resolves,
        resolution_source="manual",
    )

    council = Council(
        provider=provider,
        personas=req.members,
        config=CouncilConfig(rounds=req.rounds),
    )
    if emit:
        emit("status", {"stage": "convening council",
                        "members": [p.name for p in council.personas],
                        "models": council._model_for})

    done = {"n": 0}
    total = len(council.personas)

    def on_member(fc) -> None:
        done["n"] += 1
        if emit:
            emit("member", {
                "name": fc.member, "probability": fc.probability,
                "ok": fc.parse_ok, "done": done["n"], "total": total,
                "reasoning": fc.reasoning[:400],
            })

    def on_round(rnd: int, v) -> None:
        # Round 0 lands in roughly half the time the full deliberation takes.
        # Showing it, clearly labelled as provisional, beats a spinner: on a
        # ten-member panel of 14B models the difference is ~65s versus ~145s,
        # and the number rarely moves much in the second round anyway.
        if emit:
            emit("preliminary", _verdict_payload(req, q, v, packet, council, resolves))
        done["n"] = 0

    verdict = council.run(q, packet, on_member=on_member, on_round=on_round)
    return _verdict_payload(req, q, verdict, packet, council, resolves)


def _verdict_payload(req, q, verdict, packet, council, resolves) -> dict:
    """Shape a verdict for the client. Used for both the provisional
    round-0 answer and the final one, so they render identically."""
    families = {m.split(":")[0] for m in council._model_for.values()}
    return {
        "route": "council",
        "question": req.question,
        "resolves": str(resolves),
        "probability": verdict.probability,
        "dispersion": verdict.dispersion,
        "n_members": verdict.n_members,
        "summary": verdict.summary_line(),
        "members": [
            {"name": f.member, "model": f.model, "probability": f.probability,
             "confidence": f.confidence, "reasoning": f.reasoning,
             "key_driver": f.key_driver, "citations": [c.id for c in f.citations],
             "ok": f.parse_ok, "error": f.parse_error}
            for f in verdict.member_forecasts
        ],
        "dissent": verdict.dissent,
        "counterargument": verdict.strongest_counterargument,
        "notes": verdict.notes,
        "evidence": [
            {"id": i.id, "label": i.label, "value": i.value, "source": i.source}
            for i in packet.items
        ],
        # Retrieved headlines travel with the verdict. Members cite these as
        # [C01], so omitting them left a reader looking at a citation they
        # could not resolve -- which is worse than not citing at all.
        "context": [
            {"id": c["id"], "title": c["title"], "source": c["source"],
             "tier": c["tier"], "age_hours": c.get("age_hours"),
             "url": c.get("url", ""), "flags": c.get("flags", [])}
            for c in packet.context
        ],
        "evidence_caveats": packet.caveats,
        "independence_warning": (
            None if len(families) > 1 else
            f"All {verdict.n_members} members are running on the same base model "
            f"({', '.join(families)}). Their errors are correlated and the "
            f"dispersion below understates true uncertainty. Pull more model "
            f"families to fix this."
        ),
    }


@app.get("/status", response_class=HTMLResponse)
def status_page() -> str:
    """Plain-HTML reachability check, deliberately NOT under /api/.

    If this renders but the main page reports itself offline, the server is
    healthy and something in the browser is blocking its requests.
    """
    from vyuha.council.providers import EchoProvider, default_provider

    prov = default_provider()
    try:
        models = prov.available_models()
    except Exception:  # noqa: BLE001
        models = []
    return (
        "<!doctype html><meta charset=utf-8>"
        "<title>Vyuha status</title>"
        "<style>body{font-family:system-ui;max-width:40em;margin:3em auto;"
        "padding:0 1em;line-height:1.6}code{background:#eee;padding:2px 5px}</style>"
        "<h1>Vyuha is running</h1>"
        f"<p>Version {__version__}, inference provider <code>{prov.name}</code>, "
        f"{len(models)} model(s) available: <code>{', '.join(models[:6]) or 'none'}</code>.</p>"
        f"<p>Council available: <b>{'yes' if not isinstance(prov, EchoProvider) else 'no'}</b>. "
        "Live figures and stress tests work either way.</p>"
        "<p>If you can read this but the main page says it is offline, the server "
        "is fine and your browser is blocking its requests &mdash; usually an ad "
        "or privacy blocker. Pause it for this site and reload.</p>"
        "<p><a href=\"../vyuha\">Back to Vyuha</a></p>"
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    from vyuha.api.ui import PAGE

    return PAGE
