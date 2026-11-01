"""Typer CLI command implementations for DevPilot."""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Any

import typer

from devpilot import __version__
from devpilot.ai.architect import ask_codebase
from devpilot.ai.provider import AIProviderError
from devpilot.ai.suggestions import explain_finding, generate_plan
from devpilot.analyzers.change_impact import analyze_git_impact, analyze_symbol_impact
from devpilot.analyzers.mermaid import export_mermaid
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.cli.output import (
    console,
    err_console,
    print_ask_answer,
    print_finding_detail,
    print_history,
    print_impact,
    print_patch,
    print_plan,
    print_scan_report,
    print_test_scaffold,
)
from devpilot.core.config import (
    DEFAULT_CONFIG_TEMPLATE,
    ConfigError,
    find_config,
    load_config,
    state_dir,
)
from devpilot.core.context import RepoContext
from devpilot.core.models import Severity
from devpilot.core.report import (
    find_finding,
    latest_report_path,
    load_latest_graph,
    load_latest_report,
)
from devpilot.core.scanner import run_scan
from devpilot.dashboard_server.server import create_server
from devpilot.fixes.patch_generator import PatchError, propose_patch
from devpilot.fixes.patch_manager import apply_patch, discard_patch, verify_patch
from devpilot.fixes.test_generator import generate_test_scaffold
from devpilot.integrations.github_ci import (
    format_github_annotation,
    format_markdown_summary,
    write_github_step_summary,
)
from devpilot.memory.history import load_history

app = typer.Typer(
    name="devpilot",
    help="DevPilot — Your Repository's AI Engineering Assistant. Detect, understand, analyze impact, fix, verify, and remember.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"devpilot {__version__}")
        raise typer.Exit(0)


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show DevPilot version and exit.",
    ),
) -> None:
    """DevPilot CLI."""


@app.command("init")
def cmd_init(
    path: Path = typer.Argument(Path("."), help="Target repository directory."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing devpilot.yml."),
) -> None:
    """Initialize DevPilot configuration (`devpilot.yml`) and `.devpilot/` directory."""
    root = path.resolve()
    if not root.is_dir():
        err_console.print(f"[red]Error:[/red] Directory `{root}` does not exist.")
        raise typer.Exit(2)

    existing = find_config(root)
    target = existing or (root / "devpilot.yml")
    if target.exists() and not force:
        console.print(f"[yellow]Configuration already exists at {target}. Use --force to overwrite.[/yellow]")
    else:
        target.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        console.print(f"[green]Created configuration:[/green] {target}")

    sdir = state_dir(root)
    (sdir / "reports").mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        gi_text = gitignore.read_text(encoding="utf-8", errors="replace")
        if ".devpilot" not in gi_text:
            suffix = "" if gi_text.endswith("\n") or not gi_text else "\n"
            gitignore.write_text(f"{gi_text}{suffix}.devpilot/\n", encoding="utf-8")
            console.print("[green]Added `.devpilot/` to `.gitignore`.[/green]")
    console.print(f"[bold green]DevPilot initialized in {root}[/bold green] — run `devpilot scan .` next.")


@app.command("scan")
def cmd_scan(
    path: Path = typer.Argument(Path("."), help="Repository path to scan."),
    demo: bool = typer.Option(False, "--demo", help="Scan the built-in demo repository (examples/demo-app)."),
    offline: bool = typer.Option(False, "--offline", help="Skip network-dependent checks (such as OSV.dev)."),
    json_out: bool = typer.Option(False, "--json", help="Print unified JSON report to stdout."),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="Exit with code 1 if any finding has at least this severity (critical, high, medium, low).",
    ),
) -> None:
    """Run repository analyzers, build the code intelligence graph, and save `.devpilot/reports/latest.json`."""
    if demo:
        root, _ = _resolve_repo_path(None, demo=True)
    else:
        root = path.resolve()
    if not root.is_dir():
        err_console.print(f"[red]Error:[/red] `{root}` is not a directory.")
        raise typer.Exit(2)
    try:
        cfg = load_config(root)
    except ConfigError as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(2) from exc

    report = run_scan(root, config=cfg, offline=offline, persist=True)
    if json_out:
        print(report.model_dump_json(indent=2))
    else:
        print_scan_report(report)
        console.print(f"[dim]Saved report to {latest_report_path(root)}[/dim]")

    if fail_on:
        try:
            threshold = Severity(fail_on.strip().lower())
        except ValueError as exc:
            err_console.print(f"[red]Invalid --fail-on severity `{fail_on}`.[/red]")
            raise typer.Exit(2) from exc
        if any(f.severity.rank <= threshold.rank for f in report.findings):
            raise typer.Exit(1)


