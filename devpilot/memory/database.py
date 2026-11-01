"""SQLite persistence for repository scan history, finding lifecycles, AI cache, and patches."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from devpilot.core.config import state_dir
from devpilot.core.models import (
    AIExplanation,
    FindingStatus,
    MemoryDelta,
    Report,
    VerificationStatus,
)

DB_FILENAME = "devpilot.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    commit_hash TEXT,
    branch TEXT,
    status TEXT NOT NULL,
    total INTEGER NOT NULL,
    health_score INTEGER NOT NULL,
    by_severity_json TEXT NOT NULL,
    new_count INTEGER NOT NULL DEFAULT 0,
    existing_count INTEGER NOT NULL DEFAULT 0,
    resolved_count INTEGER NOT NULL DEFAULT 0,
    reintroduced_count INTEGER NOT NULL DEFAULT 0,
    severity_changed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS finding_sightings (
    scan_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    module TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    file TEXT,
    line INTEGER,
    status TEXT NOT NULL,
    PRIMARY KEY (scan_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_sightings_fp ON finding_sightings(fingerprint);

CREATE TABLE IF NOT EXISTS ai_explanations (
    fingerprint TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patches (
    patch_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    engine TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    diff TEXT NOT NULL,
    files_json TEXT NOT NULL,
    edits_json TEXT NOT NULL,
    file_hashes_json TEXT NOT NULL,
    verification_json TEXT
);
"""


