"""Dependency security analyzer.

Known vulnerabilities are looked up in OSV.dev (default) or via pip-audit for
dependencies whose exact version is known (pinned with ``==`` or from a lock
file). Vulnerabilities are reported separately from (optional) "outdated"
information - an old version is not necessarily a vulnerable one.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from devpilot.analyzers.base import Analyzer, AnalyzerOutput, AnalyzerSkipped
from devpilot.analyzers.manifests import Dependency, discover_dependencies, normalize_name
from devpilot.analyzers.osv import OSVError, cvss3_base_score, get_vulns, query_batch, score_to_label
from devpilot.core.context import RepoContext
from devpilot.core.models import Confidence, Finding, Severity
from devpilot.utils.proc import run

_LABELS = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "MEDIUM": "medium", "LOW": "low"}


def vuln_severity(vuln: dict) -> tuple[Severity, str, Confidence]:
    """Return (severity, source description, confidence)."""
    db_sev = str((vuln.get("database_specific") or {}).get("severity") or "").upper()
    if db_sev in _LABELS:
        return Severity(_LABELS[db_sev]), f"advisory severity {db_sev}", Confidence.HIGH
    for sev in vuln.get("severity", []) or []:
        if str(sev.get("type", "")).startswith("CVSS_V3"):
            score = cvss3_base_score(str(sev.get("score", "")))
            if score is not None:
                return Severity(score_to_label(score)), f"CVSS v3 base score {score}", Confidence.HIGH
    return Severity.MEDIUM, "severity not published; defaulted to medium", Confidence.MEDIUM


def fixed_versions(vuln: dict, package: str, ecosystem: str = "PyPI") -> list[str]:
    fixed: list[str] = []
    for affected in vuln.get("affected", []) or []:
        pkg = affected.get("package") or {}
        aff_eco = str(pkg.get("ecosystem", "")).lower()
        if aff_eco != ecosystem.lower():
            continue
        aff_name = str(pkg.get("name", ""))
        if ecosystem.lower() == "pypi":
            if normalize_name(aff_name) != package:
                continue
        elif aff_name.lower() != package.lower():
            continue
        for rng in affected.get("ranges", []) or []:
            for event in rng.get("events", []) or []:
                if "fixed" in event and event["fixed"] not in fixed:
                    fixed.append(event["fixed"])
    return fixed


def dedupe_vulns(ids: list[str], details: dict[str, dict]) -> list[dict]:
    """Merge records that alias each other (e.g. PYSEC-x and GHSA-y for one CVE)."""
    groups: list[tuple[set[str], dict]] = []
    for vid in ids:
        data = details.get(vid) or {"id": vid}
        keys = {vid, *(data.get("aliases") or [])}
        for group in groups:
            if group[0] & keys:
                group[0].update(keys)
                # prefer records that carry a severity (typically GHSA)
                if "severity" not in group[1] and ("severity" in data or "database_specific" in data):
                    group[1].clear()
                    group[1].update(data)
                break
        else:
            groups.append((keys, dict(data)))
    merged = []
    for keys, data in groups:
        data = dict(data)
        data["_all_ids"] = sorted(keys)
        merged.append(data)
    return merged


def _version_tuple(v: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(\.\d+)*", v):
        return None
    return tuple(int(x) for x in v.split("."))


class DependencyAnalyzer(Analyzer):
    name = "dependencies"
    description = "Known-vulnerable dependency versions (OSV.dev / pip-audit)"
    requires_network = True

    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        deps = discover_dependencies(ctx)
        if not deps:
            raise AnalyzerSkipped("No supported dependency manifests found")
        out = AnalyzerOutput()
        self._unpinned(deps, out)
        pinned = [d for d in deps if d.pinned]
        if ctx.offline:
            out.message = f"Offline mode: {len(pinned)} pinned dependencies were not audited"
            return out
        cfg = ctx.config.analyzers.dependencies
        unique = sorted({(d.name, d.version or "", d.ecosystem) for d in pinned})
        if cfg.engine == "pip-audit":
            pypi_unique = [(n, v) for n, v, eco in unique if eco.lower() == "pypi"]
            vuln_ids = self._pip_audit_ids(ctx, pypi_unique, cfg.timeout)
        else:
            try:
                vuln_ids = dict(zip(unique, query_batch(unique, timeout=cfg.timeout), strict=False))
            except OSVError as exc:
                raise RuntimeError(
                    f"Could not reach OSV.dev ({exc}). Re-run later or use --offline."
                ) from exc
        all_ids = [vid for ids in vuln_ids.values() for vid in ids]
        details = get_vulns(all_ids, timeout=cfg.timeout) if all_ids else {}
        for dep in pinned:
            for vuln in dedupe_vulns(vuln_ids.get((dep.name, dep.version or "", dep.ecosystem), []), details):
                self._vuln_finding(dep, vuln, out)
        if cfg.check_outdated:
            self._outdated(pinned, out, cfg.timeout)
        out.message = (
            f"{len(deps)} dependencies parsed, {len(unique)} pinned versions audited via {cfg.engine}"
        )
        return out

    def _unpinned(self, deps: list[Dependency], out: AnalyzerOutput) -> None:
        by_manifest: dict[str, list[Dependency]] = {}
        for d in deps:
            if not d.pinned and not d.manifest.endswith(".lock"):
                by_manifest.setdefault(d.manifest, []).append(d)
        for manifest, items in by_manifest.items():
            if manifest.endswith("pyproject.toml"):
                continue  # ranges are normal for libraries
            names = ", ".join(sorted({d.name for d in items})[:12])
            out.add(
                Finding(
                    module=self.name,
                    rule="unpinned-dependencies",
                    severity=Severity.INFO,
                    title=f"{len(items)} unpinned dependencies cannot be audited precisely",
                    file=manifest,
                    line=items[0].line,
                    evidence=f"No exact version (==) for: {names}",
                    suggestion="Pin exact versions (or add a lock file) so installs are reproducible and auditable.",
                    confidence=Confidence.HIGH,
                    metadata={"packages": sorted({d.name for d in items})},
                ),
                anchor="unpinned",
            )

    def _vuln_finding(self, dep: Dependency, vuln: dict, out: AnalyzerOutput) -> None:
        severity, sev_source, confidence = vuln_severity(vuln)
        ids = vuln.get("_all_ids") or [vuln.get("id", "unknown")]
        primary = next((i for i in ids if i.startswith("GHSA")), vuln.get("id", ids[0]))
        cves = [i for i in ids if i.startswith("CVE-")]
        fixes = fixed_versions(vuln, dep.name, ecosystem=dep.ecosystem)
        summary = (vuln.get("summary") or (vuln.get("details") or "").split("\n")[0])[:240]
        upgrade = (
            f"Upgrade {dep.name} to {fixes[0]} or later"
            if fixes
            else "No fixed version published; consider an alternative package or mitigation"
        )
        out.add(
            Finding(
                module=self.name,
                rule="vulnerable-dependency",
                severity=severity,
                title=f"{dep.name} {dep.version} has a known vulnerability ({primary})",
                file=dep.manifest,
                line=dep.line,
                evidence=(
                    f"{dep.name}=={dep.version}: {summary or 'see advisory'}\n"
                    f"Advisory: {', '.join(ids)} ({sev_source})"
                ),
                suggestion=upgrade + ".",
                confidence=confidence,
                fixable=bool(
                    fixes
                    and any(
                        m in dep.manifest.lower()
                        for m in (
                            "requirements",
                            "package.json",
                            ".gradle",
                            "pom.xml",
                            "cargo.toml",
                            "go.mod",
                            "pyproject.toml",
                        )
                    )
                ),
                references=[f"https://osv.dev/vulnerability/{primary}"],
                metadata={
                    "package": dep.name,
                    "installed_version": dep.version,
                    "advisory": primary,
                    "aliases": ids,
                    "cves": cves,
                    "fixed_versions": fixes,
                    "severity_source": sev_source,
                },
            ),
            anchor=f"{dep.name}@{dep.version}:{primary}",
        )

    def _pip_audit_ids(self, ctx: RepoContext, unique: list[tuple[str, str]], timeout: float) -> dict:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write("\n".join(f"{n}=={v}" for n, v in unique))
            req = fh.name
        res = run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                req,
                "--no-deps",
                "--disable-pip",
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ],
            cwd=ctx.root,
            timeout=max(timeout, 120),
        )
        if res.returncode == 127 or "No module named pip_audit" in res.stderr:
            raise AnalyzerSkipped("pip-audit is not installed (pip install 'devpilot[audit]')")
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"pip-audit failed: {res.stderr.strip()[:300]}") from exc
        result: dict[tuple[str, str], list[str]] = {}
        for dep in data.get("dependencies", []):
            key = (normalize_name(dep.get("name", "")), dep.get("version", ""))
            result[key] = [v["id"] for v in dep.get("vulns", [])]
        return result

    def _outdated(self, pinned: list[Dependency], out: AnalyzerOutput, timeout: float) -> None:
        def latest(name: str) -> tuple[str, str | None]:
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{name}/json", headers={"User-Agent": "devpilot"}
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return name, json.loads(resp.read())["info"]["version"]
            except (urllib.error.URLError, KeyError, json.JSONDecodeError, OSError, TimeoutError):
                return name, None

        names = sorted({d.name for d in pinned})
        with ThreadPoolExecutor(max_workers=8) as pool:
            latest_versions = dict(pool.map(latest, names))
        for dep in pinned:
            newest = latest_versions.get(dep.name)
            cur, new = _version_tuple(dep.version or ""), _version_tuple(newest or "")
            if cur and new and new > cur:
                out.add(
                    Finding(
                        module=self.name,
                        rule="outdated-dependency",
                        severity=Severity.INFO,
                        title=f"{dep.name} {dep.version} is outdated (latest {newest})",
                        file=dep.manifest,
                        line=dep.line,
                        evidence=f"PyPI reports {newest} as the latest release. Outdated is not the same as vulnerable.",
                        suggestion=f"Consider upgrading {dep.name} after reviewing its changelog.",
                        confidence=Confidence.HIGH,
                        metadata={"package": dep.name, "latest": newest},
                    ),
                    anchor=f"{dep.name}@{dep.version}",
                )
