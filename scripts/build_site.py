#!/usr/bin/env python3
"""Build a static Vyuha site for GitHub Pages.

WHY THIS EXISTS

GitHub Pages serves static files only -- no Python, no server, no FastAPI. So
it cannot run Vyuha as it stands. But it is free, always on, needs no card,
and never sleeps, which is exactly what a hosted instance on a personal
machine is not.

The resolution is that most of what people actually use Vyuha for does not
need a server at all:

    projections      a block bootstrap over 835 monthly returns -- 8 KB of
                     data and some arithmetic. Runs fine in a browser.
    goal planning    the same simulation, solved backwards.
    portfolio risk   bucketing and stress arithmetic. No server needed.
    today's figures  a JSON file this script refreshes daily.
    the council      genuinely needs a model at request time, so the static
                     site shows the LATEST RECORDED verdicts instead of
                     answering new questions.

So the static build carries the data and the mathematics, and is honest about
the one thing it cannot do.

    python scripts/build_site.py --out site/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ASSETS = ("indian_equity", "gold", "us_equity")


def collect_returns() -> dict:
    """Historical monthly returns, small enough to ship to a browser."""
    from vyuha.projection import ASSET_SOURCES, FIXED_RATE_ASSETS, monthly_returns

    out: dict = {"assets": {}, "fixed": {}}
    for a in ASSETS:
        try:
            r, meta = monthly_returns(a)
            out["assets"][a] = {
                "label": meta["label"],
                "returns": [round(float(x), 6) for x in r.to_numpy()],
                "start": meta["start"], "end": meta["end"],
                "years": meta["years"], "note": meta["source"],
            }
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {a}: {type(exc).__name__}: {str(exc)[:70]}")
    for a, spec in FIXED_RATE_ASSETS.items():
        out["fixed"][a] = {"label": spec["label"], "rate": spec["rate"],
                           "vol": spec["vol"], "note": spec["note"]}
    out["asset_sources"] = {k: v["note"] for k, v in ASSET_SOURCES.items()}
    return out


def collect_market() -> dict:
    """Today's figures, as recorded by the daily snapshot."""
    from vyuha.store.pit import PITStore

    rows = []
    try:
        with PITStore(read_only=True) as store:
            df = store.as_of(dt.datetime.now(),
                             start=dt.date.today() - dt.timedelta(days=10))
        if not df.empty:
            latest = (df.sort_values("event_date")
                        .drop_duplicates("series_id", keep="last"))
            for _, r in latest.iterrows():
                if r["value"] is None:
                    continue
                rows.append({
                    "series": str(r["series_id"]), "value": float(r["value"]),
                    "unit": str(r["unit"] or ""), "source": str(r["source"]),
                    "date": str(r["event_date"]),
                })
    except Exception as exc:  # noqa: BLE001
        print(f"  ! market snapshot unavailable: {str(exc)[:70]}")
    return {"as_of": dt.datetime.now(dt.UTC).isoformat(), "series": rows}


def collect_council() -> dict:
    """The most recent recorded verdicts. The static site cannot answer new
    questions -- that needs a model at request time -- so it shows what the
    council last said rather than pretending to be live."""
    runs = []
    log_dir = ROOT / "council_runs"
    files = sorted(log_dir.glob("*.json"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for f in files:
        if f.name in ("resolutions.json", "tuning.json", "track_record.jsonl"):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        q, v = d.get("question") or {}, d.get("verdict") or {}
        if v.get("probability") is None or (d.get("provider") == "echo"):
            continue
        runs.append({
            "question": q.get("text", ""),
            "probability": v.get("probability"),
            "dispersion": v.get("dispersion"),
            "members": v.get("n_members"),
            "resolves": str(q.get("resolution_date", "")),
            "asked": d.get("created_at", "")[:10],
        })
        if len(runs) >= 20:
            break
    return {"runs": runs}


def collect_scoreboard() -> dict:
    from vyuha.benchmark.scoreboard import REFERENCES, standing
    from vyuha.council.scoring import TrackRecord

    s = standing(TrackRecord(ROOT / "council_runs" / "track_record.jsonl"))
    return {
        "standing": s.to_dict(),
        "references": [{"name": r.name, "brier": r.brier, "source": r.source,
                        "note": r.note} for r in REFERENCES],
    }


def collect_coverage() -> dict:
    from vyuha.ingest.catalogue import asset_class_coverage, coverage_summary

    return {"by_asset_class": asset_class_coverage(),
            "summary": coverage_summary()}


def build(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(exist_ok=True)

    pieces = {
        "returns": collect_returns,
        "market": collect_market,
        "council": collect_council,
        "scoreboard": collect_scoreboard,
        "coverage": collect_coverage,
    }
    manifest: dict = {"built_at": dt.datetime.now(dt.UTC).isoformat(), "files": {}}
    for name, fn in pieces.items():
        try:
            payload = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name} failed: {type(exc).__name__}: {str(exc)[:70]}")
            payload = {"error": str(exc)[:200]}
        path = data_dir / f"{name}.json"
        path.write_text(json.dumps(payload, separators=(",", ":"), default=str))
        kb = path.stat().st_size / 1024
        manifest["files"][name] = round(kb, 1)
        print(f"  {name:11} {kb:7.1f} KB")

    from vyuha.site import PAGE

    (out_dir / "index.html").write_text(PAGE)
    (out_dir / ".nojekyll").touch()   # stop Pages mangling files starting with _
    manifest["files"]["index.html"] = round(
        (out_dir / "index.html").stat().st_size / 1024, 1)
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the static Vyuha site")
    ap.add_argument("--out", default="site", help="output directory")
    args = ap.parse_args()
    out = ROOT / args.out
    print(f"Building static site into {out}")
    m = build(out)
    total = sum(m["files"].values())
    print(f"\n  {len(m['files'])} files, {total:.1f} KB total")
    print(f"  open {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
