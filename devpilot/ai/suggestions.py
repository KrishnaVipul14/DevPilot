"""AI explanations and prioritized action plan generation (with deterministic fallback)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devpilot.ai.context_builder import build_finding_context
from devpilot.ai.prompts import (
    EXPLAIN_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    build_explain_user_prompt,
    build_plan_user_prompt,
)
from devpilot.ai.provider import AIProviderError, get_ai_provider
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.core.context import RepoContext
from devpilot.core.models import AIExplanation, Finding, Report
from devpilot.memory.database import MemoryDB


def _build_deterministic_explanation(
    ctx: RepoContext, finding: Finding, graph: RepoGraph | None = None
) -> AIExplanation:
    impact_desc = "May affect runtime correctness or operational stability."
    if finding.severity.value in ("critical", "high"):
        impact_desc = f"Critical risk: `{finding.rule}` can lead to production crashes, security bypass, or data leakage if triggered."
    elif finding.module == "dependencies":
        impact_desc = (
            "Vulnerable dependency contains publicly known CVEs and could be exploited by remote actors."
        )
    elif finding.module == "setup_doctor":
        impact_desc = (
            "Environment discrepancy can cause onboarding failure, deployment crashes, or leaked credentials."
        )

    tests: list[str] = []
    if finding.file:
        stem = Path(finding.file).stem
        if finding.file.endswith(".py"):
            tests.append(f"pytest tests/test_{stem}.py -v")
        elif finding.file.endswith((".js", ".ts", ".tsx", ".jsx")):
            tests.append(f"npm test -- {stem}")
    if not tests:
        tests.append("devpilot scan .")

    return AIExplanation(
        finding_fingerprint=finding.fingerprint,
        provider="deterministic-engine",
        model="offline",
        summary=f"Analysis of {finding.rule}: {finding.title}",
        root_cause=f"{finding.evidence}\n\nDetected at {finding.file}:{finding.line} by '{finding.module}' analyzer.",
        impact=impact_desc,
        recommendation=finding.suggestion
        or "Inspect the referenced line and apply the recommended fix pattern.",
        suggested_tests=tests,
        caveats="Deterministic offline explanation generated from AST & static analysis rules (configure an AI key in settings for conversational reasoning).",
    )


def explain_finding(
    ctx: RepoContext,
    finding: Finding,
    force: bool = False,
    graph: RepoGraph | None = None,
) -> AIExplanation:
    db = MemoryDB(ctx.root)
    if not force:
        cached = db.get_explanation(finding.fingerprint)
        if cached is not None:
            return cached

    provider = get_ai_provider(ctx.config)
    st = provider.status()
    if not st.available:
        return _build_deterministic_explanation(ctx, finding, graph)

    try:
        context = build_finding_context(ctx, finding, graph=graph)
        raw = provider.generate_json(
            EXPLAIN_SYSTEM_PROMPT,
            build_explain_user_prompt(context),
            timeout=ctx.config.ai.timeout,
        )
        tests = raw.get("suggested_tests")
        if not isinstance(tests, list):
            tests = [str(tests)] if tests else []

        explanation = AIExplanation(
            finding_fingerprint=finding.fingerprint,
            provider=provider.name,
            model=provider.model,
            summary=str(raw.get("summary") or finding.title).strip(),
            root_cause=str(raw.get("root_cause") or finding.evidence).strip(),
            impact=str(
                raw.get("impact") or "May affect code reliability, security, or maintainability."
            ).strip(),
            recommendation=str(raw.get("recommendation") or finding.suggestion).strip(),
            suggested_tests=[str(t) for t in tests if t],
            caveats=str(
                raw.get("caveats") or "Derived from static analysis and LLM reasoning; verify with tests."
            ).strip(),
        )
        db.save_explanation(explanation)
        return explanation
    except Exception:  # noqa: BLE001
        return _build_deterministic_explanation(ctx, finding, graph)


def _categorize_findings(findings: list[Finding]) -> list[tuple[str, str, str, list[Finding], str]]:
    buckets: list[tuple[str, str, str, list[Finding], str]] = []

    # 1. Critical / High Code Health
    runtime_bugs = [
        f for f in findings if f.module == "code_health" and f.severity.value in ("critical", "high")
    ]
    if runtime_bugs:
        buckets.append(
            (
                "Fix high-severity code defects and undefined names",
                "Undefined names (F821), syntax errors, and unsafe execution primitives can cause crashes or vulnerabilities.",
                "Resolve each undefined identifier or unsafe call reported by Ruff and run the test suite.",
                runtime_bugs,
                "small" if len(runtime_bugs) <= 3 else "medium",
            )
        )

    # 2. Vulnerable dependencies
    vuln_deps = [f for f in findings if f.module == "dependencies" and f.rule == "vulnerable-dependency"]
    if vuln_deps:
        pkgs = ", ".join(sorted({str(f.metadata.get("package") or f.title.split()[0]) for f in vuln_deps}))
        buckets.append(
            (
                f"Upgrade vulnerable dependencies ({pkgs})",
                "Known security advisories (CVEs/GHSAs) exist in pinned dependency versions.",
                "Update affected package versions in requirements.txt / pyproject.toml and run regression tests.",
                vuln_deps,
                "small",
            )
        )

    # 3. Secrets & configuration hygiene
    setup_issues = [f for f in findings if f.module == "setup_doctor"]
    if setup_issues:
        buckets.append(
            (
                "Align environment configuration and secret hygiene",
                "Missing `.env.example` entries or hardcoded credentials cause onboarding failures and secret leakage risks.",
                "Document all required environment variables in `.env.example` and move secrets to environment variables.",
                setup_issues,
                "small",
            )
        )

    # 4. Documentation drift
    doc_issues = [f for f in findings if f.module == "documentation"]
    if doc_issues:
        buckets.append(
            (
                "Synchronize README examples and docstrings with code signatures",
                "Outdated documentation examples mislead developers and cause copy-paste errors.",
                "Update README code blocks and function docstrings to match current function signatures.",
                doc_issues,
                "small",
            )
        )

    # 5. Remaining maintainability & cleanup
    cleanup_issues = [
        f for f in findings if f.module == "code_health" and f.severity.value not in ("critical", "high")
    ]
    if cleanup_issues:
        buckets.append(
            (
                "Clean up unused imports and maintainability warnings",
                "Unused imports and overly complex functions increase cognitive load and hide real bugs.",
                "Use `devpilot fix <ID>` to apply safe automated Ruff fixes and refactor complex functions.",
                cleanup_issues,
                "small" if len(cleanup_issues) <= 8 else "medium",
            )
        )

    return buckets


def build_deterministic_plan(
    ctx: RepoContext, report: Report, graph: RepoGraph | None = None
) -> dict[str, Any]:
    """Build a structured, prioritized engineering action plan without requiring an LLM."""
    graph = graph or RepoGraph.build(ctx)
    all_tests = [
        str(n.meta.get("nodeid") or f"{n.file}::{n.name}") for n in graph.nodes.values() if n.kind == "test"
    ]
    default_test_cmd = (
        f"pytest {' '.join(sorted({t.split('::')[0] for t in all_tests[:4]}))}" if all_tests else "pytest"
    )
    buckets = _categorize_findings(report.findings)

    tasks: list[dict[str, Any]] = []
    for idx, (title, why, resolution, group, effort) in enumerate(buckets, start=1):
        tasks.append(
            {
                "priority": idx,
                "title": title,
                "why": why,
                "resolution": resolution,
                "finding_ids": [f.id for f in group],
                "tests": [default_test_cmd],
                "effort": effort,
            }
        )

    summary = (
        f"Prioritized {len(report.findings)} finding(s) into {len(tasks)} actionable engineering task(s) "
        f"(Health score: {report.summary.health_score}/100)."
        if tasks
        else "No open findings detected. Repository passes all configured checks."
    )

    return {
        "source": "deterministic",
        "provider": None,
        "model": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scan_id": report.scan_id,
        "summary": summary,
        "tasks": tasks,
    }


def generate_plan(ctx: RepoContext, report: Report, prefer_ai: bool = True) -> dict[str, Any]:
    db = MemoryDB(ctx.root)
    provider = get_ai_provider(ctx.config)
    st = provider.status()

    if prefer_ai and st.available and report.findings:
        try:
            findings_payload = [
                {
                    "id": f.id,
                    "module": f.module,
                    "rule": f.rule,
                    "severity": f.severity.value,
                    "title": f.title,
                    "file": f.file,
                    "line": f.line,
                    "suggestion": f.suggestion,
                }
                for f in report.findings
            ]
            raw = provider.generate_json(
                PLAN_SYSTEM_PROMPT,
                build_plan_user_prompt(findings_payload, report.summary.model_dump()),
                timeout=ctx.config.ai.timeout,
            )
            raw_tasks = raw.get("tasks")
            if isinstance(raw_tasks, list) and raw_tasks:
                tasks = []
                for idx, t in enumerate(raw_tasks, start=1):
                    effort = str(t.get("effort", "small")).lower()
                    if effort not in ("small", "medium", "large"):
                        effort = "medium"
                    tasks.append(
                        {
                            "priority": int(t.get("priority") or idx),
                            "title": str(t.get("title") or f"Task {idx}"),
                            "why": str(t.get("why") or ""),
                            "resolution": str(t.get("resolution") or ""),
                            "finding_ids": [str(x) for x in (t.get("finding_ids") or [])],
                            "tests": [str(x) for x in (t.get("tests") or ["pytest"])],
                            "effort": effort,
                        }
                    )
                tasks.sort(key=lambda x: x["priority"])
                plan = {
                    "source": "ai",
                    "provider": provider.name,
                    "model": provider.model,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "scan_id": report.scan_id,
                    "summary": str(raw.get("summary") or f"AI-prioritized action plan ({len(tasks)} tasks)."),
                    "tasks": tasks,
                }
                db.save_plan(report.scan_id, plan)
                return plan
        except AIProviderError:
            pass

    plan = build_deterministic_plan(ctx, report)
    db.save_plan(report.scan_id, plan)
    return plan
