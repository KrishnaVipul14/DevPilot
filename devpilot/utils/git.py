"""Thin wrappers around the git CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

from devpilot.utils.proc import ProcResult, run


def git_available() -> bool:
    return shutil.which("git") is not None


def git(args: list[str], cwd: Path, timeout: float = 30) -> ProcResult:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def git_root(path: Path) -> Path | None:
    if not git_available():
        return None
    res = git(["rev-parse", "--show-toplevel"], path)
    if not res.ok:
        return None
    return Path(res.stdout.strip()).resolve()


def head_commit(path: Path) -> str | None:
    res = git(["rev-parse", "HEAD"], path)
    return res.stdout.strip() if res.ok else None


def current_branch(path: Path) -> str | None:
    res = git(["rev-parse", "--abbrev-ref", "HEAD"], path)
    return res.stdout.strip() if res.ok else None


def is_dirty(path: Path) -> bool | None:
    res = git(["status", "--porcelain"], path)
    if not res.ok:
        return None
    for line in res.stdout.splitlines():
        entry = line[3:].strip().replace("\\", "/")
        if entry == ".devpilot" or entry.startswith(".devpilot/"):
            continue
        if line.strip():
            return True
    return False


def tracked_files(path: Path) -> set[str] | None:
    """Return tracked files relative to the git root (POSIX paths)."""
    res = git(["ls-files", "-z"], path)
    if not res.ok:
        return None
    return {p for p in res.stdout.split("\0") if p}


def untracked_files(path: Path) -> list[str]:
    res = git(["ls-files", "--others", "--exclude-standard", "-z"], path)
    return [p for p in res.stdout.split("\0") if p] if res.ok else []


def is_ignored(path: Path, rel: str) -> bool:
    res = git(["check-ignore", "-q", rel], path)
    return res.returncode == 0
