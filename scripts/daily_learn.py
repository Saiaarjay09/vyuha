#!/usr/bin/env python3
"""The daily learning cycle.

Run by GitHub Actions on trading mornings, or by hand:

    python scripts/daily_learn.py --all
    python scripts/daily_learn.py --resolve --retune      # the part that matters
    python scripts/daily_learn.py --discover --validate   # the speculative part

Order is deliberate. Resolution and retuning come first because they are what
actually improve accuracy; discovery is downstream and optional. If the time
budget runs out, the right thing to lose is discovery.

Nothing here promotes a candidate into the live catalogue. The most this does
is move something to `validated` and write a report for a human to read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _print(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Vyuha daily learning cycle")
    ap.add_argument("--all", action="store_true", help="every stage")
    ap.add_argument("--snapshot", action="store_true",
                    help="record today's market state (REQUIRED for resolution)")
    ap.add_argument("--generate", action="store_true",
                    help="pose new short-horizon questions to the council")
    ap.add_argument("--answer", action="store_true",
                    help="have the council answer pending generated questions "
                         "(needs a local model)")
    ap.add_argument("--resolve", action="store_true", help="resolve due questions")
    ap.add_argument("--retune", action="store_true", help="re-derive weights and bias")
    ap.add_argument("--discover", action="store_true", help="find new candidates")
    ap.add_argument("--validate", action="store_true", help="statistically test candidates")
    ap.add_argument("--hypotheses", action="store_true",
                    help="also ask a local LLM for speculative variables")
    ap.add_argument("--out", default="data/learning_report.json")
    args = ap.parse_args()

    if args.all:
        args.snapshot = args.generate = args.answer = True
        args.resolve = args.retune = args.discover = args.validate = True
    if not any((args.snapshot, args.generate, args.answer, args.resolve,
                args.retune, args.discover, args.validate)):
        ap.error("choose at least one stage, or --all")

    report: dict = {
        "run_at": dt.datetime.now(dt.UTC).isoformat(),
        "date": str(dt.date.today()),
        "stages": {},
    }

    # --------------------------------------------------------- snapshot
    if args.snapshot:
        _print("0. RECORDING TODAY'S MARKET STATE")
        from vyuha.learn.snapshot import snapshot_today

        try:
            s = snapshot_today()
            print(f"  {s.summary()}")
            for e in s.errors:
                print(f"  error: {e[:130]}")
            report["stages"]["snapshot"] = {
                "written": s.written, "series": s.series, "errors": s.errors,
            }
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["snapshot"] = {"error": str(exc)}

    # --------------------------------------------------------- generate
    if args.generate:
        _print("0b. POSING NEW QUESTIONS")
        try:
            report["stages"]["generate"] = generate_and_store()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["generate"] = {"error": str(exc)}

    # ----------------------------------------------------------- answer
    if args.answer:
        _print("0c. ANSWERING PENDING QUESTIONS")
        try:
            report["stages"]["answer"] = answer_pending()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["answer"] = {"error": str(exc)}

    # ---------------------------------------------------------- resolve
    if args.resolve:
        _print("1. RESOLVING DUE QUESTIONS")
        from vyuha.learn.resolve import resolve_due

        try:
            r = resolve_due()
            print(f"  {r.summary()}")
            for e in r.errors[:5]:
                print(f"  error: {e[:140]}")
            report["stages"]["resolve"] = r.to_dict()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["resolve"] = {"error": str(exc)}

    # ----------------------------------------------------------- retune
    if args.retune:
        _print("2. RE-DERIVING COUNCIL PARAMETERS")
        from vyuha.learn.resolve import retune

        try:
            t = retune()
            print(f"  resolved questions: {t['resolved_questions']}  members: {t['members']}")
            for k in t.get("applied", {}):
                print(f"  applied: {k}")
            for k, why in t.get("withheld", {}).items():
                print(f"  withheld {k}: {why}")
            if "council_vs_members" in t:
                c = t["council_vs_members"]
                print(f"  council Brier {c['council_brier']:.4f} vs mean member "
                      f"{c['mean_member_brier']}; aggregation helping: "
                      f"{c['aggregation_is_helping']}")
            report["stages"]["retune"] = t
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["retune"] = {"error": str(exc)}

    # ------------------------------------------------------- experiments
    if args.retune:
        _print("2b. COMPARING CONFIGURATION VARIANTS")
        try:
            from vyuha.council.scoring import TrackRecord
            from vyuha.learn.experiment import analyse, apply_winners

            track = TrackRecord(ROOT / "council_runs" / "track_record.jsonl")
            results = analyse(track)
            if not results:
                print("  no variant assignments recorded yet")
            for r in results:
                print(f"  {r.setting}: {r.decision[:110]}")
            applied = apply_winners(results)
            if applied["applied"]:
                print(f"  APPLIED: {applied['applied']}")
            report["stages"]["experiments"] = {
                "results": [r.to_dict() for r in results], **applied,
            }
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["experiments"] = {"error": str(exc)}

    # --------------------------------------------------------- discover
    if args.discover:
        _print("3. DISCOVERING CANDIDATE VARIABLES")
        from vyuha.learn.discover import discover_all

        try:
            d = discover_all(include_hypotheses=args.hypotheses)
            print(f"  channels {d['checked_channels']} | found {d['found']} | "
                  f"new {d['new']} | verified {d['verified']} | rejected {d['rejected']}")
            print(f"  registry: {d['registry']}")
            for e in d["errors"]:
                print(f"  error: {e[:140]}")
            report["stages"]["discover"] = d
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["discover"] = {"error": str(exc)}

    # --------------------------------------------------------- validate
    if args.validate:
        _print("4. VALIDATING CANDIDATES AGAINST NIFTY RETURNS")
        try:
            report["stages"]["validate"] = run_validation()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            report["stages"]["validate"] = {"error": str(exc)}

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nreport written to {out}")
    return 0


QUEUE = ROOT / "data" / "question_queue.json"


def generate_and_store() -> dict:
    """Pose a fresh batch and queue it for answering."""
    from vyuha.learn.questions import generate

    r = generate()
    existing = json.loads(QUEUE.read_text()) if QUEUE.exists() else []
    known = {q["id"] for q in existing}
    added = [q.model_dump(mode="json") for q in r.questions if q.id not in known]
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(existing + added, indent=2, default=str))
    print(f"  {r.summary()}; {len(added)} new, {len(existing) + len(added)} queued")
    for q in r.questions[:3]:
        print(f"    {q.text}")
    return {"generated": r.generated, "added": len(added),
            "queued_total": len(existing) + len(added), "skipped": r.skipped}


def answer_pending(limit: int = 12) -> dict:
    """Run the council over queued questions that have no forecast yet.

    Needs a local model, so this stage is skipped on a hosted runner. Each
    answered question becomes a scored forecast once its date passes, which is
    the entire mechanism by which the system improves without being asked to.
    """
    from vyuha.api.server import build_evidence
    from vyuha.council import Council, CouncilConfig, Question, default_provider
    from vyuha.council.providers import EchoProvider

    provider = default_provider()
    if isinstance(provider, EchoProvider):
        print("  no local model available; skipping (CI has no Ollama)")
        return {"answered": 0, "note": "no model"}

    if not QUEUE.exists():
        print("  nothing queued")
        return {"answered": 0}

    queued = json.loads(QUEUE.read_text())
    answered_ids = set()
    for f in (ROOT / "council_runs").glob("*.json"):
        try:
            answered_ids.add(json.loads(f.read_text())["question"]["id"])
        except Exception:  # noqa: BLE001
            continue

    todo = [q for q in queued if q["id"] not in answered_ids][:limit]
    if not todo:
        print(f"  all {len(queued)} queued questions already answered")
        return {"answered": 0, "queued": len(queued)}

    from vyuha.learn.experiment import config_for, record_run

    done = 0
    for raw in todo:
        # Each question is answered under a randomly assigned configuration,
        # so that when it resolves the score attributes to that variant. This
        # is how the system decides whether retrieval is worth its six seconds
        # instead of someone asserting that it is.
        variant = config_for(raw["id"])
        packet = build_evidence(include_global=True,
                                question=raw["text"] if variant["retrieval_enabled"] else None)
        council = Council(provider=provider, config=CouncilConfig(
            rounds=variant["rounds"], min_panel=variant["min_panel"]))
        try:
            council.run(Question.model_validate(raw), packet)
            record_run(raw["id"], variant)
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  failed on {raw['id']}: {str(exc)[:80]}")
    print(f"  answered {done} of {len(todo)} pending ({len(queued)} queued total)")
    return {"answered": done, "queued": len(queued)}


def run_validation() -> dict:
    """Fetch every verified candidate's history and test it against the market."""
    import pandas as pd

    from vyuha.learn.registry import CandidateRegistry
    from vyuha.learn.validate import summarise, validate_candidates

    registry = CandidateRegistry()
    verified = registry.by_state("verified")
    if not verified:
        print("  no verified candidates awaiting validation")
        return {"tested": 0, "note": "nothing to validate"}

    target = _nifty_monthly_returns()
    if target is None or len(target) < 40:
        print("  could not build a target return series; skipping")
        return {"tested": 0, "note": "no usable target series"}

    series: dict[str, pd.DataFrame] = {}
    for rec in verified[:40]:          # bounded, so a daily job stays predictable
        df = _fetch_candidate_series(rec)
        if df is not None and len(df) >= 40:
            series[rec.key] = df

    if not series:
        print(f"  {len(verified)} verified candidates, none with enough history")
        return {"tested": 0, "note": "no candidate had >= 40 observations"}

    results = validate_candidates(series, target)
    s = summarise(results)
    print(f"  {s['reading']}")
    for r in results:
        if r.survives_fdr:
            registry.set_state(r.key, "validated", evidence={
                "oos_rho": r.oos_rho, "p_adjusted": r.p_adjusted,
                "batch_size": r.batch_size, "note": r.note,
            })
            print(f"  VALIDATED {r.key}: oos_rho={r.oos_rho:+.3f} q={r.p_adjusted:.4f}")
    registry.save()
    s["results"] = [r.to_dict() for r in results]
    return s


