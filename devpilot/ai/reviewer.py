"""AI-driven and AST-grounded automated PR reviewer and PR description generator."""

from __future__ import annotations

from typing import Any

from devpilot.ai.provider import get_ai_provider
from devpilot.analyzers.change_impact import analyze_git_impact
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.core.context import RepoContext
from devpilot.utils import git as gitutil

REVIEW_SYSTEM_PROMPT = """You are DevPilot Automated Staff Engineer Code Reviewer.
Your role is to conduct a thorough, constructive, and actionable code review of the given changes.

CRITICAL REVIEW GUIDELINES:
1. Architecture & Impact: Highlight routes or downstream callers that could be broken.
2. Security & Edge Cases: Flag injection, unsanitized inputs, missing null/None guards, or concurrency issues.
3. Test Coverage: Recommend specific test scenarios for new or modified branches.
4. Keep the feedback concise, prioritized, and professional.

Return a JSON object matching this schema:
{
  "verdict": "APPROVE" | "REQUEST_CHANGES" | "COMMENT",
  "summary": "High-level review summary",
  "key_strengths": ["Item 1", "Item 2"],
  "critical_risks": ["Risk 1", "Risk 2"],
  "actionable_suggestions": ["Suggestion 1", "Suggestion 2"],
  "markdown_review": "Full formatted markdown review comment ready for GitHub PR"
}
"""

PR_SYSTEM_PROMPT = """You are DevPilot PR Assistant. Generate a comprehensive, professional Pull Request description based on the Git diff and affected architecture.

Return a JSON object matching this schema:
{
  "title": "Clear conventional commit style PR title",
  "summary": "1-2 sentence executive summary",
  "changes": ["Change 1", "Change 2"],
  "impact": "Affected components, routes, or callers",
  "testing_plan": ["pytest command or test scenario 1", "Scenario 2"],
  "markdown_pr": "Complete markdown PR description ready for GitHub PR body"
}
"""


def _get_diff_text(ctx: RepoContext, base: str = "HEAD") -> str:
    diff_res = gitutil.git(["diff", "-u", base], ctx.root)
    text = diff_res.stdout if diff_res.ok else ""
    if not text.strip() and base == "HEAD":
        prev = gitutil.git(["diff", "-u", "HEAD~1", "HEAD"], ctx.root)
        if prev.ok:
            text = prev.stdout
    return text[:8000]


def review_changes(ctx: RepoContext, base: str = "HEAD", graph: RepoGraph | None = None) -> dict[str, Any]:
    """Perform automated staff-engineer code review on git changes."""
    diff_text = _get_diff_text(ctx, base)
    impact = analyze_git_impact(ctx, base=base, graph=graph)
    changed_files = [f["path"] for f in impact.get("changed_files", [])]

    if not diff_text.strip() and not changed_files:
        return {
            "verdict": "APPROVE",
            "summary": "No changes detected in working tree against base ref.",
            "key_strengths": ["Working directory is clean"],
            "critical_risks": [],
            "actionable_suggestions": [],
            "markdown_review": "### ✅ DevPilot Code Review\n\nNo uncommitted or changed code detected.",
            "provider": "deterministic",
        }

    provider = get_ai_provider(ctx.config)
    st = provider.status()

    # High-quality deterministic fallback review
    risk_level = impact.get("overall_risk", {}).get("level", "low").upper()
    impact_items = [
        f"- **{i['symbol']}**: {len(i.get('callers', []))} caller(s)" for i in impact.get("impacts", [])[:5]
    ]
    suggested_cmds = impact.get("suggested_commands", ["pytest"])

    det_md = f"""### 🔍 DevPilot Automated Code Review

**Review Verdict:** `{"COMMENT" if risk_level == "LOW" else "REQUEST_CHANGES"}` · **Blast Radius Risk:** `{risk_level}`

#### 📂 Files Modified ({len(changed_files)})
{chr(10).join(f"- `{f}`" for f in changed_files[:10])}

#### ⚡ Architecture Impact
{chr(10).join(impact_items) if impact_items else "- No public symbol signatures modified."}

#### 🧪 Verification Test Plan
Run the following targeted test suites before merging:
```bash
{chr(10).join(suggested_cmds)}
```
"""

    if not st.available:
        return {
            "verdict": "COMMENT" if risk_level == "LOW" else "REQUEST_CHANGES",
            "summary": f"Analyzed {len(changed_files)} changed file(s). Blast radius risk: {risk_level}.",
            "key_strengths": ["Static call graph mapped"],
            "critical_risks": [r for r in impact.get("overall_risk", {}).get("reasons", [])],
            "actionable_suggestions": [f"Run targeted tests: `{cmd}`" for cmd in suggested_cmds],
            "markdown_review": det_md.strip(),
            "provider": "deterministic-engine",
        }

    user_prompt = f"""Target Base: {base}
Changed Files: {", ".join(changed_files)}
Impact Summary: Risk {risk_level}, {len(impact.get("impacts", []))} affected symbols.

<git_diff>
{diff_text}
</git_diff>
"""
    try:
        raw = provider.generate_json(
            REVIEW_SYSTEM_PROMPT,
            user_prompt,
            timeout=ctx.config.ai.timeout,
        )
        return {
            "verdict": str(raw.get("verdict") or "COMMENT"),
            "summary": str(raw.get("summary") or f"Reviewed {len(changed_files)} changed files."),
            "key_strengths": [str(x) for x in (raw.get("key_strengths") or [])],
            "critical_risks": [str(x) for x in (raw.get("critical_risks") or [])],
            "actionable_suggestions": [str(x) for x in (raw.get("actionable_suggestions") or [])],
            "markdown_review": str(raw.get("markdown_review") or det_md),
            "provider": provider.name,
            "model": provider.model,
        }
    except Exception:  # noqa: BLE001
        return {
            "verdict": "COMMENT",
            "summary": f"Reviewed {len(changed_files)} files (deterministic engine).",
            "key_strengths": ["AST impact verified"],
            "critical_risks": [],
            "actionable_suggestions": [f"Execute `{c}`" for c in suggested_cmds],
            "markdown_review": det_md.strip(),
            "provider": "deterministic-engine",
        }