def _resolve_repo_path(path: Path | None, demo: bool = False) -> tuple[Path, bool]:
    cwd = Path.cwd().resolve()
    candidates = [
        cwd / "examples" / "demo-app",
        Path(__file__).resolve().parent.parent.parent / "examples" / "demo-app",
    ]
    demo_dir = next((c.resolve() for c in candidates if c.is_dir()), None)

    if demo:
        if demo_dir:
            return demo_dir, True
        err_console.print("[red]Built-in demo repository `examples/demo-app` not found.[/red]")
        raise typer.Exit(2)

    if path is None:
        if demo_dir is not None and ((cwd / "devpilot").is_dir() or cwd == demo_dir.parent.parent):
            return demo_dir, True
        return cwd, False

    resolved = path.resolve()
    if demo_dir and (resolved == demo_dir or (resolved == cwd and (cwd / "devpilot").is_dir())):
        return demo_dir, True
    return resolved, False


@app.command("dashboard")
def cmd_dashboard(
    path: Path | None = typer.Option(
        None, "--path", "-p", help="Target repository directory (defaults to built-in demo-app)."
    ),
    demo: bool = typer.Option(False, "--demo", help="Open the built-in demo-app repository."),
    port: int = typer.Option(8765, "--port", help="Local port on 127.0.0.1."),
    open_browser: bool = typer.Option(False, "--open", help="Open the dashboard in the default browser."),
) -> None:
    """Launch the local DevPilot dashboard and API server on `http://127.0.0.1:<port>`."""
    root, is_demo = _resolve_repo_path(path, demo=demo)
    url = f"http://127.0.0.1:{port}"
    server = create_server(root, host="127.0.0.1", port=port)
    repo_label = "[bold cyan]Demo Project (examples/demo-app)[/bold cyan]" if is_demo else f"{root}"
    console.print(
        f"[bold green]DevPilot local dashboard running at[/bold green] [underline]{url}[/underline]\n"
        f"[dim]Repository: {repo_label}  |  Bound to 127.0.0.1 only  |  Press Ctrl+C to stop[/dim]"
    )
    if is_demo:
        console.print(
            "[dim]Tip: To analyze your own codebase, specify: `devpilot dashboard -p /path/to/your/project`[/dim]"
        )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down dashboard server.[/dim]")
    finally:
        server.server_close()


@app.command("web", help="Alias for 'dashboard'. Launch the local DevPilot web dashboard.")
def cmd_web(
    path: Path | None = typer.Option(
        None, "--path", "-p", help="Target repository directory (defaults to built-in demo-app)."
    ),
    demo: bool = typer.Option(False, "--demo", help="Open the built-in demo-app repository."),
    port: int = typer.Option(8765, "--port", help="Local port on 127.0.0.1."),
    open_browser: bool = typer.Option(False, "--open", help="Open the dashboard in the default browser."),
) -> None:
    cmd_dashboard(path=path, demo=demo, port=port, open_browser=open_browser)


@app.command("history")
def cmd_history(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    json_out: bool = typer.Option(False, "--json", help="Output history as JSON."),
) -> None:
    """Display historical scan results, finding trends, and verification outcomes from SQLite memory."""
    root = path.resolve()
    hist = load_history(root)
    if json_out:
        print(json.dumps(hist, indent=2))
    else:
        print_history(hist)


