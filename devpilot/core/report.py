"""Report serialization, loading, and summary calculation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devpilot.core.config import state_dir
from devpilot.core.models import Finding, Report, Severity, Summary, VerificationStatus
from devpilot.memory.database import MemoryDB

HEALTH_FORMULA = "max(0, 100 - (25*critical + 12*high + 5*medium + 2*low))"

SEVERITY_PENALTY: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 12,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
    Severity.INFO: 0,
}


def compute_summary(findings: list[Finding], files_scanned: int) -> Summary:
    by_sev: dict[str, int] = {s.value: 0 for s in Severity}
    by_mod: dict[str, int] = {}
    penalty = 0
    for f in findings:
        by_sev[f.severity.value] = by_sev.get(f.severity.value, 0) + 1
        by_mod[f.module] = by_mod.get(f.module, 0) + 1
        penalty += SEVERITY_PENALTY.get(f.severity, 0)
    score = max(0, 100 - penalty)
    return Summary(
        total=len(findings),
        by_severity=by_sev,
        by_module=by_mod,
        health_score=score,
        health_formula=HEALTH_FORMULA,
        files_scanned=files_scanned,
    )


def reports_dir(root: Path) -> Path:
    d = state_dir(root) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def latest_report_path(root: Path) -> Path:
    return reports_dir(root) / "latest.json"


def latest_graph_path(root: Path) -> Path:
    return reports_dir(root) / "graph.json"


def save_report(root: Path, report: Report, graph_dict: dict[str, Any] | None = None) -> Path:
    rdir = reports_dir(root)
    latest = rdir / "latest.json"
    archive = rdir / f"scan-{report.scan_id}.json"
    payload = report.model_dump_json(indent=2)
    latest.write_text(payload, encoding="utf-8")
    archive.write_text(payload, encoding="utf-8")
    if graph_dict is not None:
        (rdir / "graph.json").write_text(json.dumps(graph_dict, indent=2), encoding="utf-8")
    return latest


def load_latest_report(root: Path, refresh_from_memory: bool = True) -> Report | None:
    path = latest_report_path(root)
    if not path.is_file():
        return None
    report = Report.model_validate_json(path.read_text(encoding="utf-8"))
    if refresh_from_memory:
        db = MemoryDB(root)
        report.ai = db.get_all_explanations()
        ver_by_fp: dict[str, str] = {}
        for p in db.list_patches():
            if p["status"] in ("verified", "partially_verified", "failed", "applied"):
                ver_by_fp[p["fingerprint"]] = "verified" if p["status"] == "applied" else p["status"]
        for f in report.findings:
            if f.fingerprint in ver_by_fp:
                try:
                    f.verification = VerificationStatus(ver_by_fp[f.fingerprint])
                except ValueError:
                    pass
    return report


def load_latest_graph(root: Path) -> dict[str, Any] | None:
    path = latest_graph_path(root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_finding(report: Report, ref: str) -> Finding | None:
    ref_upper = ref.strip().upper()
    for f in report.findings:
        if f.id.upper() == ref_upper or f.fingerprint == ref.strip():
            return f
    return None
