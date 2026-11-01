"""Core repository scanner orchestrator."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from devpilot import __version__
from devpilot.analyzers.base import Analyzer, AnalyzerSkipped
from devpilot.analyzers.repository_graph import GRAPH_LIMITATIONS, RepoGraph
from devpilot.core.config import DevPilotConfig, load_config
from devpilot.core.context import RepoContext
from devpilot.core.models import (
    AnalyzerRun,
    AnalyzerState,
    Finding,
    GraphSummary,
    Report,
    RepositoryInfo,
    ScanStatus,
    utcnow,
)
from devpilot.core.registry import default_analyzers
from devpilot.core.report import compute_summary, save_report
from devpilot.memory.database import MemoryDB
from devpilot.memory.fingerprints import assign_fingerprints
from devpilot.utils import git as gitutil

SCAN_LIMITATIONS = [
    "Static analysis identifies known patterns and AST/linter rules; it cannot prove the absence of runtime bugs.",
    "Dependency vulnerability checks require pinned versions (==) or lock files and advisory coverage in OSV.dev.",
    "Secret scanning uses pattern and variable-name heuristics; actual secret values are never stored or transmitted.",
    *GRAPH_LIMITATIONS,
]


def _compute_tree_hash(ctx: RepoContext) -> str:
    import hashlib

    h = hashlib.sha256()
    for rel in sorted(ctx.files)[:200]:
        h.update(rel.encode("utf-8"))
        text = ctx.read_text(rel)
        if text is not None:
            h.update(text[:1000].encode("utf-8", errors="replace"))
    return h.hexdigest()[:12]


def run_scan(
    root: Path,
    config: DevPilotConfig | None = None,
    offline: bool = False,
    analyzers: list[Analyzer] | None = None,
    persist: bool = True,
) -> Report:
    root = root.resolve()
    cfg = config or load_config(root)
    ctx = RepoContext(root=root, config=cfg, offline=offline)
    started = utcnow()
    scan_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    all_findings: list[Finding] = []
    all_anchors: list[str] = []
    runs: list[AnalyzerRun] = []

    for analyzer in analyzers or default_analyzers():
        t0 = time.monotonic()
        if not analyzer.enabled(ctx):
            runs.append(
                AnalyzerRun(
                    name=analyzer.name,
                    status=AnalyzerState.SKIPPED,
                    duration_ms=0,
                    message="Disabled in devpilot.yml",
                )
            )
            continue
        try:
            out = analyzer.run(ctx)
            dur = int((time.monotonic() - t0) * 1000)
            all_findings.extend(out.findings)
            all_anchors.extend(out.anchors)
            runs.append(
                AnalyzerRun(
                    name=analyzer.name,
                    status=AnalyzerState.OK,
                    duration_ms=dur,
                    findings=len(out.findings),
                    message=out.message,
                )
            )
        except AnalyzerSkipped as exc:
            dur = int((time.monotonic() - t0) * 1000)
            runs.append(
                AnalyzerRun(
                    name=analyzer.name,
                    status=AnalyzerState.SKIPPED,
                    duration_ms=dur,
                    message=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            dur = int((time.monotonic() - t0) * 1000)
            runs.append(
                AnalyzerRun(
                    name=analyzer.name,
                    status=AnalyzerState.ERROR,
                    duration_ms=dur,
                    message=str(exc),
                )
            )

    assign_fingerprints(all_findings, all_anchors)
    all_findings.sort(key=lambda f: (f.severity.rank, f.file or "", f.line or 0, f.rule, f.fingerprint))
    for idx, f in enumerate(all_findings, start=1):
        f.id = f"DP{idx:03d}"

    graph = RepoGraph.build(ctx)
    graph_dict = graph.to_dict()
    graph_summary = GraphSummary(**graph.summary())

    summary = compute_summary(all_findings, len(ctx.files))

    any_err = any(r.status == AnalyzerState.ERROR for r in runs)
    any_ok = any(r.status == AnalyzerState.OK for r in runs)
    status = (
        ScanStatus.FAILED
        if (any_err and not any_ok)
        else ScanStatus.PARTIAL
        if any_err
        else ScanStatus.COMPLETED
    )

    git_root_path = ctx.git_root
    head_c = gitutil.head_commit(root) if git_root_path else None
    repo_info = RepositoryInfo(
        name=root.name,
        path=str(root),
        git_root=str(git_root_path) if git_root_path else None,
        commit=head_c if head_c else f"tree-{_compute_tree_hash(ctx)}",
        branch=gitutil.current_branch(root) if git_root_path else None,
        dirty=gitutil.is_dirty(root) if git_root_path else None,
    )

    finished = utcnow()
    report = Report(
        version=__version__,
        scan_id=scan_id,
        repository=repo_info,
        started_at=started,
        finished_at=finished,
        status=status,
        summary=summary,
        findings=all_findings,
        analyzers=runs,
        graph=graph_summary,
        limitations=list(SCAN_LIMITATIONS),
    )

    if persist:
        db = MemoryDB(root)
        report.memory = db.classify_and_record(report)
        report.ai = db.get_all_explanations()
        save_report(root, report, graph_dict=graph_dict)

    return report