def generate_pr_description(
    ctx: RepoContext, base: str = "HEAD", graph: RepoGraph | None = None
) -> dict[str, Any]:
    """Generate structured Pull Request description from Git diff and AST impact."""
    diff_text = _get_diff_text(ctx, base)
    impact = analyze_git_impact(ctx, base=base, graph=graph)
    changed_files = [f["path"] for f in impact.get("changed_files", [])]
    cmds = impact.get("suggested_commands", ["pytest"])

    default_title = f"feat: update {len(changed_files)} file(s)"
    default_summary = f"Includes updates across {len(changed_files)} repository file(s)."
    default_md = f"""## 🚀 Pull Request Overview

**Summary:** {default_summary}

### 📝 Key Changes
{chr(10).join(f"- `{f}`" for f in changed_files[:10])}

### 🧪 Testing Plan
```bash
{chr(10).join(cmds)}
```
"""

    provider = get_ai_provider(ctx.config)
    st = provider.status()

    if not st.available or not diff_text.strip():
        return {
            "title": default_title,
            "summary": default_summary,
            "changes": changed_files,
            "impact": f"Risk level: {impact.get('overall_risk', {}).get('level', 'low')}",
            "testing_plan": cmds,
            "markdown_pr": default_md.strip(),
            "provider": "deterministic-engine",
        }

    user_prompt = f"""Changed Files: {", ".join(changed_files)}
Impact: {impact.get("overall_risk", {}).get("level", "low")} risk.

<git_diff>
{diff_text}
</git_diff>
"""
    try:
        raw = provider.generate_json(
            PR_SYSTEM_PROMPT,
            user_prompt,
            timeout=ctx.config.ai.timeout,
        )
        return {
            "title": str(raw.get("title") or default_title),
            "summary": str(raw.get("summary") or default_summary),
            "changes": [str(x) for x in (raw.get("changes") or changed_files)],
            "impact": str(raw.get("impact") or "Core services"),
            "testing_plan": [str(x) for x in (raw.get("testing_plan") or cmds)],
            "markdown_pr": str(raw.get("markdown_pr") or default_md),
            "provider": provider.name,
            "model": provider.model,
        }
    except Exception:  # noqa: BLE001
        return {
            "title": default_title,
            "summary": default_summary,
            "changes": changed_files,
            "impact": "Deterministic engine",
            "testing_plan": cmds,
            "markdown_pr": default_md.strip(),
            "provider": "deterministic-engine",
        }
