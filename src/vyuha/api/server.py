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
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from vyuha import __version__
from vyuha.config import settings

app = FastAPI(title="Vyuha", version=__version__, docs_url="/api/docs")

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
    r"nav|mutual fund)\b", re.I,
)
_RISK_PAT = re.compile(r"\b(var\b|value at risk|stress|scenario|drawdown|volatility|"
                       r"tail risk|expected shortfall)\b", re.I)
_FORECAST_PAT = re.compile(r"\b(will|would|probability|odds|chance|likely|forecast|"
                           r"expect|predict|by (?:next|the end)|before)\b", re.I)


def classify(text: str) -> str:
    if _RISK_PAT.search(text):
        return "risk"
    if _FORECAST_PAT.search(text):
        return "council"
    if _DATA_PAT.search(text):
        return "data"
    return "council"


# ------------------------------------------------------------------- evidence


def build_evidence(as_of: dt.datetime | None = None):
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

    if not packet.items:
        packet.caveats.append(
            "No live evidence could be fetched. Members must answer from base "
            "rates and say so explicitly."
        )
    return packet


# ---------------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict:
    from vyuha.council.providers import OllamaProvider

    models = OllamaProvider().available_models()
    return {
        "status": "ok", "version": __version__,
        "models": models,
        "distinct_model_families": len({m.split(":")[0] for m in models}),
        "ollama": bool(models),
    }


@app.get("/api/evidence")
def evidence() -> dict:
    p = build_evidence()
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
async def ask(req: AskRequest) -> JSONResponse:
    """Non-streaming ask. Use /api/ask/stream for progress."""
    result = await asyncio.to_thread(_run_ask, req)
    return JSONResponse(result)


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
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
            except asyncio.TimeoutError:
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
    kind = classify(req.question)
    if emit:
        emit("status", {"stage": "classified", "route": kind})

    if kind == "data":
        return _answer_data(req.question, emit)
    if kind == "risk":
        return _answer_risk(req.question, emit)
    return _answer_council(req, emit)


def _answer_data(question: str, emit=None) -> dict:
    if emit:
        emit("status", {"stage": "fetching live data"})
    p = build_evidence()
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
    from vyuha.council.schema import question_id_for

    if emit:
        emit("status", {"stage": "assembling point-in-time evidence"})
    packet = build_evidence()

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
        provider=default_provider(),
        personas=req.members,
        config=CouncilConfig(rounds=req.rounds),
    )
    if emit:
        emit("status", {"stage": "convening council",
                        "members": [p.name for p in council.personas],
                        "models": council._model_for})

    verdict = council.run(q, packet)

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
        "evidence_caveats": packet.caveats,
        "independence_warning": (
            None if len(families) > 1 else
            f"All {verdict.n_members} members are running on the same base model "
            f"({', '.join(families)}). Their errors are correlated and the "
            f"dispersion below understates true uncertainty. Pull more model "
            f"families to fix this."
        ),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    from vyuha.api.ui import PAGE

    return PAGE
