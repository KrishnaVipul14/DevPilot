"""Rich terminal formatting for the DevPilot CLI."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from devpilot.core.models import AIExplanation, AnalyzerState, Finding, Report, Severity

console = Console()
err_console = Console(stderr=True)

SEV_STYLE: dict[str, str] = {
    "critical": "bold white on red",
    "high": "bold red",
    "medium": "bold yellow",
    "low": "cyan",
    "info": "dim",
}

RISK_STYLE: dict[str, str] = {
    "critical": "bold white on red",
    "high": "bold red",
    "medium": "bold yellow",
    "low": "bold green",
}


def sev_badge(sev: Severity | str) -> Text:
    val = sev.value if isinstance(sev, Severity) else str(sev).lower()
    return Text(val.upper(), style=SEV_STYLE.get(val, ""))


def print_scan_report(report: Report, max_rows: int = 40) -> None:
    s = report.summary
    sev = s.by_severity
    score_color = "green" if s.health_score >= 80 else "yellow" if s.health_score >= 55 else "red"

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Repository:", f"{report.repository.name} ({report.repository.path})")
    if report.repository.branch or report.repository.commit:
        git_str = f"{report.repository.branch or '?'} @ {(report.repository.commit or '')[:8]}"
        if report.repository.dirty:
            git_str += " [yellow](dirty)[/yellow]"
        header.add_row("Git:", git_str)
    header.add_row("Scan ID:", f"{report.scan_id}  ({report.status.value.upper()})")
    header.add_row(
        "Health Score:",
        f"[{score_color} bold]{s.health_score}/100[/{score_color} bold]  [dim]{s.health_formula}[/dim]",
    )
    header.add_row(
        "Findings:",
        f"[bold]{s.total}[/bold] total — "
        f"[bold red]{sev.get('critical', 0)} critical[/bold red], "
        f"[red]{sev.get('high', 0)} high[/red], "
        f"[yellow]{sev.get('medium', 0)} medium[/yellow], "
        f"[cyan]{sev.get('low', 0)} low[/cyan], "
        f"[dim]{sev.get('info', 0)} info[/dim]",
    )
    if report.memory and report.memory.previous_scan_id:
        m = report.memory
        header.add_row(
            "Memory Delta:",
            f"[yellow]+{m.new} new[/yellow], {m.existing} existing, "
            f"[green]{m.resolved} resolved[/green], [red]{m.reintroduced} reintroduced[/red]",
        )
    if report.graph:
        g = report.graph
        header.add_row(
            "Code Graph:",
            f"{g.modules} modules, {g.functions} functions, {g.classes} classes, "
            f"{g.routes} routes, {g.tests} tests ({g.edges} edges)",
        )

    console.print(Panel(header, title="[bold]DevPilot Repository Intelligence Scan[/bold]", border_style="blue"))

    # Analyzer table
    atab = Table(title="Analyzer Execution", box=None, pad_edge=False)
    atab.add_column("Analyzer", style="bold")
    atab.add_column("Status")
    atab.add_column("Findings", justify="right")
    atab.add_column("Time", justify="right")
    atab.add_column("Details", style="dim")
    for a in report.analyzers:
        st_color = (
            "green" if a.status == AnalyzerState.OK
            else "yellow" if a.status == AnalyzerState.SKIPPED
            else "red"
        )
        atab.add_row(
            a.name,
            f"[{st_color}]{a.status.value.upper()}[/{st_color}]",
            str(a.findings),
            f"{a.duration_ms}ms",
            a.message,
        )
    console.print(atab)
    console.print()

    if not report.findings:
        console.print("[bold green]No issues detected![/bold green]")
        return

    ftab = Table(title=f"Findings (showing {min(len(report.findings), max_rows)} of {len(report.findings)})")
    ftab.add_column("ID", style="bold")
    ftab.add_column("Severity")
    ftab.add_column("Module")
    ftab.add_column("Location")
    ftab.add_column("Title")
    ftab.add_column("Status")
    for f in report.findings[:max_rows]:
        loc = f"{f.file}:{f.line}" if (f.file and f.line) else (f.file or "—")
        ftab.add_row(
            f.id,
            sev_badge(f.severity),
            f.module,
            loc,
            f.title,
            f.status.value,
        )
    console.print(ftab)
    console.print(
        "\n[dim]Next steps: `devpilot explain DP001` | `devpilot fix DP001` | "
        "`devpilot impact` | `devpilot plan` | `devpilot dashboard`[/dim]"
    )


def print_finding_detail(f: Finding, exp: AIExplanation | None = None) -> None:
    loc = f"{f.file}:{f.line}" if (f.file and f.line) else (f.file or "—")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("ID / Rule:", f"{f.id} ({f.module} / {f.rule})  [dim]fp:{f.fingerprint}[/dim]")
    grid.add_row("Severity:", sev_badge(f.severity))
    grid.add_row("Location:", loc + (f"  symbol: `{f.symbol}`" if f.symbol else ""))
    grid.add_row("Confidence:", f"{f.confidence.value}  |  Status: {f.status.value}  |  Verification: {f.verification.value}")
    grid.add_row("Evidence:", f.evidence)
    grid.add_row("Suggestion:", f.suggestion)
    if f.references:
        grid.add_row("References:", ", ".join(f.references))
    console.print(Panel(grid, title=f"[bold]{f.id}: {f.title}[/bold]", border_style="cyan"))

    if exp is not None:
        ai_grid = Table.grid(padding=(0, 2))
        ai_grid.add_column(style="bold magenta")
        ai_grid.add_column()
        ai_grid.add_row("Provider:", f"{exp.provider} ({exp.model}) — AI-generated (non-deterministic)")
        ai_grid.add_row("Summary:", exp.summary)
        ai_grid.add_row("Root Cause:", exp.root_cause)
        ai_grid.add_row("Impact:", exp.impact)
        ai_grid.add_row("Recommended Fix:", exp.recommendation)
        if exp.suggested_tests:
            ai_grid.add_row("Suggested Tests:", "\n".join(f"• {t}" for t in exp.suggested_tests))
        if exp.caveats:
            ai_grid.add_row("Caveats:", f"[dim]{exp.caveats}[/dim]")
        console.print(Panel(ai_grid, title="[bold magenta]AI Engineering Explanation[/bold magenta]", border_style="magenta"))


def print_impact(impact: dict[str, Any]) -> None:
    risk = impact.get("overall_risk") or {"level": "low", "reasons": []}
    lvl = str(risk.get("level", "low")).lower()
    rstyle = RISK_STYLE.get(lvl, "bold")

    top = Table.grid(padding=(0, 2))
    top.add_column(style="bold")
    top.add_column()
    top.add_row("Mode:", f"{impact.get('mode', 'git')}" + (f" (base: {impact['base']})" if impact.get("base") else ""))
    top.add_row("Changed Files:", str(len(impact.get("changed_files", []))))
    top.add_row("Changed Symbols:", str(len(impact.get("changed_symbols", []))))
    top.add_row("Estimated Risk:", Text(lvl.upper(), style=rstyle))
    top.add_row("Risk Evidence:", "\n".join(f"• {r}" for r in risk.get("reasons", [])))
    if impact.get("suggested_commands"):
        top.add_row("Suggested Action:", "\n".join(f"`{c}`" for c in impact["suggested_commands"]))

    console.print(Panel(top, title="[bold]DevPilot Change Impact Analysis[/bold]", border_style="blue"))

    for item in impact.get("impacts", []):
        itab = Table.grid(padding=(0, 2))
        itab.add_column(style="bold")
        itab.add_column()
        ilvl = str((item.get("risk") or {}).get("level", "low")).lower()
        itab.add_row("Risk:", Text(ilvl.upper(), style=RISK_STYLE.get(ilvl, "bold")))
        itab.add_row(
            "Dependent Functions:",
            ", ".join(item["callers"]) if item.get("callers") else "[dim]None identified[/dim]",
        )
        itab.add_row(
            "Dependent Modules:",
            ", ".join(item["dependent_modules"]) if item.get("dependent_modules") else "[dim]None identified[/dim]",
        )
        routes = item.get("routes") or []
        itab.add_row(
            "API Endpoints:",
            ", ".join(f"{r['method']} {r['path']}" for r in routes) if routes else "[dim]None identified[/dim]",
        )
        tests = item.get("tests") or []
        itab.add_row(
            "Relevant Tests:",
            ", ".join(f"{t['nodeid']} ({t['certainty']})" for t in tests) if tests else "[yellow]None identified[/yellow]",
        )
        console.print(Panel(itab, title=f"Symbol: [bold]{item['symbol']}[/bold]"))


def print_history(history: dict[str, Any]) -> None:
    scans = history.get("scans") or []
    if not scans:
        console.print("[yellow]No scan history recorded yet. Run `devpilot scan .` first.[/yellow]")
        return

    tab = Table(title="Repository Scan History")
    tab.add_column("Scan ID", style="bold")
    tab.add_column("Finished At")
    tab.add_column("Commit")
    tab.add_column("Health", justify="right")
    tab.add_column("Total", justify="right")
    tab.add_column("+New", justify="right", style="yellow")
    tab.add_column("Resolved", justify="right", style="green")
    tab.add_column("Reintro", justify="right", style="red")
    for s in scans[:25]:
        tab.add_row(
            s["scan_id"],
            s["finished_at"][:19].replace("T", " "),
            (s["commit"] or "—")[:8],
            f"{s['health_score']}/100",
            str(s["total"]),
            str(s["new"]),
            str(s["resolved"]),
            str(s["reintroduced"]),
        )
    console.print(tab)

    vers = history.get("verifications") or []
    if vers:
        vtab = Table(title="Patch Verification History")
        vtab.add_column("Patch ID", style="bold")
        vtab.add_column("Finding")
        vtab.add_column("Title")
        vtab.add_column("Status")
        vtab.add_column("Checks")
        for v in vers[:15]:
            checks_str = ", ".join(f"{c['name']}:{c['status']}" for c in v.get("checks", []))
            vtab.add_row(v["patch_id"], v["finding_id"], v["title"], v["status"].upper(), checks_str)
        console.print(vtab)


def print_plan(plan: dict[str, Any]) -> None:
    src = (
        f"AI-generated ({plan.get('provider')}/{plan.get('model')})"
        if plan.get("source") == "ai"
        else "Deterministic prioritization (offline / AI fallback)"
    )
    console.print(
        Panel(
            f"[bold]{plan.get('summary')}[/bold]\n[dim]Source: {src}[/dim]",
            title="[bold]DevPilot Prioritized Improvement Plan[/bold]",
            border_style="blue",
        )
    )
    for t in plan.get("tasks", []):
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold")
        grid.add_column()
        grid.add_row("Why it matters:", t.get("why", ""))
        grid.add_row("Resolution:", t.get("resolution", ""))
        grid.add_row("Findings:", ", ".join(t.get("finding_ids", [])))
        grid.add_row("Verification:", ", ".join(t.get("tests", [])) + f"  (effort: {t.get('effort', 'small')})")
        console.print(Panel(grid, title=f"[bold]Priority #{t.get('priority')}: {t.get('title')}[/bold]"))


def print_patch(patch: dict[str, Any]) -> None:
    src = (
        "Deterministic fix (Ruff / manifest rule)"
        if patch.get("engine") == "ruff"
        else "AI-generated search/replace patch (requires review & verification)"
    )
    info = (
        f"[bold]Patch ID:[/bold] {patch['patch_id']}   "
        f"[bold]Finding:[/bold] {patch['finding_id']} ({patch['title']})\n"
        f"[bold]Engine:[/bold] {src}\n"
        f"[bold]Summary:[/bold] {patch['summary']}\n"
        f"[bold]Status:[/bold] {patch['status'].upper()}"
    )
    console.print(Panel(info, title="[bold]Proposed Fix Patch[/bold]", border_style="cyan"))
    console.print(Syntax(patch.get("diff", ""), "diff", theme="monokai", word_wrap=True))

    ver = patch.get("verification")
    if ver:
        vtab = Table(title=f"Verification Result: {ver['status'].upper()} (isolated {ver.get('mode', 'worktree')})")
        vtab.add_column("Check", style="bold")
        vtab.add_column("Status")
        vtab.add_column("Duration", justify="right")
        vtab.add_column("Detail")
        for c in ver.get("checks", []):
            color = "green" if c["status"] == "passed" else "yellow" if c["status"] == "skipped" else "red"
            vtab.add_row(
                c["name"],
                f"[{color}]{c['status'].upper()}[/{color}]",
                f"{c['duration_ms']}ms",
                (c.get("detail") or "").splitlines()[0][:100] if c.get("detail") else "",
            )
        console.print(vtab)