class MemoryDB:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = state_dir(root) / DB_FILENAME
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _get_verification_map(self, conn: sqlite3.Connection) -> dict[str, str]:
        ver_map: dict[str, str] = {}
        for r in conn.execute("SELECT fingerprint, status FROM patches ORDER BY created_at ASC"):
            if r["status"] in ("verified", "partially_verified", "failed", "applied"):
                ver_map[r["fingerprint"]] = "verified" if r["status"] == "applied" else r["status"]
        return ver_map

    def _persist_scan_and_sightings(
        self, conn: sqlite3.Connection, report: Report, delta: MemoryDelta
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO scans (
                scan_id, started_at, finished_at, commit_hash, branch, status,
                total, health_score, by_severity_json,
                new_count, existing_count, resolved_count, reintroduced_count, severity_changed_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.scan_id,
                report.started_at.isoformat(),
                report.finished_at.isoformat(),
                report.repository.commit,
                report.repository.branch,
                report.status.value,
                report.summary.total,
                report.summary.health_score,
                json.dumps(report.summary.by_severity),
                delta.new,
                delta.existing,
                delta.resolved,
                delta.reintroduced,
                delta.severity_changed,
            ),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO finding_sightings (
                scan_id, fingerprint, finding_id, module, rule, severity, title, file, line, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    report.scan_id,
                    f.fingerprint,
                    f.id,
                    f.module,
                    f.rule,
                    f.severity.value,
                    f.title,
                    f.file,
                    f.line,
                    f.status.value,
                )
                for f in report.findings
            ],
        )

    def classify_and_record(self, report: Report) -> MemoryDelta:
        """Compare `report.findings` against previous scans, set `finding.status` and
        `finding.verification`, persist the scan, and return the `MemoryDelta`."""
        with self._connect() as conn:
            prev_row = conn.execute("SELECT scan_id FROM scans ORDER BY finished_at DESC LIMIT 1").fetchone()
            prev_scan_id: str | None = prev_row["scan_id"] if prev_row else None

            prev_fps: dict[str, sqlite3.Row] = {}
            if prev_scan_id:
                for r in conn.execute("SELECT * FROM finding_sightings WHERE scan_id = ?", (prev_scan_id,)):
                    prev_fps[r["fingerprint"]] = r

            ever_seen: set[str] = {
                r["fingerprint"] for r in conn.execute("SELECT DISTINCT fingerprint FROM finding_sightings")
            }
            ver_map = self._get_verification_map(conn)
            new_c = existing_c = reintro_c = sev_changed_c = 0
            current_fps: set[str] = set()

            for f in report.findings:
                current_fps.add(f.fingerprint)
                if f.fingerprint in ver_map:
                    try:
                        f.verification = VerificationStatus(ver_map[f.fingerprint])
                    except ValueError:
                        pass

                if prev_scan_id is None:
                    f.status = FindingStatus.NEW
                    new_c += 1
                elif f.fingerprint in prev_fps:
                    f.status = FindingStatus.EXISTING
                    existing_c += 1
                    if prev_fps[f.fingerprint]["severity"] != f.severity.value:
                        sev_changed_c += 1
                elif f.fingerprint in ever_seen:
                    f.status = FindingStatus.REINTRODUCED
                    reintro_c += 1
                else:
                    f.status = FindingStatus.NEW
                    new_c += 1

            resolved_list = [
                {
                    "fingerprint": fp,
                    "id": row["finding_id"],
                    "module": row["module"],
                    "rule": row["rule"],
                    "severity": row["severity"],
                    "title": row["title"],
                    "file": row["file"],
                    "line": row["line"],
                }
                for fp, row in prev_fps.items()
                if fp not in current_fps
            ]

            delta = MemoryDelta(
                previous_scan_id=prev_scan_id,
                new=new_c,
                existing=existing_c,
                reintroduced=reintro_c,
                resolved=len(resolved_list),
                severity_changed=sev_changed_c,
                resolved_findings=resolved_list,
            )
            self._persist_scan_and_sightings(conn, report, delta)
            return delta

    def save_explanation(self, exp: AIExplanation) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ai_explanations (fingerprint, provider, model, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    exp.finding_fingerprint,
                    exp.provider,
                    exp.model,
                    exp.created_at.isoformat(),
                    exp.model_dump_json(),
                ),
            )

    def get_explanation(self, fingerprint: str) -> AIExplanation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ai_explanations WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            return AIExplanation.model_validate_json(row["payload_json"]) if row else None

    def get_all_explanations(self) -> dict[str, AIExplanation]:
        out: dict[str, AIExplanation] = {}
        with self._connect() as conn:
            for row in conn.execute("SELECT fingerprint, payload_json FROM ai_explanations"):
                try:
                    out[row["fingerprint"]] = AIExplanation.model_validate_json(row["payload_json"])
                except Exception:  # noqa: BLE001
                    pass
        return out

    def save_plan(self, scan_id: str, plan: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plans (scan_id, created_at, payload_json) VALUES (?, ?, ?)",
                (scan_id, plan["created_at"], json.dumps(plan)),
            )

    def get_latest_plan(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM plans ORDER BY id DESC LIMIT 1").fetchone()
            return json.loads(row["payload_json"]) if row else None

    def save_patch(self, patch: dict[str, Any], edits: dict[str, str], file_hashes: dict[str, str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO patches (
                    patch_id, finding_id, fingerprint, title, engine, summary, status,
                    created_at, diff, files_json, edits_json, file_hashes_json, verification_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patch["patch_id"],
                    patch["finding_id"],
                    patch["fingerprint"],
                    patch["title"],
                    patch["engine"],
                    patch["summary"],
                    patch["status"],
                    patch["created_at"],
                    patch["diff"],
                    json.dumps(patch["files"]),
                    json.dumps(edits),
                    json.dumps(file_hashes),
                    json.dumps(patch["verification"]) if patch.get("verification") else None,
                ),
            )

    def get_patch_record(self, patch_id: str) -> tuple[dict[str, Any], dict[str, str], dict[str, str]] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM patches WHERE patch_id = ?", (patch_id,)).fetchone()
            if not row:
                return None
            return self._row_to_patch(row), json.loads(row["edits_json"]), json.loads(row["file_hashes_json"])

    def find_patch_for_ref(self, ref: str) -> tuple[dict[str, Any], dict[str, str], dict[str, str]] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM patches WHERE patch_id = ? OR finding_id = ? OR fingerprint = ? ORDER BY created_at DESC LIMIT 1",
                (ref, ref, ref),
            ).fetchone()
            if not row:
                return None
            return self._row_to_patch(row), json.loads(row["edits_json"]), json.loads(row["file_hashes_json"])

    def list_patches(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM patches ORDER BY created_at DESC").fetchall()
            return [self._row_to_patch(r) for r in rows]

    @staticmethod
    def _row_to_patch(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "patch_id": row["patch_id"],
            "finding_id": row["finding_id"],
            "fingerprint": row["fingerprint"],
            "title": row["title"],
            "engine": row["engine"],
            "summary": row["summary"],
            "status": row["status"],
            "created_at": row["created_at"],
            "diff": row["diff"],
            "files": json.loads(row["files_json"]),
            "verification": json.loads(row["verification_json"]) if row["verification_json"] else None,
        }

    def get_history(self) -> dict[str, Any]:
        with self._connect() as conn:
            scans = []
            for r in conn.execute("SELECT * FROM scans ORDER BY finished_at DESC LIMIT 50"):
                scans.append(
                    {
                        "scan_id": r["scan_id"],
                        "started_at": r["started_at"],
                        "finished_at": r["finished_at"],
                        "commit": r["commit_hash"],
                        "branch": r["branch"],
                        "status": r["status"],
                        "total": r["total"],
                        "health_score": r["health_score"],
                        "by_severity": json.loads(r["by_severity_json"]),
                        "new": r["new_count"],
                        "existing": r["existing_count"],
                        "resolved": r["resolved_count"],
                        "reintroduced": r["reintroduced_count"],
                    }
                )
            verifications = []
            for r in conn.execute(
                "SELECT * FROM patches WHERE verification_json IS NOT NULL ORDER BY created_at DESC LIMIT 50"
            ):
                ver = json.loads(r["verification_json"])
                verifications.append(
                    {
                        "patch_id": r["patch_id"],
                        "finding_id": r["finding_id"],
                        "fingerprint": r["fingerprint"],
                        "title": r["title"],
                        "status": ver.get("status", r["status"]),
                        "created_at": ver.get("finished_at") or r["created_at"],
                        "checks": ver.get("checks", []),
                    }
                )
            return {"scans": scans, "verifications": verifications}
