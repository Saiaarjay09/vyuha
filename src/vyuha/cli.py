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
council_app = typer.Typer(help="Run and score the forecasting council.")
risk_app = typer.Typer(help="Risk analytics.")
app.add_typer(sources_app, name="sources")
app.add_typer(council_app, name="council")
app.add_typer(risk_app, name="risk")

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
        Council, CouncilConfig, EvidencePacket, Question, QuestionKind, default_provider,
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