@app.command("impact")
def cmd_impact(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    base: str = typer.Option("HEAD", "--base", "-b", help="Git ref to diff against."),
    symbol: str | None = typer.Option(
        None,
        "--symbol",
        "-s",
        help="Analyze impact of changing a specific function or class (e.g. validate_token).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output impact report as JSON."),
) -> None:
    """Analyze Git changes (or a target symbol) and map affected functions, routes, tests, and risk."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))
    cached = load_latest_graph(root)
    graph = RepoGraph.from_dict(cached) if cached else RepoGraph.build(ctx)

    if symbol:
        impact = analyze_symbol_impact(ctx, symbol, graph=graph)
    else:
        impact = analyze_git_impact(ctx, base=base, graph=graph)

    if json_out:
        print(json.dumps(impact, indent=2))
    else:
        print_impact(impact)


@app.command("explain")
def cmd_explain(
    finding_id: str = typer.Argument(..., help="Finding ID (e.g. DP001) or fingerprint."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    force: bool = typer.Option(False, "--force", help="Bypass cached AI explanation."),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Explain a detected finding, its root cause, impact, and remediation using AI (with deterministic details)."""
    root = path.resolve()
    report = load_latest_report(root, refresh_from_memory=True)
    if report is None:
        err_console.print("[red]No scan report found. Run `devpilot scan .` first.[/red]")
        raise typer.Exit(1)

    finding = find_finding(report, finding_id)
    if finding is None:
        err_console.print(f"[red]Finding `{finding_id}` not found in the latest report.[/red]")
        raise typer.Exit(1)

    ctx = RepoContext(root=root, config=load_config(root))
    exp = None
    ai_err: str | None = None
    try:
        exp = explain_finding(ctx, finding, force=force)
    except AIProviderError as exc:
        ai_err = str(exc)

    if json_out:
        print(
            json.dumps(
                {
                    "finding": finding.model_dump(mode="json"),
                    "ai_explanation": exp.model_dump(mode="json") if exp else None,
                    "ai_unavailable_reason": ai_err,
                },
                indent=2,
            )
        )
        return

    print_finding_detail(finding, exp=exp)
    if ai_err:
        console.print(
            f"[yellow]Note: AI explanation unavailable ({ai_err}). Displayed deterministic finding details above.[/yellow]"
        )


def _handle_fix_discard(ctx: RepoContext, finding_id: str) -> None:
    try:
        patch = discard_patch(ctx, finding_id)
    except PatchError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[yellow]Discarded patch `{patch['patch_id']}` for `{patch['finding_id']}`.[/yellow]")


def _handle_fix_verification(
    ctx: RepoContext, patch: dict[str, Any], yes: bool, json_out: bool
) -> dict[str, Any] | None:
    if not yes and not json_out:
        approved = typer.confirm(
            f"Approve patch {patch['patch_id']} to run verification in an isolated worktree?", default=True
        )
        if not approved:
            console.print("[yellow]Verification cancelled. Patch remains in 'proposed' state.[/yellow]")
            return None
    return verify_patch(ctx, patch["patch_id"])


def _handle_fix_application(
    ctx: RepoContext, patch: dict[str, Any], yes: bool, json_out: bool
) -> dict[str, Any] | None:
    if patch["status"] not in ("verified", "partially_verified"):
        err_console.print(
            f"[red]Refusing to apply patch because verification status is `{patch['status']}`.[/red]"
        )
        raise typer.Exit(1)
    if not yes and not json_out:
        approved_apply = typer.confirm(
            f"Apply verified patch {patch['patch_id']} to your working tree?", default=False
        )
        if not approved_apply:
            console.print(
                "[yellow]Patch was verified in isolation but NOT applied to the working tree.[/yellow]"
            )
            return None
    return apply_patch(ctx, patch["patch_id"])


