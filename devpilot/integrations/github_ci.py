"""GitHub Actions integration: PR annotations and Markdown Job Summary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from devpilot.core.models import Finding, Report, Severity

_ANNOTATION_LEVEL: dict[Severity, str] = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def format_github_annotation(f: Finding) -> str:
    level = _ANNOTATION_LEVEL.get(f.severity, "notice")
    props: list[str] = [f"title={_escape_prop(f'[{f.id}] {f.title} ({f.module})')}"]
    if f.file:
        props.append(f"file={_escape_prop(f.file)}")
    if f.line:
        props.append(f"line={f.line}")
    if f.end_line:
        props.append(f"endLine={f.end_line}")
    if f.column:
        props.append(f"col={f.column}")
    msg = f"{f.evidence.splitlines()[0]} — Suggestion: {f.suggestion}"
    return f"::{level} {','.join(props)}::{_escape_data(msg)}"


def format_markdown_summary(report: Report, impact: dict[str, Any] | None = None) -> str:
    s = report.summary
    sev = s.by_severity
    lines = [
        f"## DevPilot Repository Intelligence Report — `{report.repository.name}`",
        "",
        f"**Health Score:** `{s.health_score}/100` (`{s.health_formula}`) | "
        f"**Total Findings:** `{s.total}` | **Status:** `{report.status.value.upper()}`",
        "",
        "| Critical | High | Medium | Low | Info |",
        "| :---: | :---: | :---: | :---: | :---: |",
        f"| {sev.get('critical', 0)} | {sev.get('high', 0)} | {sev.get('medium', 0)} | "
        f"{sev.get('low', 0)} | {sev.get('info', 0)} |",
        "",
    ]

    if impact and impact.get("changed_files"):
        risk = impact.get("overall_risk", {})
        lines.extend([
            "### Change Impact Analysis",
            f"- **Estimated Risk:** `{str(risk.get('level', 'low')).upper()}`",
            f"- **Modified Files:** `{len(impact['changed_files'])}`",
            f"- **Modified Symbols:** `{len(impact.get('changed_symbols', []))}`",
        ])
        for reason in risk.get("reasons", []):
            lines.append(f"  - {reason}")
        if impact.get("suggested_commands"):
            lines.append(f"- **Suggested Verification:** `{impact['suggested_commands'][0]}`")
        lines.append("")

    if report.findings:
        lines.extend([
            "### Top Findings",
            "",
            "| ID | Severity | Module | Location | Title | Suggestion |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for f in report.findings[:25]:
            loc = f"`{f.file}:{f.line}`" if (f.file and f.line) else (f"`{f.file}`" if f.file else "—")
            lines.append(
                f"| `{f.id}` | **{f.severity.value.upper()}** | `{f.module}` | {loc} | "
                f"{f.title} | {f.suggestion} |"
            )
        lines.append("")
    else:
        lines.append("_No findings detected._\n")

    return "\n".join(lines)


def write_github_step_summary(markdown: str) -> Path | None:
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_file:
        return None
    path = Path(summary_file)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(markdown + "\n")
    return path