def _nifty_monthly_returns():
    """Monthly Nifty returns, from whichever source is reachable."""
    import pandas as pd

    from vyuha.store.pit import PITStore

    try:
        with PITStore() as store:
            df = store.as_of(dt.datetime.now(), series_id="NIFTY50_CLOSE")
        if not df.empty and len(df) > 60:
            s = df.set_index(pd.to_datetime(df["event_date"]))["value"].sort_index()
            return s.resample("ME").last().pct_change().dropna()
    except Exception:  # noqa: BLE001
        pass

    # Fall back to a global proxy so the pipeline is still exercised. Clearly
    # not the Nifty -- any result from this is about world equity, not India.
    try:
        from vyuha.ingest.globalmarkets import global_index

        sp = global_index("sp500")
        s = sp.set_index(pd.to_datetime(sp["date"]))["value"].sort_index()
        print("  NOTE: no Nifty history in the store; using S&P 500 as a proxy "
              "target. Results describe world equity, not India.")
        return s.resample("ME").last().pct_change().dropna()
    except Exception:  # noqa: BLE001
        return None


def _fetch_candidate_series(rec):
    """Best-effort history for a candidate, by source type."""
    import io

    import pandas as pd

    from vyuha.ingest.base import fetch

    try:
        if "fredgraph.csv" in rec.url:
            txt = fetch(rec.url, ttl=86_400, browser_ua=False).text()
            df = pd.read_csv(io.StringIO(txt))
            df.columns = ["date", "value"] + list(df.columns[2:])
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.dropna(subset=["date", "value"])[["date", "value"]]

        if "worldbank.org" in rec.url:
            payload = fetch(rec.url, params={"format": "json", "per_page": "500"},
                            ttl=86_400, browser_ua=False).json()
            rows = [{"date": pd.Timestamp(f"{r['date']}-12-31"), "value": r["value"]}
                    for r in (payload[1] or []) if r.get("value") is not None]
            return pd.DataFrame(rows).sort_values("date") if rows else None
    except Exception:  # noqa: BLE001
        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