@app.command("fix")
def cmd_fix(
    finding_id: str = typer.Argument(..., help="Finding ID (e.g. DP001) or fingerprint."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    engine: str = typer.Option("auto", "--engine", help="Fix engine: auto, ruff, or ai."),
    verify_now: bool = typer.Option(
        False, "--verify", help="Immediately verify the proposed patch in an isolated Git worktree."
    ),
    apply_now: bool = typer.Option(
        False, "--apply", help="Apply the verified patch to the working tree after approval."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve verification/application without interactive prompt."
    ),
    discard: bool = typer.Option(
        False, "--discard", help="Discard an existing proposed patch for this finding."
    ),
    json_out: bool = typer.Option(False, "--json", help="Output patch as JSON."),
) -> None:
    """Propose a safe fix patch for a finding and preview the unified diff."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))

    if discard:
        _handle_fix_discard(ctx, finding_id)
        return

    report = load_latest_report(root, refresh_from_memory=False)
    if report is None:
        err_console.print("[red]No scan report found. Run `devpilot scan .` first.[/red]")
        raise typer.Exit(1)

    finding = find_finding(report, finding_id)
    if finding is None:
        err_console.print(f"[red]Finding `{finding_id}` not found in the latest report.[/red]")
        raise typer.Exit(1)

    if engine not in ("auto", "ruff", "ai"):
        err_console.print("[red]--engine must be one of: auto, ruff, ai[/red]")
        raise typer.Exit(2)

    try:
        patch = propose_patch(ctx, finding, engine=engine)  # type: ignore[arg-type]
    except PatchError as exc:
        err_console.print(f"[red]Could not generate fix:[/red] {exc}")
        raise typer.Exit(1) from exc

    if verify_now or apply_now:
        verified_patch = _handle_fix_verification(ctx, patch, yes, json_out)
        if verified_patch is None:
            return
        patch = verified_patch

    if apply_now:
        applied_patch = _handle_fix_application(ctx, patch, yes, json_out)
        if applied_patch is None:
            return
        patch = applied_patch

    if json_out:
        print(json.dumps(patch, indent=2))
    else:
        print_patch(patch)
        if patch["status"] == "proposed":
            console.print(
                f"\n[dim]Next step: `devpilot verify {finding.id}` (or `devpilot verify {patch['patch_id']}`)[/dim]"
            )


@app.command("verify")
def cmd_verify(
    ref: str = typer.Argument(..., help="Finding ID (e.g. DP001), patch ID, or fingerprint."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    apply_after: bool = typer.Option(
        False, "--apply", help="Apply the patch to the working tree if verification passes."
    ),
    discard_after: bool = typer.Option(False, "--discard", help="Discard the patch instead of verifying."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive confirmation prompt."),
    json_out: bool = typer.Option(False, "--json", help="Output verification result as JSON."),
) -> None:
    """Verify an approved patch in an isolated Git worktree (syntax + Ruff + targeted pytest)."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))

    if discard_after:
        try:
            patch = discard_patch(ctx, ref)
        except PatchError as exc:
            err_console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        console.print(f"[yellow]Discarded patch `{patch['patch_id']}`.[/yellow]")
        return

    try:
        patch = verify_patch(ctx, ref)
    except PatchError as exc:
        err_console.print(f"[red]Verification error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if apply_after:
        if patch["status"] not in ("verified", "partially_verified"):
            print_patch(patch)
            err_console.print(f"[red]Cannot apply patch with verification status `{patch['status']}`.[/red]")
            raise typer.Exit(1)
        if not yes and not json_out:
            if not typer.confirm(f"Apply verified patch {patch['patch_id']} to working tree?", default=False):
                print_patch(patch)
                return
        patch = apply_patch(ctx, patch["patch_id"])

    if json_out:
        print(json.dumps(patch, indent=2))
    else:
        print_patch(patch)

    if patch["status"] == "failed":
        raise typer.Exit(1)


@app.command("plan")
def cmd_plan(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Use deterministic prioritization without AI."
    ),
    json_out: bool = typer.Option(False, "--json", help="Output plan as JSON."),
) -> None:
    """Generate a prioritized engineering improvement plan from the latest scan."""
    root = path.resolve()
    report = load_latest_report(root, refresh_from_memory=True)
    if report is None:
        err_console.print("[red]No scan report found. Run `devpilot scan .` first.[/red]")
        raise typer.Exit(1)

    ctx = RepoContext(root=root, config=load_config(root))
    plan = generate_plan(ctx, report, prefer_ai=not deterministic)
    if json_out:
        print(json.dumps(plan, indent=2))
    else:
        print_plan(plan)


@app.command("report")
def cmd_report(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table, json, or markdown."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write report to a file."),
) -> None:
    """Display or export the latest unified scan report."""
    root = path.resolve()
    report = load_latest_report(root, refresh_from_memory=True)
    if report is None:
        err_console.print("[red]No scan report found. Run `devpilot scan .` first.[/red]")
        raise typer.Exit(1)

    fmt_lower = fmt.strip().lower()
    if fmt_lower == "json":
        text = report.model_dump_json(indent=2)
        if output:
            output.write_text(text, encoding="utf-8")
            console.print(f"[green]Wrote JSON report to {output}[/green]")
        else:
            print(text)
    elif fmt_lower in ("markdown", "md"):
        text = format_markdown_summary(report)
        if output:
            output.write_text(text, encoding="utf-8")
            console.print(f"[green]Wrote Markdown report to {output}[/green]")
        else:
            print(text)
    else:
        print_scan_report(report, max_rows=100)


