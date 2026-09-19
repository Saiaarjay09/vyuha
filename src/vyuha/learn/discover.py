"""Finding candidate variables that might matter, without fooling ourselves.

Two channels, and the difference between them is important.

**Registry diffing (reliable).** Official statistical agencies publish machine-
readable catalogues. Snapshot them, diff daily, and anything new is a genuinely
new dataset -- a fact, not a guess. data.gov.in carries ~288,000 resources and
the World Bank ~1,500 indicators, both of which grow. This is the channel that
does real work.

**Hypothesis generation (speculative).** A language model reading news can
suggest "monsoon onset date affects rural demand". That is a hypothesis, and it
is worth exactly nothing until the data exists and survives testing. Anything
from this channel is labelled speculative and can never be promoted on its own.

Every candidate from either channel must then pass :func:`verify_candidate` --
its endpoint has to actually return parseable data -- before it is anything
other than a suggestion. Discovery that skips verification is how a catalogue
fills up with dead URLs and invented series names.

SAFETY: content fetched from the web is *data*, never instructions. Nothing
here executes, evaluates or follows text retrieved from a remote source, and
discovered entries are written to a registry for human review rather than
merged into the live catalogue.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from vyuha.config import settings
from vyuha.ingest.base import fetch
from vyuha.learn.registry import CandidateRecord, CandidateRegistry

#: Terms that make an unknown dataset plausibly relevant to Indian markets.
#: Deliberately broad -- the statistical stage does the filtering, not this.
RELEVANCE_TERMS = (
    "price", "index", "inflation", "gdp", "production", "output", "trade",
    "export", "import", "credit", "bank", "money", "rate", "yield", "fiscal",
    "deficit", "revenue", "tax", "gst", "employment", "wage", "consumption",
    "sales", "vehicle", "cement", "steel", "power", "electricity", "energy",
    "fuel", "petroleum", "rainfall", "monsoon", "crop", "agri", "harvest",
    "reservoir", "freight", "railway", "port", "cargo", "tourism", "housing",
    "property", "investment", "capital", "foreign", "remittance", "currency",
)

NOISE_TERMS = ("sample data", "test data", "dummy", "demo ")


@dataclass(slots=True)
class Candidate:
    key: str
    name: str
    url: str
    source: str
    rationale: str = ""
    asset_classes: list[str] = field(default_factory=list)
    speculative: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> CandidateRecord:
        return CandidateRecord(
            key=self.key, name=self.name, url=self.url, source=self.source,
            rationale=self.rationale, asset_classes=list(self.asset_classes),
            evidence={"speculative": self.speculative, **self.meta},
        )


def _relevant(title: str, desc: str = "") -> bool:
    hay = f"{title} {desc}".lower()
    if any(n in hay for n in NOISE_TERMS):
        return False
    return any(t in hay for t in RELEVANCE_TERMS)


# ------------------------------------------------------- channel 1: registries


def discover_world_bank(
    snapshot_path: Path | None = None, limit: int = 2000
) -> list[Candidate]:
    """Diff the World Bank indicator list against yesterday's snapshot."""
    snapshot_path = snapshot_path or (settings.cache_dir / "wb_indicators.json")
    payload = fetch(
        "https://api.worldbank.org/v2/indicator",
        params={"format": "json", "per_page": str(limit)},
        ttl=43_200, browser_ua=False,
    ).json()
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise RuntimeError("World Bank indicator list unavailable")

    current = {i["id"]: (i.get("name") or "") for i in payload[1]}
    previous: dict[str, str] = {}
    if snapshot_path.exists():
        try:
            previous = json.loads(snapshot_path.read_text())
        except (json.JSONDecodeError, OSError):
            previous = {}

    new_ids = set(current) - set(previous)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(current, sort_keys=True))

    # First run establishes the baseline; everything would look "new".
    if not previous:
        return []

    out = []
    for iid in sorted(new_ids):
        name = current[iid]
        if not _relevant(name):
            continue
        out.append(Candidate(
            key=f"wb_{iid.lower().replace('.', '_')}", name=name,
            url=f"https://api.worldbank.org/v2/country/IND/indicator/{iid}",
            source="world_bank_registry_diff",
            rationale=f"New World Bank indicator '{name}' appeared in the registry.",
            asset_classes=["macro"], meta={"indicator_id": iid},
        ))
    return out


