"""Vyuha command line."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vyuha import __version__

app = typer.Typer(
    add_completion=False,
    help="Vyuha - an open risk engine for Indian markets, with a bias-diverse LLM council.",
)
sources_app = typer.Typer(help="Inspect and fetch data sources.")
world_app = typer.Typer(help="Global markets: commodities, world indices, FX, countries.")
council_app = typer.Typer(help="Run and score the forecasting council.")
risk_app = typer.Typer(help="Risk analytics.")
app.add_typer(sources_app, name="sources")
app.add_typer(council_app, name="council")
app.add_typer(risk_app, name="risk")
app.add_typer(world_app, name="world")

console = Console()

_STATUS_STYLE = {
    "working": "green", "fragile": "yellow", "blocked": "red", "planned": "dim",
}


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"vyuha {__version__}")


@app.command()
def doctor() -> None:
    """Check that the environment is set up: deps, models, store, data sources."""
    from vyuha.config import settings

    t = Table(title="Vyuha environment", show_header=True, header_style="bold")
    t.add_column("Check")
    t.add_column("Status")
    t.add_column("Detail", overflow="fold")

    for mod in ("numpy", "pandas", "scipy", "sklearn", "duckdb", "httpx", "pydantic"):
        try:
            m = __import__(mod)
            t.add_row(mod, "[green]ok[/]", getattr(m, "__version__", ""))
        except ImportError:
            t.add_row(mod, "[red]missing[/]", "pip install -e .")

    from vyuha.council.providers import OllamaProvider

    p = OllamaProvider()
    models = p.available_models()
    if models:
        t.add_row("ollama", "[green]ok[/]", f"{len(models)} models: {', '.join(models[:4])}")
    else:
        t.add_row("ollama", "[yellow]unreachable[/]",
                  f"start it with `ollama serve` ({settings.ollama_host})")

    from vyuha.council.personas import PERSONAS

    unresolved = [pr.name for pr in PERSONAS if not p.resolve_model(pr.preferred_models)]
    if models:
        t.add_row(
            "council models",
            "[green]ok[/]" if not unresolved else "[yellow]substituting[/]",
            "all personas mapped" if not unresolved
            else f"no preferred model for: {', '.join(unresolved)}",
        )

    t.add_row("store", "[green]ok[/]" if settings.db_path.exists() else "[dim]empty[/]",
              str(settings.db_path))

    from vyuha.ingest.catalogue import coverage_summary

    cs = coverage_summary()
    t.add_row("data sources", "[green]ok[/]",
              f"{cs['working']} working, {cs['fragile']} fragile, "
              f"{cs['blocked']} blocked, {cs['planned']} planned")
    console.print(t)


# ------------------------------------------------------------------- sources


@sources_app.command("list")
def sources_list(
    domain: str = typer.Option(None, help="Filter by domain, e.g. equity, macro, flows."),
    status: str = typer.Option(None, help="Filter by status: working/fragile/blocked/planned."),
) -> None:
    """List every catalogued data source."""
    from vyuha.ingest.catalogue import CATALOGUE

    rows = CATALOGUE
    if domain:
        rows = [s for s in rows if s.domain.value == domain]
    if status:
        rows = [s for s in rows if s.status.value == status]

    t = Table(show_header=True, header_style="bold")
    for c in ("key", "domain", "status", "verified", "name", "freq", "lag"):
        t.add_column(c, overflow="fold")
    for s in sorted(rows, key=lambda x: (x.domain.value, x.key)):
        style = _STATUS_STYLE.get(s.status.value, "")
        t.add_row(s.key, s.domain.value, f"[{style}]{s.status.value}[/]",
                  s.last_verified or "-", s.name, s.update_freq, s.typical_lag)
    console.print(t)
    console.print(f"[dim]{len(rows)} sources[/]")


@sources_app.command("show")
def sources_show(key: str) -> None:
    """Show everything known about one source."""
    from vyuha.ingest.catalogue import BY_KEY

    if key not in BY_KEY:
        console.print(f"[red]unknown source {key!r}[/]")
        raise typer.Exit(1)
    s = BY_KEY[key]
    body = [
        f"[bold]{s.name}[/]", "", s.description, "",
        f"url          {s.url}",
        f"domain       {s.domain.value}",
        f"status       [{_STATUS_STYLE.get(s.status.value,'')}]{s.status.value}[/]",
        f"verified     {s.last_verified or 'not yet verified'}",
        f"frequency    {s.update_freq} (typical lag: {s.typical_lag})",
        f"licence      {s.licence}",
        f"api key      {'required' if s.needs_key else 'not needed'}",
        f"series       {', '.join(s.series) or '-'}",
    ]
    if s.notes:
        body += ["", f"[italic]{s.notes}[/]"]
    console.print(Panel("\n".join(body), title=key, expand=False))


@sources_app.command("fetch")
def sources_fetch(
    key: str = typer.Argument(..., help="amfi_nav | fred | world_bank | nse_indices | "
                                        "nse_fii_dii | nse_option_chain"),
    series: str = typer.Option("DGS10", help="Series/indicator/symbol, where applicable."),
    limit: int = typer.Option(10, help="Rows to display."),
) -> None:
    """Fetch a source live and show what came back."""
    from vyuha.ingest import sources as S

    fetchers = {
        "amfi_nav": lambda: S.amfi_nav(),
        "fred": lambda: S.fred_series(series),
        "world_bank": lambda: S.world_bank(series if series != "DGS10" else "NY.GDP.MKTP.KD.ZG"),
        "nse_indices": lambda: S.nse_all_indices(),
        "nse_fii_dii": lambda: S.nse_fii_dii(),
        "nse_option_chain": lambda: S.nse_option_chain(series if series != "DGS10" else "NIFTY"),
        "yahoo": lambda: S.yahoo_history(series if series != "DGS10" else "^NSEI"),
        "gdelt": lambda: S.gdelt_tone(series if series != "DGS10" else "india economy"),
    }
    if key not in fetchers:
        console.print(f"[red]no fetcher for {key!r}[/]. Available: {', '.join(fetchers)}")
        raise typer.Exit(1)

    with console.status(f"fetching {key}..."):
        try:
            df = fetchers[key]()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]fetch failed:[/] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]{len(df)} rows[/] from [bold]{df.attrs.get('source', key)}[/]")
    console.print(df.head(limit).to_string())


# ------------------------------------------------------------------- council


@council_app.command("personas")
def council_personas() -> None:
    """List the council members and the bias each one is built around."""
    from vyuha.council.personas import PERSONAS

    for p in PERSONAS:
        console.print(Panel(
            f"[italic]{p.bias}[/]\n\n"
            f"models   {', '.join(p.preferred_models)}\n"
            f"focus    {', '.join(p.focus_series) or '-'}\n"
            f"temp     {p.temperature}   tags: {', '.join(p.tags)}",
            title=f"[bold]{p.name}[/] - {p.title}", expand=False,
        ))


@council_app.command("ask")
def council_ask(
    question: str = typer.Argument(..., help="A question that resolves objectively."),
    resolves: str = typer.Option(..., "--resolves", help="Resolution date, YYYY-MM-DD."),
    criteria: str = typer.Option("", help="Exactly how it resolves."),
    members: str = typer.Option("", help="Comma-separated persona names. Default: all ten."),
    rounds: int = typer.Option(2, help="Deliberation rounds."),
    evidence: Path = typer.Option(None, help="JSON file of {label: value} evidence."),
    live: bool = typer.Option(False, "--live", help="Pull live NSE evidence into the packet."),
) -> None:
    """Put a question to the council."""
    from vyuha.council import (
        Council,
        CouncilConfig,
        EvidencePacket,
        Question,
        QuestionKind,
        default_provider,
    )
    from vyuha.council.schema import question_id_for

    res_date = dt.date.fromisoformat(resolves)
    packet = EvidencePacket(as_of=dt.datetime.now())

    if evidence:
        for label, value in json.loads(evidence.read_text()).items():
            packet.add(label=label, value=value, source=str(evidence.name))
    if live:
        from vyuha.ingest.base import NSESession
        from vyuha.ingest.sources import nse_all_indices, nse_fii_dii

        with console.status("pulling live NSE evidence..."), NSESession() as s:
            try:
                idx = nse_all_indices(s)
                for name in ("NIFTY 50", "NIFTY BANK", "INDIA VIX", "NIFTY MIDCAP 100"):
                    row = idx[idx["index"].str.upper() == name]
                    if len(row):
                        packet.add(label=name.replace(" ", "_"),
                                   value=float(row["last"].iloc[0]),
                                   event_date=dt.date.today(), source="NSE")
                for r in nse_fii_dii(s).to_dict("records"):
                    packet.add(label=f"{r['category']}_NET_CASH",
                               value=float(r["netValue"]), unit="INR cr",
                               source="NSE")
            except Exception as exc:  # noqa: BLE001
                packet.caveats.append(f"live NSE fetch failed: {exc}")

    if not packet.items:
        packet.caveats.append(
            "No evidence supplied. Members must answer from base rates and say so."
        )

    q = Question(
        id=question_id_for(question, res_date), kind=QuestionKind.BINARY, text=question,
        resolution_criteria=criteria or "Resolved by the stated source on the resolution date.",
        resolution_date=res_date, resolution_source="manual",
    )
    names = [m.strip() for m in members.split(",") if m.strip()] or None
    c = Council(provider=default_provider(), personas=names,
                config=CouncilConfig(rounds=rounds))

    console.print(f"[dim]models: {json.dumps(c._model_for)}[/]")
    with console.status(f"convening {len(c.personas)} members over {rounds} round(s)..."):
        v = c.run(q, packet)

    console.print(Panel(f"[bold]{v.summary_line()}[/]", title=q.text, expand=False))

    t = Table(show_header=True, header_style="bold", title="Members")
    for col in ("member", "p", "conf", "cites", "key driver"):
        t.add_column(col, overflow="fold")
    for f in v.member_forecasts:
        t.add_row(
            f.member,
            f"{f.probability:.1%}" if f.probability is not None else "[red]-[/]",
            f"{f.confidence:.2f}", str(len(f.citations)),
            (f.key_driver or (f.parse_error or ""))[:60],
        )
    console.print(t)

    if v.dissent:
        console.print("\n[bold yellow]Dissent[/]")
        for d in v.dissent:
            console.print(f"  - {d}")
    if v.strongest_counterargument:
        console.print(Panel(v.strongest_counterargument,
                            title="Strongest counterargument", expand=False))
    console.print(f"\n[dim]{' | '.join(v.notes)}[/]")


@council_app.command("record")
def council_record(half_life: float = typer.Option(40.0, help="Decay, in questions.")) -> None:
    """Show each member's track record and current pooling weight."""
    from vyuha.config import settings
    from vyuha.council.scoring import TrackRecord

    tr = TrackRecord(settings.council_log_dir / "track_record.jsonl")
    if not tr.rows:
        console.print("[yellow]No resolved forecasts yet.[/] Resolve questions to build "
                      "a record; until then every member is weighted equally.")
        raise typer.Exit()

    scores = tr.all_scores(half_life)
    weights = tr.weights(tr.members())
    bias = tr.bias_corrections(tr.members())

    t = Table(show_header=True, header_style="bold", title="Council track record")
    for c in ("member", "n", "brier", "log", "ECE", "resolution", "bias(logit)", "weight"):
        t.add_column(c)
    for m, r in scores.iterrows():
        t.add_row(str(m), f"{int(r['n'])}", f"{r['mean_brier']:.4f}",
                  f"{r['mean_log_score']:.4f}", f"{r['ece']:.4f}",
                  f"{r['resolution']:.4f}", f"{bias.get(str(m), 0):+.3f}",
                  f"{weights.get(str(m), 0):.3f}")
    console.print(t)
    console.print("[dim]Lower Brier/log/ECE is better. Higher resolution is better. "
                  "Bias is the log-odds offset subtracted before pooling.[/]")


