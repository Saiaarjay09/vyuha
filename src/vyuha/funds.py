"""Looking up Indian mutual funds.

AMFI publishes the NAV of every scheme in India daily, and Vyuha has been
fetching all 14,400 of them since the ingest layer was built -- and using none
of them. This makes that data reachable.

What it can answer: does this fund exist, what is it worth today, who runs it,
what category is it in, and how does its NAV compare to its peers'.

What it CANNOT answer, and says so: whether a fund is any good. That needs a
return history, and AMFI's daily file carries only today's NAV. Comparing raw
NAVs between funds is meaningless -- a Rs 500 NAV is not "expensive" and a
Rs 10 NAV is not "cheap", they are just different unit sizes -- and this module
refuses to imply otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd


@dataclass(slots=True)
class FundMatch:
    scheme_code: str
    name: str
    amc: str
    category: str
    nav: float
    date: str
    plan: str = ""
    option: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class FundSearch:
    query: str
    matches: list[FundMatch] = field(default_factory=list)
    total_schemes: int = 0
    category_peers: int = 0
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["matches"] = [m.to_dict() for m in self.matches]
        return d


def _score(name: str, terms: list[str]) -> int:
    low = name.lower()
    return sum(3 if low.startswith(t) else 1 for t in terms if t in low)


def search(query: str, limit: int = 8, prefer_direct_growth: bool = True) -> FundSearch:
    """Find schemes matching a name.

    Prefers Direct/Growth plans by default. Regular plans pay a distributor
    commission out of the fund, so for the same scheme the Direct plan keeps
    more of the return -- a difference that compounds to a meaningful amount
    over a decade and is invisible in a NAV comparison.
    """
    from vyuha.ingest.sources import amfi_nav

    df = amfi_nav()
    res = FundSearch(query=query, total_schemes=len(df))

    terms = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower())
             if t not in ("fund", "mutual", "scheme", "plan", "the")]
    if not terms:
        res.caveats.append("Give a fund or AMC name to search for.")
        return res

    mask = pd.Series(True, index=df.index)
    for t in terms:
        mask &= (df["scheme_name"].str.lower().str.contains(t, regex=False)
                 | df["amc"].str.lower().str.contains(t, regex=False))
    hits = df[mask].copy()
    if hits.empty:
        res.caveats.append(
            f"No scheme matched '{query}' among {len(df):,} schemes. Try the "
            "AMC name, or fewer words."
        )
        return res

    hits["_score"] = hits["scheme_name"].apply(lambda n: _score(n, terms))
    if prefer_direct_growth:
        hits["_score"] += (
            hits["plan"].fillna("").str.contains("Direct", case=False).astype(int) * 2
            + hits["option"].fillna("").str.contains("Growth", case=False).astype(int)
        )
    hits = hits.sort_values("_score", ascending=False)

    for _, r in hits.head(limit).iterrows():
        res.matches.append(FundMatch(
            scheme_code=str(r["scheme_code"]), name=str(r["scheme_name"]),
            amc=str(r["amc"]), category=str(r["category"]),
            nav=float(r["nav"]), date=str(pd.Timestamp(r["date"]).date()),
            plan=str(r.get("plan") or ""), option=str(r.get("option") or ""),
        ))

    if res.matches:
        cat = res.matches[0].category
        res.category_peers = int((df["category"] == cat).sum())

    res.caveats = [
        "NAV is today's unit price, not a measure of quality. A Rs 500 NAV is "
        "not 'expensive' and a Rs 10 NAV is not 'cheap' -- they are different "
        "unit sizes for the same rupee invested.",
        "AMFI's daily file carries only today's NAV, so past returns cannot be "
        "computed here. Whether a fund is good needs a return history this "
        "does not have.",
        "Direct plans are shown first where available: they pay no distributor "
        "commission, so for the same scheme they keep more of your return.",
    ]
    return res


def categories(contains: str = "", limit: int = 25) -> pd.DataFrame:
    """What scheme categories exist, and how many schemes each holds."""
    from vyuha.ingest.sources import amfi_nav

    df = amfi_nav()
    counts = (df.groupby("category").size()
                .sort_values(ascending=False).rename("schemes").reset_index())
    if contains:
        counts = counts[counts["category"].str.contains(contains, case=False)]
    return counts.head(limit)