def discover_data_gov_in(
    snapshot_path: Path | None = None, scan: int = 4000
) -> list[Candidate]:
    """Diff the head of the data.gov.in catalogue for new resources.

    Only the first ``scan`` entries are checked, because the full catalogue is
    ~288,000 resources and the shared demo API key is quota-limited. New
    resources are not guaranteed to appear at the head, so this channel is
    partial by construction and says so.
    """
    from vyuha.ingest.govdata import iter_catalogue

    snapshot_path = snapshot_path or (settings.cache_dir / "dgi_head.json")
    current: dict[str, str] = {}
    for rec in iter_catalogue(max_records=scan):
        rid = rec.get("index_name")
        if rid:
            current[rid] = rec.get("title", "")

    previous: dict[str, str] = {}
    if snapshot_path.exists():
        try:
            previous = json.loads(snapshot_path.read_text())
        except (json.JSONDecodeError, OSError):
            previous = {}

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(current, sort_keys=True))
    if not previous:
        return []

    out = []
    for rid in sorted(set(current) - set(previous)):
        title = current[rid]
        if not _relevant(title):
            continue
        out.append(Candidate(
            key=f"dgi_{rid[:16]}", name=title,
            url=f"https://api.data.gov.in/resource/{rid}",
            source="data_gov_in_diff",
            rationale=f"New data.gov.in resource '{title[:90]}'.",
            asset_classes=["macro"], meta={"resource_id": rid},
        ))
    return out


def discover_fred(candidates: Iterable[str] | None = None) -> list[Candidate]:
    """Probe a curated list of FRED series that would extend coverage.

    Not discovery in the open-ended sense -- FRED has no key-free search -- but
    it closes known gaps, and each probe is verified against the live endpoint
    rather than assumed.
    """
    wanted = {
        "INDCPIALLMINMEI": ("India CPI (OECD via FRED)", ["macro"]),
        "INDPROINDMISMEI": ("India industrial production (OECD)", ["macro"]),
        "IRLTLT01INM156N": ("India 10-year government bond yield", ["bond"]),
        "INTDSRINM193N": ("India discount rate", ["bond"]),
        "XTEXVA01INM667S": ("India merchandise exports", ["macro"]),
        "XTIMVA01INM667S": ("India merchandise imports", ["macro"]),
        "RBINBIS": ("India real broad effective exchange rate", ["currency"]),
        "MKTGDPINA646NWDB": ("India GDP, current USD", ["macro"]),
    }
    if candidates:
        wanted = {k: v for k, v in wanted.items() if k in set(candidates)}
    return [
        Candidate(
            key=f"fred_{sid.lower()}", name=name,
            url=f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
            source="fred_gap_probe",
            rationale=f"Would close a known coverage gap: {name}.",
            asset_classes=acs, meta={"series_id": sid},
        )
        for sid, (name, acs) in wanted.items()
    ]


# -------------------------------------------------- channel 2: hypotheses


def discover_hypotheses(provider=None, n: int = 5) -> list[Candidate]:
    """Ask a local model for variables that might matter. SPECULATIVE.

    Output is marked ``speculative=True`` and can never reach ``promoted``
    without both verification and statistical validation. A model asserting
    that something drives markets is not evidence that it does, and treating
    it as evidence is the single easiest way to turn this loop into an
    expensive random-variable generator.
    """
    from vyuha.council.providers import default_provider, extract_json

    provider = provider or default_provider()
    model = provider.resolve_model(("qwen2.5:32b", "llama3.1:70b", "llama3.2"))
    if not model:
        return []

    prompt = (
        "List variables that plausibly affect Indian equity markets but are "
        "rarely used in conventional risk models. Prefer things with a public "
        "data source. Respond ONLY with JSON:\n"
        '{"variables":[{"name":"...","why":"one sentence","where":"likely public source"}]}'
    )
    resp = provider.generate(
        system="You are a research assistant proposing testable hypotheses. "
               "Do not assert that anything is proven.",
        user=prompt, model=model, temperature=0.7, max_tokens=700,
    )
    if not resp.ok:
        return []
    data, _ = extract_json(resp.text)
    if not data:
        return []

    out = []
    for item in (data.get("variables") or [])[:n]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])[:120]
        key = "hyp_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
        out.append(Candidate(
            key=key, name=name, url=str(item.get("where", ""))[:300],
            source="llm_hypothesis",
            rationale=str(item.get("why", ""))[:300],
            asset_classes=["macro"], speculative=True,
        ))
    return out