# ---------------------------------------------------------------------- risk


@app.command()
def coverage() -> None:
    """Which asset classes Vyuha can actually answer questions about."""
    from vyuha.ingest.catalogue import asset_class_coverage

    t = Table(show_header=True, header_style="bold", title="Asset class coverage")
    for c in ("asset class", "sources", "usable", "can answer?", "working sources"):
        t.add_column(c, overflow="fold")
    for k, v in asset_class_coverage().items():
        ok = v["can_answer"]
        t.add_row(k.replace("_", " "), str(v["sources"]), str(v["usable"]),
                  "[green]yes[/]" if ok else "[red]NO[/]",
                  ", ".join(v["usable_keys"][:4]) or "[dim]none[/]")
    console.print(t)
    console.print("[dim]'Usable' = a fetcher that returned real data when last run. "
                  "Questions about unanswerable classes are refused, not guessed.[/]")


@app.command()
def benchmark(
    symbol: str = typer.Option("NIFTY", help="Index to read the option chain for."),
    level: float = typer.Option(None, help="Strike level for the probability question."),
    expiry: str = typer.Option(None, help="Expiry, e.g. 19-Oct-2026. Default: ~30 days out."),
) -> None:
    """Extract the market's own forecast from the option chain.

    This is the benchmark to beat. Aladdin cannot be benchmarked -- it is
    proprietary with no public accuracy figures -- but the option-implied
    probability is public, falsifiable and produced by people with money at risk.
    """
    from vyuha.benchmark.implied import implied_from_chain, real_world_adjust
    from vyuha.ingest.base import NSESession
    from vyuha.ingest.sources import nse_option_chain

    with console.status("fetching option chain..."), NSESession() as s:
        chain = nse_option_chain(symbol, s, all_expiries=True)

    spot = float(chain.attrs["underlying"])
    expiries = chain.attrs["expiries"]
    target = expiry or (expiries[4] if len(expiries) > 4 else expiries[-1])
    level = level or round(spot * 0.98 / 100) * 100

    try:
        dist = implied_from_chain(chain, expiry=target)
    except ValueError as exc:
        console.print(f"[red]could not recover a distribution:[/] {exc}")
        raise typer.Exit(1) from exc

    d = dist.diagnostics
    if not d["reliable"]:
        console.print(f"[yellow]warning:[/] unreliable recovery - {d['unreliable_reason']}")

    t = Table(show_header=True, header_style="bold",
              title=f"{symbol} @ {spot:,.1f} - market-implied, expiry {target}")
    t.add_column("measure")
    t.add_column("value", justify="right")
    t.add_row("median", f"{dist.median():,.0f}")
    t.add_row("90% range", f"{dist.quantile(0.05):,.0f} - {dist.quantile(0.95):,.0f}")
    t.add_row("strikes used", str(dist.n_strikes_used))
    t.add_row("", "")
    t.add_row(f"P(finish <= {level:,.0f})", f"{dist.prob_below(level):.2%}")
    t.add_row(f"P(ever touch {level:,.0f})", f"{dist.prob_touch_below(level):.2%}")
    t.add_row("  de-biased for risk premium",
              f"{real_world_adjust(dist.prob_touch_below(level)):.2%}")
    console.print(t)
    console.print("[dim]'Ever touch' is the barrier probability and is the one "
                  "comparable to a 'on any session' council question. Risk-neutral "
                  "probabilities overstate downside; the de-biased row corrects "
                  "crudely for that.[/]")


