"""API handler functions for the local DevPilot HTTP server."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from devpilot.ai.provider import AIProviderError, get_ai_provider
from devpilot.ai.suggestions import explain_finding, generate_plan
from devpilot.analyzers.change_impact import analyze_git_impact, analyze_symbol_impact
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.core.config import load_config
from devpilot.core.context import RepoContext
from devpilot.core.report import (
    find_finding,
    latest_report_path,
    load_latest_graph,
    load_latest_report,
)
from devpilot.fixes.patch_generator import PatchError, propose_patch
from devpilot.fixes.patch_manager import apply_patch, discard_patch, verify_patch
from devpilot.memory.database import MemoryDB


class APIHTTPError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class LocalAPI:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _ctx(self) -> RepoContext:
        return RepoContext(root=self.root, config=load_config(self.root))

    def get_status(self) -> dict[str, Any]:
        cfg = load_config(self.root)
        st = get_ai_provider(cfg).status()
        rpath = latest_report_path(self.root)
        has_report = rpath.is_file()
        mtime = rpath.stat().st_mtime if has_report else None
        report = load_latest_report(self.root, refresh_from_memory=False) if has_report else None
        return {
            "has_report": has_report,
            "scan_id": report.scan_id if report else None,
            "finished_at": report.finished_at.isoformat() if report else None,
            "report_mtime": mtime,
            "repository": {
                "name": self.root.name,
                "path": str(self.root),
            },
            "ai": {
                "available": st.available,
                "provider": st.provider,
                "model": st.model,
                "reason": st.reason,
            },
        }

    def get_report(self) -> dict[str, Any]:
        report = load_latest_report(self.root, refresh_from_memory=True)
        if report is None:
            raise APIHTTPError(404, "No scan report found. Run `devpilot scan .` first.")
        return report.model_dump(mode="json")

    def get_history(self) -> dict[str, Any]:
        return MemoryDB(self.root).get_history()

    def get_graph(self) -> dict[str, Any]:
        g = load_latest_graph(self.root)
        if g is None:
            raise APIHTTPError(404, "No repository graph found. Run `devpilot scan .` first.")
        return g

    def get_impact(self, query: dict[str, list[str]]) -> dict[str, Any]:
        ctx = self._ctx()
        cached_g = load_latest_graph(self.root)
        graph = RepoGraph.from_dict(cached_g) if cached_g else RepoGraph.build(ctx)
        sym = (query.get("symbol") or [""])[0].strip()
        if sym:
            return analyze_symbol_impact(ctx, sym, graph=graph)
        base = (query.get("base") or ["HEAD"])[0].strip() or "HEAD"
        return analyze_git_impact(ctx, base=base, graph=graph)

    def get_plan(self) -> dict[str, Any]:
        return {"plan": MemoryDB(self.root).get_latest_plan()}

    def post_plan(self) -> dict[str, Any]:
        report = load_latest_report(self.root, refresh_from_memory=True)
        if report is None:
            raise APIHTTPError(404, "No scan report found. Run `devpilot scan .` first.")
        plan = generate_plan(self._ctx(), report, prefer_ai=True)
        return {"plan": plan}

    def get_patches(self) -> dict[str, Any]:
        return {"patches": MemoryDB(self.root).list_patches()}

    def post_explain(self, ref: str) -> dict[str, Any]:
        ref = urllib.parse.unquote(ref)
        report = load_latest_report(self.root, refresh_from_memory=False)
        if report is None:
            raise APIHTTPError(404, "No scan report found.")
        finding = find_finding(report, ref)
        if finding is None:
            raise APIHTTPError(404, f"Finding `{ref}` not found in latest report.")
        try:
            exp = explain_finding(self._ctx(), finding, force=False)
        except AIProviderError as exc:
            raise APIHTTPError(503, str(exc)) from exc
        return {"explanation": exp.model_dump(mode="json")}

    def post_fix(self, ref: str, body: dict[str, Any]) -> dict[str, Any]:
        ref = urllib.parse.unquote(ref)
        report = load_latest_report(self.root, refresh_from_memory=False)
        if report is None:
            raise APIHTTPError(404, "No scan report found.")
        finding = find_finding(report, ref)
        if finding is None:
            raise APIHTTPError(404, f"Finding `{ref}` not found in latest report.")
        engine = str(body.get("engine") or "auto")
        if engine not in ("auto", "ruff", "ai"):
            engine = "auto"
        try:
            patch = propose_patch(self._ctx(), finding, engine=engine)  # type: ignore[arg-type]
        except PatchError as exc:
            raise APIHTTPError(400, str(exc)) from exc
        return {"patch": patch}

    def post_patch_action(self, patch_id: str, action: str) -> dict[str, Any]:
        patch_id = urllib.parse.unquote(patch_id)
        ctx = self._ctx()
        try:
            if action == "verify":
                patch = verify_patch(ctx, patch_id)
            elif action == "apply":
                patch = apply_patch(ctx, patch_id)
            elif action == "discard":
                patch = discard_patch(ctx, patch_id)
            else:
                raise APIHTTPError(404, f"Unknown patch action `{action}`.")
        except PatchError as exc:
            raise APIHTTPError(400, str(exc)) from exc
        return {"patch": patch}
