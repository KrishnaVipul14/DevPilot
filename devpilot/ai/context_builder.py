"""Safe AI context builder.

Extracts only relevant code snippets, finding metadata, and graph relationships.
Never reads `.env` or secret files, and runs secret redaction over all snippets
before returning them.
"""

from __future__ import annotations

from typing import Any

from devpilot.analyzers.change_impact import analyze_symbol_impact
from devpilot.analyzers.envsecrets import redact_text
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.core.context import RepoContext, is_sensitive_file
from devpilot.core.models import Finding


def build_finding_context(
    ctx: RepoContext,
    finding: Finding,
    graph: RepoGraph | None = None,
    window: int = 25,
) -> dict[str, Any]:
    snippet = ""
    full_file_redacted = ""
    if finding.file and not is_sensitive_file(finding.file):
        text = ctx.read_text(finding.file) or ""
        if text:
            redacted = redact_text(text)
            lines = redacted.splitlines()
            center = finding.line or 1
            start = max(1, center - window)
            end = min(len(lines), (finding.end_line or center) + window)
            numbered = [f"{ln:4d} | {lines[ln - 1]}" for ln in range(start, end + 1)]
            snippet = "\n".join(numbered)
            full_file_redacted = redacted[: ctx.config.ai.max_context_chars]

    impact_summary: dict[str, Any] = {}
    if finding.symbol:
        graph = graph or RepoGraph.build(ctx)
        imp = analyze_symbol_impact(ctx, finding.symbol, graph=graph)
        if imp["impacts"]:
            first = imp["impacts"][0]
            impact_summary = {
                "symbol": first["symbol"],
                "callers": first["callers"][:10],
                "dependent_modules": first["dependent_modules"][:10],
                "routes": first["routes"][:5],
                "tests": [t.get("nodeid", "") for t in first["tests"][:10] if isinstance(t, dict) and t.get("nodeid")],
                "risk": first["risk"],
            }

    return {
        "finding": {
            "id": finding.id,
            "module": finding.module,
            "rule": finding.rule,
            "severity": finding.severity.value,
            "title": finding.title,
            "file": finding.file,
            "line": finding.line,
            "symbol": finding.symbol,
            "evidence": redact_text(finding.evidence),
            "suggestion": finding.suggestion,
        },
        "code_snippet": snippet[: ctx.config.ai.max_context_chars // 2],
        "file_content": full_file_redacted,
        "impact": impact_summary,
    }