@world_app.command("commodities")
def world_commodities(
    inr: bool = typer.Option(True, help="Also show the rupee price."),
) -> None:
    """Live commodity prices, in dollars and rupees."""
    from vyuha.ingest.globalmarkets import commodity_snapshot, fx_spot

    with console.status("fetching commodities..."):
        snap = commodity_snapshot()
        rate = None
        if inr:
            try:
                rate = fx_spot("USD").get("INR")
            except Exception:  # noqa: BLE001
                pass

    t = Table(show_header=True, header_style="bold", title="Commodities")
    cols = ["commodity", "price", "unit", "as of", "source"]
    if rate:
        cols.insert(2, f"in INR (@{rate:.2f})")
    for c in cols:
        t.add_column(c, overflow="fold")
    for _, r in snap.iterrows():
        if r["error"]:
            t.add_row(str(r["commodity"]), "[red]failed[/]",
                      *([""] * (len(cols) - 3)), str(r["error"])[:40])
            continue
        row = [str(r["commodity"]), f"{r['value']:,.2f}"]
        if rate:
            row.append(f"{r['value'] * rate:,.0f}")
        row += [str(r["unit"]), str(r["date"]), str(r["source"])]
        t.add_row(*row)
    console.print(t)


@world_app.command("indices")
def world_indices() -> None:
    """World equity indices and global interest rates."""
    from vyuha.ingest.globalmarkets import global_snapshot

    with console.status("fetching world markets..."):
        snap = global_snapshot()
    t = Table(show_header=True, header_style="bold", title="World markets")
    for c in ("series", "value", "unit", "region", "as of"):
        t.add_column(c)
    for _, r in snap.iterrows():
        if r["error"]:
            t.add_row(str(r["series"]), "[red]failed[/]", "", "", str(r["error"])[:30])
            continue
        t.add_row(str(r["series"]), f"{r['value']:,.2f}", str(r["unit"]),
                  str(r["region"]), str(r["date"]))
    console.print(t)