@app.command("ci")
def cmd_ci(
    path: Path = typer.Argument(Path("."), help="Repository path."),
    base: str = typer.Option("HEAD~1", "--base", help="Base Git ref for PR impact analysis."),
    offline: bool = typer.Option(False, "--offline", help="Skip network-dependent checks."),
    fail_on: str = typer.Option(
        "critical", "--fail-on", help="Fail workflow on severity (critical, high, medium, low, none)."
    ),
) -> None:
    """Run DevPilot in CI / GitHub Actions mode: emit annotations and write a Job Summary."""
    root = path.resolve()
    cfg = load_config(root)
    report = run_scan(root, config=cfg, offline=offline, persist=True)
    ctx = RepoContext(root=root, config=cfg, offline=offline)
    impact = analyze_git_impact(ctx, base=base)

    for f in report.findings:
        print(format_github_annotation(f))

    md = format_markdown_summary(report, impact=impact)
    summary_path = write_github_step_summary(md)
    if summary_path:
        console.print(f"[green]Appended job summary to {summary_path}[/green]")
    else:
        console.print(md)

    if fail_on.strip().lower() != "none":
        try:
            threshold = Severity(fail_on.strip().lower())
            if any(f.severity.rank <= threshold.rank for f in report.findings):
                raise typer.Exit(1)
        except ValueError:
            pass


@app.command("ask")
def cmd_ask(
    question: str = typer.Argument(
        ..., help="Question about repository architecture, auth, routes, or code flow."
    ),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    json_out: bool = typer.Option(False, "--json", help="Output answer as raw JSON."),
) -> None:
    """Ask DevPilot Repository Architect questions about codebase flow, endpoints, and architecture."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))
    res = ask_codebase(ctx, question)
    if json_out:
        print(json.dumps(res, indent=2))
    else:
        print_ask_answer(res)


@app.command("testgen")
def cmd_testgen(
    symbol: str = typer.Argument(..., help="Function, method, class, or route to generate unit tests for."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    write: bool = typer.Option(False, "--write", "-w", help="Write scaffold to suggested test file."),
    json_out: bool = typer.Option(False, "--json", help="Output scaffold as JSON."),
) -> None:
    """Generate runnable unit test scaffold (pytest / vitest) based on symbol signature and semantics."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))
    cached = load_latest_graph(root)
    graph = RepoGraph.from_dict(cached) if cached else RepoGraph.build(ctx)
    scaffold = generate_test_scaffold(ctx, symbol, graph=graph)

    if write and scaffold.get("success"):
        target_path = root / scaffold["suggested_test_file"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and not typer.confirm(
            f"File {target_path} exists. Overwrite?", default=False
        ):
            console.print("[yellow]Skipping file write.[/yellow]")
        else:
            target_path.write_text(scaffold["test_code"], encoding="utf-8")
            console.print(f"[green]Wrote unit test scaffold to:[/green] {target_path}")

    if json_out:
        print(json.dumps(scaffold, indent=2))
    else:
        print_test_scaffold(scaffold)


@app.command("mermaid")
def cmd_mermaid(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository path."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write Mermaid chart to file (.mmd or .md)."
    ),
) -> None:
    """Export the repository's architecture flow as a Mermaid diagram."""
    root = path.resolve()
    ctx = RepoContext(root=root, config=load_config(root))
    cached = load_latest_graph(root)
    graph = RepoGraph.from_dict(cached) if cached else RepoGraph.build(ctx)
    chart = export_mermaid(graph)

    if output:
        output.write_text(chart, encoding="utf-8")
        console.print(f"[green]Exported Mermaid diagram to:[/green] {output}")
    else:
        print(chart)
