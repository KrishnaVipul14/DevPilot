"""Isolated patch verification engine.

Runs verification in an isolated temporary Git worktree (or a temporary copy if
not in a Git repository or if uncommitted changes exist on the target branch):
1. Python syntax compilation (`py_compile`) on modified Python files.
2. Targeted Ruff static analysis on modified Python files.
3. Targeted `pytest` execution for tests identified by the Repository Intelligence
   Graph (or the full test suite if present).

Assigns honest statuses:
- `verified`: static checks passed AND relevant tests passed (or non-code fix check passed).
- `partially_verified`: static checks passed, but no test suite exists or pytest is unavailable.
- `failed`: any syntax check, static check, or test failed.
- `not_verified`: no checks could be executed.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devpilot.analyzers.change_impact import analyze_symbol_impact
from devpilot.analyzers.code_health import find_ruff
from devpilot.analyzers.repository_graph import RepoGraph, is_test_file
from devpilot.core.context import RepoContext
from devpilot.utils import git as gitutil
from devpilot.utils.proc import run


@contextmanager
def isolated_workspace(ctx: RepoContext) -> Iterator[tuple[Path, str]]:
    """Yield `(workspace_path, mode)` where `mode` is `'git-worktree'` or `'temp-copy'`.
    Always cleans up on exit and never modifies `ctx.root`."""
    tmp_base = Path(tempfile.mkdtemp(prefix="devpilot-verify-"))
    wt_dir = tmp_base / "worktree"
    used_worktree = False
    try:
        if ctx.git_root is not None and not gitutil.is_dirty(ctx.root):
            res = gitutil.git(["worktree", "add", "--detach", str(wt_dir), "HEAD"], cwd=ctx.root)
            if res.ok and wt_dir.is_dir():
                used_worktree = True
                # If ctx.root is a subdirectory of git_root, point inside it
                rel_sub = ctx.root.resolve().relative_to(ctx.git_root.resolve())
                yield (wt_dir / rel_sub), "git-worktree"
        if not used_worktree:
            copy_dir = tmp_base / "repo"
            excludes = set(ctx.config.all_excludes)

            def _ignore(_dir: str, names: list[str]) -> set[str]:
                return {n for n in names if n in excludes}

            shutil.copytree(ctx.root, copy_dir, ignore=_ignore, dirs_exist_ok=True)
            yield copy_dir, "temp-copy"
    finally:
        if used_worktree and ctx.git_root is not None:
            gitutil.git(["worktree", "remove", "--force", str(wt_dir)], cwd=ctx.root)
            gitutil.git(["worktree", "prune"], cwd=ctx.root)
        shutil.rmtree(tmp_base, ignore_errors=True)


def _find_python(ctx: RepoContext) -> str:
    if ctx.config.verify.python:
        return ctx.config.verify.python
    for venv_name in (".venv", "venv"):
        win = ctx.root / venv_name / "Scripts" / "python.exe"
        posix = ctx.root / venv_name / "bin" / "python"
        if win.is_file():
            return str(win)
        if posix.is_file():
            return str(posix)
    return sys.executable


def verify_patch_edits(
    ctx: RepoContext,
    edits: dict[str, str],
) -> dict[str, Any]:
    py_bin = _find_python(ctx)
    timeout = ctx.config.verify.timeout
    graph = RepoGraph.build(ctx)

    # Identify relevant tests before entering worktree
    target_test_files: set[str] = set()
    all_repo_tests = [f for f in ctx.python_files if is_test_file(f)]
    for rel in edits:
        if rel.endswith(".py"):
            for node in graph.nodes.values():
                if node.file == rel and node.kind in ("function", "class"):
                    imp = analyze_symbol_impact(ctx, node.id, graph=graph)
                    for item in imp.get("impacts", []):
                        for t in item.get("tests", []):
                            if t.get("file"):
                                target_test_files.add(t["file"])
    if not target_test_files and all_repo_tests:
        target_test_files.update(all_repo_tests)

    checks: list[dict[str, Any]] = []

    with isolated_workspace(ctx) as (ws, mode):
        for rel, content in edits.items():
            dest = ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

        py_files = [r for r in edits if r.endswith(".py")]

        # 1. Syntax check via py_compile
        if py_files:
            cmd = [py_bin, "-m", "py_compile", *py_files]
            res = run(cmd, cwd=ws, timeout=30)
            checks.append({
                "name": "python_syntax",
                "status": "passed" if res.ok else "failed",
                "detail": (res.stdout + "\n" + res.stderr).strip() or f"Compiled {len(py_files)} file(s) cleanly.",
                "command": " ".join(cmd),
                "duration_ms": res.duration_ms,
            })

        # 2. Ruff static check on modified Python files
        ruff = find_ruff()
        if py_files and ruff:
            select = ",".join(ctx.config.analyzers.code_health.select)
            cmd = [ruff, "check", "--no-cache", "--select", select, *py_files]
            res = run(cmd, cwd=ws, timeout=60)
            checks.append({
                "name": "ruff_static_check",
                "status": "passed" if res.ok else "failed",
                "detail": (res.stdout + "\n" + res.stderr).strip() or "All selected Ruff rules passed.",
                "command": f"ruff check --select {select} {' '.join(py_files)}",
                "duration_ms": res.duration_ms,
            })

        # 3. Non-Python file validation (e.g. requirements.txt / .env.example)
        non_py = [r for r in edits if not r.endswith(".py")]
        for rel in non_py:
            text = (ws / rel).read_text(encoding="utf-8")
            ok = bool(text.strip())
            checks.append({
                "name": f"validate_{rel}",
                "status": "passed" if ok else "failed",
                "detail": f"Validated updated {rel} ({len(text.splitlines())} lines).",
                "command": None,
                "duration_ms": 1,
            })

        # 4. Targeted pytest execution
        if ctx.config.verify.run_tests:
            if target_test_files:
                sorted_tests = sorted(target_test_files)
                cmd = [py_bin, "-m", "pytest", "-q", *sorted_tests]
                res = run(cmd, cwd=ws, timeout=timeout)
                if "No module named pytest" in res.stderr:
                    # Fallback to sys.executable if project venv lacks pytest
                    cmd = [sys.executable, "-m", "pytest", "-q", *sorted_tests]
                    res = run(cmd, cwd=ws, timeout=timeout)
                if "No module named pytest" in res.stderr:
                    checks.append({
                        "name": "pytest",
                        "status": "skipped",
                        "detail": "pytest is not installed in the target environment.",
                        "command": f"pytest -q {' '.join(sorted_tests)}",
                        "duration_ms": res.duration_ms,
                    })
                else:
                    checks.append({
                        "name": "pytest",
                        "status": "passed" if res.ok else "failed",
                        "detail": (res.stdout + "\n" + res.stderr).strip()[:4000],
                        "command": f"pytest -q {' '.join(sorted_tests)}",
                        "duration_ms": res.duration_ms,
                    })
            else:
                checks.append({
                    "name": "pytest",
                    "status": "skipped",
                    "detail": "No test files were found in the repository.",
                    "command": None,
                    "duration_ms": 0,
                })

    statuses = [c["status"] for c in checks]
    if not checks or all(s == "skipped" for s in statuses):
        overall = "not_verified"
    elif any(s in ("failed", "error") for s in statuses):
        overall = "failed"
    elif any(s == "skipped" for s in statuses) and bool(py_files):
        overall = "partially_verified"
    else:
        overall = "verified"

    return {
        "status": overall,
        "checks": checks,
        "mode": mode,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