@world_app.command("inr")
def world_inr(
    asset: str = typer.Argument("gold", help="gold | silver | brent | wti | sp500 | nasdaq"),
    since: str = typer.Option(None, help="Start date YYYY-MM-DD. Default: 1 year ago."),
) -> None:
    """What a foreign asset actually returned FOR A RUPEE INVESTOR.

    Splits the return into the asset move and the currency move. This is the
    number an Indian holder of a foreign asset needs and almost never sees: a
    US fund reporting +15% delivered something different in Delhi, and the
    difference is frequently a third of the total.
    """
    import datetime as _dt

    import pandas as pd

    from vyuha.ingest.globalmarkets import (
        FRED_GLOBAL,
        commodity,
        global_index,
        inr_return_decomposition,
    )

    with console.status(f"fetching {asset}..."):
        try:
            df = global_index(asset) if asset in FRED_GLOBAL else commodity(asset)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        start = pd.Timestamp(since) if since else (
            pd.Timestamp(_dt.date.today()) - pd.Timedelta(days=365)
        )
        df = df[df["date"] >= start]
        if len(df) < 2:
            console.print("[red]not enough data in that window[/]")
            raise typer.Exit(1)
        d = inr_return_decomposition(df)

    t = Table(show_header=True, header_style="bold",
              title=f"{asset} for a rupee investor - {d['start']} to {d['end']}")
    t.add_column("component")
    t.add_column("return", justify="right")
    t.add_row("the asset itself (local currency)", f"{d['local_return']:+.2%}")
    t.add_row("the rupee moving", f"{d['currency_return']:+.2%}")
    t.add_row("[bold]what you actually got, in INR[/]",
              f"[bold]{d['total_inr_return']:+.2%}[/]")
    console.print(t)
    share = d["currency_share_of_return"]
    if share == share:
        console.print(f"[dim]Currency was {share:.0%} of the total return. "
                      f"{d['currency']}INR went {d['start_fx']:.2f} -> {d['end_fx']:.2f}.[/]")