# -------------------------------------------------------------- verification


def verify_candidate(cand: Candidate, timeout_rows: int = 5) -> tuple[bool, str, dict]:
    """Does this candidate's endpoint actually return usable data?

    This is the gate that separates a real source from a plausible-looking URL.
    Returns (ok, note, evidence).
    """
    url = (cand.url or "").strip()
    if not url.startswith("http"):
        return False, "no fetchable URL", {}

    try:
        if "worldbank.org" in url:
            payload = fetch(url, params={"format": "json", "per_page": "200"},
                            ttl=3600, browser_ua=False).json()
            if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
                return False, "World Bank returned no observations", {}
            vals = [r for r in payload[1] if r.get("value") is not None]
            if len(vals) < 5:
                return False, f"only {len(vals)} non-null observations", {}
            return True, f"{len(vals)} observations", {
                "n_obs": len(vals),
                "first": vals[-1].get("date"), "last": vals[0].get("date"),
            }

        if "fredgraph.csv" in url:
            import io

            txt = fetch(url, ttl=3600, browser_ua=False).text()
            df = pd.read_csv(io.StringIO(txt))
            if df.shape[1] < 2 or len(df) < 5:
                return False, "FRED returned an empty or malformed series", {}
            vals = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
            if len(vals) < 5:
                return False, f"only {len(vals)} numeric points", {}
            return True, f"{len(vals)} observations", {
                "n_obs": int(len(vals)),
                "first": str(df.iloc[0, 0]), "last": str(df.iloc[-1, 0]),
            }

        if "api.data.gov.in" in url:
            from vyuha.ingest.govdata import _key

            payload = fetch(url, params={"api-key": _key(), "format": "json",
                                         "limit": str(timeout_rows)},
                            ttl=3600, browser_ua=False).json()
            if payload.get("status") == "error":
                return False, str(payload.get("message", "error"))[:120], {}
            recs = payload.get("records") or []
            if not recs:
                return False, "resource returned zero records", {}
            return True, f"{payload.get('total', len(recs))} records", {
                "n_records": payload.get("total"), "fields": list(recs[0])[:12],
            }

        res = fetch(url, ttl=3600, browser_ua=False)
        if len(res.content) < 64:
            return False, "response too small to be data", {}
        return True, f"{len(res.content)} bytes", {"bytes": len(res.content)}

    except Exception as exc:  # noqa: BLE001 - a failed probe is a rejection, not a crash
        return False, f"{type(exc).__name__}: {str(exc)[:120]}", {}


# ------------------------------------------------------------------ top level


def discover_all(
    registry: CandidateRegistry | None = None,
    include_hypotheses: bool = False,
    verify: bool = True,
) -> dict[str, Any]:
    """Run every discovery channel, verify what is new, and record it."""
    registry = registry or CandidateRegistry()
    found: list[Candidate] = []
    errors: list[str] = []

    for name, fn in (
        ("world_bank", discover_world_bank),
        ("data_gov_in", discover_data_gov_in),
        ("fred_gaps", discover_fred),
    ):
        try:
            found.extend(fn())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")

    if include_hypotheses:
        try:
            found.extend(discover_hypotheses())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hypotheses: {str(exc)[:120]}")

    added, verified, rejected = 0, 0, 0
    for cand in found:
        if not registry.add(cand.to_record()):
            continue
        added += 1
        if not verify:
            continue
        ok, note, evidence = verify_candidate(cand)
        if ok:
            registry.set_state(cand.key, "verified", evidence={**evidence, "note": note})
            verified += 1
        else:
            registry.set_state(cand.key, "rejected", rejected_reason=note)
            rejected += 1

    registry.save()
    return {
        "checked_channels": 3 + int(include_hypotheses),
        "found": len(found), "new": added,
        "verified": verified, "rejected": rejected,
        "errors": errors, "registry": registry.counts(),
    }
