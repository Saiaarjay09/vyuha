"""End-to-end demo: live data -> risk engine -> council.

Run with:  python examples_demo.py
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from vyuha.council import (
    Council, CouncilConfig, EvidencePacket, Question, QuestionKind, default_provider,
)
from vyuha.council.schema import question_id_for
from vyuha.ingest.base import NSESession
from vyuha.ingest.sources import nse_all_indices, nse_fii_dii, nse_option_chain, put_call_ratio
from vyuha.risk.liquidity import concentration
from vyuha.risk.stress import run_all, unmodelled_exposures


def main() -> None:
    print("=" * 74)
    print("1. LIVE MARKET EVIDENCE")
    print("=" * 74)

    packet = EvidencePacket(as_of=dt.datetime.now())
    today = dt.date.today()

    with NSESession() as s:
        idx = nse_all_indices(s)
        for name in ("NIFTY 50", "NIFTY BANK", "INDIA VIX", "NIFTY MIDCAP 100"):
            row = idx[idx["index"].str.upper() == name]
            if len(row):
                packet.add(name.replace(" ", "_"), float(row["last"].iloc[0]),
                           event_date=today, source="NSE")

        for r in nse_fii_dii(s).to_dict("records"):
            packet.add(f"{r['category']}_NET_CASH", float(r["netValue"]),
                       unit="INR cr", event_date=today, source="NSE")

        chain = nse_option_chain("NIFTY", s)
        packet.add("NIFTY_PUT_CALL_RATIO", round(put_call_ratio(chain), 3),
                   event_date=today, source="NSE")
        atm = chain[chain["iv"] > 0]
        if len(atm):
            spot = float(chain.attrs["underlying"])
            near = atm.iloc[(atm["strike"] - spot).abs().argsort()[:6]]
            packet.add("NIFTY_ATM_IV", round(float(near["iv"].mean()), 2),
                       unit="pct", event_date=today, source="NSE")

    print(packet.render())

    print()
    print("=" * 74)
    print("2. STRESS TEST A SAMPLE BOOK")
    print("=" * 74)

    book = pd.DataFrame(
        {
            "value": [40e6, 25e6, 15e6, 12e6, 8e6],
            "beta": [0.85, 1.15, 1.45, 1.30, 0.20],
            "cap_segment": ["large", "large", "mid", "small", "large"],
            "duration": [0.0, 0.0, 0.0, 0.0, 6.2],
        },
        index=["RELIANCE", "HDFCBANK", "MIDCAP_BASKET", "SMALLCAP_BASKET", "GSEC_2033"],
    )
    print(f"Book: INR {book['value'].sum()/1e7:.1f} cr across {len(book)} positions")

    conc = concentration(book["value"])
    print(f"Concentration: top-1 {conc['top1_pct']:.1%}, "
          f"effective N = {conc['effective_n']:.2f} of {conc['n_positions']}")

    missing = unmodelled_exposures(book)
    if missing:
        print(f"UNMODELLED exposure (treated as zero, which may be wrong): "
              f"{', '.join(missing)}")

    res = run_all(book)
    print()
    print(res[["name", "pnl_pct", "equity_pnl", "rates_pnl"]].head(5).to_string(index=False))

    worst = res.iloc[0]
    print(f"\nWorst case: {worst['name']} at {worst['pnl_pct']:.1%} "
          f"(INR {worst['pnl']/1e7:.2f} cr)")

    print()
    print("=" * 74)
    print("3. CONVENE THE COUNCIL")
    print("=" * 74)

    nifty = next((i.value for i in packet.items if i.label == "NIFTY_50"), 23000.0)
    strike = round(float(nifty) * 0.98 / 100) * 100
    resolves = today + dt.timedelta(days=30)

    q = Question(
        id=question_id_for(f"nifty below {strike}", resolves),
        kind=QuestionKind.BINARY,
        text=f"Will the NIFTY 50 close below {strike:,} on any session in the next 30 days?",
        resolution_criteria=f"NSE official NIFTY 50 close < {strike} on any session "
                            f"up to and including {resolves}.",
        resolution_date=resolves,
        resolution_source="NIFTY50_CLOSE",
    )
    print(f"Q: {q.text}\n")

    council = Council(
        provider=default_provider(),
        personas=["hawk", "momentum_bull", "quant", "flows", "red_team"],
        config=CouncilConfig(rounds=2, use_track_record=False),
    )
    verdict = council.run(q, packet)

    print(f"VERDICT: {verdict.summary_line()}\n")
    for f in verdict.member_forecasts:
        p = f"{f.probability:.1%}" if f.probability is not None else "FAILED"
        print(f"  {f.member:16} {p:>7}  cites={len(f.citations)}  "
              f"{(f.key_driver or f.parse_error or '')[:44]}")

    if verdict.dissent:
        print("\nDISSENT")
        for d in verdict.dissent:
            print(f"  - {d[:150]}")

    if verdict.strongest_counterargument:
        print(f"\nSTRONGEST COUNTERARGUMENT\n  {verdict.strongest_counterargument[:320]}")

    print("\nNOTES")
    for n in verdict.notes:
        print(f"  {n[:160]}")

    print("\nReminder: this is calibrated uncertainty, not a prediction, and the "
          "members above may share a base model. See docs/PRECISION.md.")


if __name__ == "__main__":
    main()