@world_app.command("country")
def world_country(
    iso3: str = typer.Argument("IND", help="ISO3 code, e.g. IND, USA, CHN, BRA."),
    indicator: str = typer.Option("gdp_growth", help="See WB_INDICATORS."),
    last: int = typer.Option(10, help="Years to show."),
) -> None:
    """Macro history for any of 217 countries."""
    from vyuha.ingest.globalmarkets import WB_INDICATORS, country_macro

    if indicator not in WB_INDICATORS:
        console.print(f"[yellow]known indicators:[/] {', '.join(WB_INDICATORS)}")
    with console.status(f"fetching {iso3}..."):
        try:
            df = country_macro(iso3.upper(), indicator)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
    t = Table(show_header=True, header_style="bold",
              title=f"{iso3.upper()} - {indicator.replace('_', ' ')}")
    t.add_column("year")
    t.add_column("value", justify="right")
    for _, r in df.tail(last).iterrows():
        t.add_row(str(r["date"].year), f"{r['value']:,.2f}")
    console.print(t)
    console.print("[dim]World Bank, annual and revised for years afterwards. "
                  "Context for comparing economies, not a timing signal.[/]")


@app.command()
def project(
    amount: float = typer.Argument(..., help="Lump sum, or the MONTHLY amount with --sip."),
    years: float = typer.Argument(..., help="Horizon in years."),
    asset: str = typer.Option("indian_equity", help="indian_equity | gold | silver | "
                                                    "us_equity | fixed_deposit | debt_fund"),
    sip: bool = typer.Option(False, "--sip", help="Treat the amount as a monthly contribution."),
    compare: bool = typer.Option(False, "--compare", help="Show other asset classes too."),
) -> None:
    """Project an investment as a distribution of outcomes.

    Never a single number. The point of this command is the spread and the
    downside, not the median.
    """
    from vyuha.projection import compare_assets
    from vyuha.projection import project as _project

    mode = "sip" if sip else "lumpsum"
    with console.status("simulating..."):
        try:
            r = _project(amount, years, asset=asset, mode=mode)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc

    rs = lambda v: f"Rs {v:,.0f}"  # noqa: E731
    t = Table(show_header=True, header_style="bold",
              title=f"{r.asset_label} - {rs(amount)}"
                    f"{'/month' if sip else ''} over {years:g}y")
    t.add_column("outcome")
    t.add_column("value", justify="right")
    t.add_row("[dim]you put in[/]", f"[dim]{rs(r.total_invested)}[/]")
    t.add_row("very unlucky (5th pct)", f"[red]{rs(r.percentiles['p5'])}[/]")
    t.add_row("unlucky (25th)", rs(r.percentiles["p25"]))
    t.add_row("[bold]middle (50th)[/]", f"[bold]{rs(r.percentiles['p50'])}[/]")
    t.add_row("lucky (75th)", rs(r.percentiles["p75"]))
    t.add_row("very lucky (95th)", f"[green]{rs(r.percentiles['p95'])}[/]")
    t.add_row("", "")
    t.add_row("middle, less tax", rs(r.post_tax_percentiles["p50"]))
    t.add_row("[bold]middle, worth in today's money[/]",
              f"[bold]{rs(r.net_real_percentiles['p50'])}[/]")
    console.print(t)

    risk = Table(show_header=False, box=None)
    risk.add_row("chance of ending below what you put in",
                 f"[{'red' if r.prob_loss > 0.2 else 'yellow'}]{r.prob_loss:.0%}[/]")
    risk.add_row("chance of not beating inflation", f"{r.prob_below_inflation:.0%}")
    risk.add_row("chance a fixed deposit beats it", f"{r.prob_below_fd:.0%}")
    risk.add_row("typical worst fall along the way", f"{r.max_drawdown_median:.0%}")
    console.print(risk)

    if compare:
        c = compare_assets(amount, years, mode=mode)
        ct = Table(show_header=True, header_style="bold", title="Same money elsewhere")
        for col in ("asset", "median", "5th pct", "95th pct", "loss risk"):
            ct.add_column(col, justify="right" if col != "asset" else "left")
        for _, row in c.iterrows():
            if row.get("median") != row.get("median"):
                continue
            ct.add_row(str(row["asset"]), rs(row["median"]), rs(row["p5"]),
                       rs(row["p95"]), f"{row['prob_loss']:.0%}")
        console.print(ct)

    console.print(f"[dim]Resampled from {r.sample_start} to {r.sample_end} "
                  f"({r.sample_years}y). Not a prediction, and not advice.[/]")


