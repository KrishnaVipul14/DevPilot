"""API handler functions for the local DevPilot HTTP server."""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from devpilot.ai.gemini import _read_dotenv_vars as _read_gemini_dotenv
from devpilot.ai.groq import _read_dotenv_vars as _read_groq_dotenv
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
from devpilot.core.scanner import run_scan
from devpilot.fixes.patch_generator import PatchError, propose_patch
from devpilot.fixes.patch_manager import apply_patch, discard_patch, verify_patch
from devpilot.memory.database import MemoryDB


def update_dotenv_file(filepath: Path, updates: dict[str, str]) -> None:
    """Safely update or append keys in a .env file without deleting comments or other variables."""
    lines: list[str] = []
    if filepath.is_file():
        try:
            lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []

    remaining_keys = set(updates.keys())
    new_lines: list[str] = []
    key_pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

    for line in lines:
        match = key_pattern.match(line)
        if match:
            k = match.group(1)
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                remaining_keys.discard(k)
                continue
        new_lines.append(line)

    for k in sorted(remaining_keys):
        new_lines.append(f"{k}={updates[k]}")

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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

    def post_plan(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        report = load_latest_report(self.root, refresh_from_memory=True)
        if report is None:
            raise APIHTTPError(404, "No scan report found. Run `devpilot scan .` first.")
        b = body or {}
        prefer_ai = not bool(b.get("deterministic", False)) and bool(b.get("prefer_ai", True))
        plan = generate_plan(self._ctx(), report, prefer_ai=prefer_ai)
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

    def set_repository(self, path_str: str) -> Path:
        target = Path(path_str).expanduser().resolve()
        if not target.is_dir():
            raise APIHTTPError(400, f"Directory does not exist: {target}")
        self.root = target
        return self.root

    def _mask_key(self, key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "••••" + key[-2:]
        return key[:4] + "••••" + key[-4:]

    def get_settings(self) -> dict[str, Any]:
        cfg = load_config(self.root)
        st = get_ai_provider(cfg).status()
        groq_env = (
            os.environ.get("GROQ_API_KEY", "").strip()
            or _read_groq_dotenv(self.root).get("GROQ_API_KEY", "").strip()
        )
        gemini_env = (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
            or _read_gemini_dotenv(self.root).get("GEMINI_API_KEY", "").strip()
            or _read_gemini_dotenv(self.root).get("GOOGLE_API_KEY", "").strip()
        )
        rpath = latest_report_path(self.root)
        has_cfg = any((self.root / fn).is_file() for fn in ("devpilot.yml", "devpilot.yaml", ".devpilot.yml"))
        return {
            "repository": {
                "name": self.root.name,
                "path": str(self.root),
                "exists": self.root.is_dir(),
                "has_devpilot_yaml": has_cfg,
                "has_report": rpath.is_file(),
            },
            "ai": {
                "available": st.available,
                "provider": cfg.ai.provider,
                "model": st.model,
                "reason": st.reason,
                "has_groq_key": bool(groq_env),
                "groq_key_preview": self._mask_key(groq_env),
                "has_gemini_key": bool(gemini_env),
                "gemini_key_preview": self._mask_key(gemini_env),
            },
        }

    def _apply_ai_settings(self, body: dict[str, Any]) -> dict[str, str]:
        dotenv_updates: dict[str, str] = {}
        provider = body.get("provider")
        target_provider: str | None = None
        if isinstance(provider, str) and provider.strip().lower() in ("groq", "gemini"):
            target_provider = provider.strip().lower()
            os.environ["DEVPILOT_AI_PROVIDER"] = target_provider
            dotenv_updates["DEVPILOT_AI_PROVIDER"] = target_provider

        model = body.get("model")
        if isinstance(model, str):
            m = model.strip()
            if target_provider == "gemini" and any(
                k in m.lower() for k in ("llama", "mixtral", "gemma", "qwen", "openai", "gpt")
            ):
                m = ""
            elif target_provider == "groq" and "gemini" in m.lower():
                m = ""
            if m:
                os.environ["DEVPILOT_AI_MODEL"] = m
                dotenv_updates["DEVPILOT_AI_MODEL"] = m
            else:
                os.environ.pop("DEVPILOT_AI_MODEL", None)
                dotenv_updates["DEVPILOT_AI_MODEL"] = ""

        groq_key = body.get("groq_api_key")
        if isinstance(groq_key, str) and groq_key.strip():
            gk = groq_key.strip()
            os.environ["GROQ_API_KEY"] = gk
            dotenv_updates["GROQ_API_KEY"] = gk

        gemini_key = body.get("gemini_api_key")
        if isinstance(gemini_key, str) and gemini_key.strip():
            gk = gemini_key.strip()
            os.environ["GEMINI_API_KEY"] = gk
            dotenv_updates["GEMINI_API_KEY"] = gk

        return dotenv_updates

    def post_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        repo_path = body.get("repository_path")
        if isinstance(repo_path, str) and repo_path.strip():
            self.set_repository(repo_path.strip())

        dotenv_updates = self._apply_ai_settings(body)
        if body.get("persist_to_env", True) and dotenv_updates:
            # Always save to active target repo .env
            update_dotenv_file(self.root / ".env", dotenv_updates)
            # Also save to current working dir .env if distinct
            cwd_env = Path.cwd() / ".env"
            if cwd_env.resolve() != (self.root / ".env").resolve():
                update_dotenv_file(cwd_env, dotenv_updates)

        return self.get_settings()

    def post_repository(self, body: dict[str, Any]) -> dict[str, Any]:
        path_str = body.get("path")
        if not path_str or not isinstance(path_str, str):
            raise APIHTTPError(400, "Missing required 'path' parameter in request body.")
        self.set_repository(path_str.strip())
        return self.get_status()

    def post_scan(self, body: dict[str, Any]) -> dict[str, Any]:
        path_str = body.get("path")
        if isinstance(path_str, str) and path_str.strip():
            self.set_repository(path_str.strip())
        offline = bool(body.get("offline", False))
        cfg = load_config(self.root)
        try:
            report = run_scan(self.root, config=cfg, offline=offline, persist=True)
        except Exception as exc:
            raise APIHTTPError(500, f"Scan failed: {exc}") from exc
        return {
            "status": self.get_status(),
            "report": report.model_dump(mode="json"),
        }