@risk_app.command("scenarios")
def risk_scenarios() -> None:
    """List the stress scenarios and the lesson each one encodes."""
    from vyuha.risk.stress import SCENARIOS

    for s in SCENARIOS:
        console.print(Panel(
            f"{s.description}\n\n"
            f"equity {s.equity_shock:+.0%}   midcap extra {s.midcap_extra:+.0%}   "
            f"rates {s.rate_shock_bp:+.0f}bp   INR {s.inr_shock:+.0%}   "
            f"oil {s.oil_shock:+.0%}\n"
            f"vol x{s.vol_multiplier}   liquidity haircut {s.liquidity_haircut:.0%}\n\n"
            f"[italic]{s.lesson}[/]",
            title=f"[bold]{s.name}[/] ({s.period})", expand=False,
        ))


@risk_app.command("var")
def risk_var(
    symbol: str = typer.Option("^NSEI", help="Yahoo symbol to analyse."),
    confidence: float = typer.Option(0.99),
    horizon: int = typer.Option(1, help="Horizon in trading days."),
) -> None:
    """Run every VaR estimator on a symbol and show where they disagree."""
    from vyuha.ingest.sources import yahoo_history
    from vyuha.risk.returns import simple_returns
    from vyuha.risk.var import var_ensemble

    with console.status(f"fetching {symbol}..."):
        px = yahoo_history(symbol, range_="5y").set_index("date")["close"]
    r = simple_returns(px)
    console.print(f"[green]{len(r)} daily returns[/] "
                  f"({r.index.min().date()} to {r.index.max().date()})")

    df = var_ensemble(r, confidence, horizon)
    t = Table(show_header=True, header_style="bold",
              title=f"{symbol} VaR - {confidence:.0%}, {horizon}d")
    for c in ("method", "VaR", "ES", "note"):
        t.add_column(c, overflow="fold")
    for name, row in df.iterrows():
        t.add_row(str(name),
                  f"{row['var']:.2%}" if row["var"] == row["var"] else "[red]failed[/]",
                  f"{row['es']:.2%}" if row["es"] == row["es"] else "-",
                  str(row["error"])[:60])
    console.print(t)
    spread = df.attrs.get("spread_ratio")
    if spread and spread == spread:
        style = "red" if spread > 1.5 else "yellow" if spread > 1.25 else "green"
        console.print(f"[{style}]Spread ratio {spread:.2f}x[/] between the most and least "
                      "conservative estimator.")
        if spread > 1.5:
            console.print("[dim]A wide spread means the tail is not pinned down by the "
                          "data. Report the range, not a single number.[/]")


if __name__ == "__main__":
    app()
