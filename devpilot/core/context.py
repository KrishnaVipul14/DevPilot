"""Repository context shared by all analyzers during a scan.

Holds the discovered file list and caches file contents / parsed ASTs so each
file is read and parsed at most once per scan.
"""

from __future__ import annotations

import ast
import fnmatch
import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from devpilot.core.config import DevPilotConfig
from devpilot.utils import git as gitutil

MAX_FILE_BYTES = 1_000_000  # skip huge/generated files
SENSITIVE_FILE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "*.kdbx")
ENV_EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", "example.env", ".env.dist")


def is_sensitive_file(rel_path: str) -> bool:
    """Files whose *contents* must never be read or sent anywhere."""
    name = rel_path.rsplit("/", 1)[-1]
    if name in ENV_EXAMPLE_NAMES:
        return False
    return any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS)


def _excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.rstrip("/")
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*") or rel.startswith(pat + "/"):
            return True
    return False


@dataclass
class RepoContext:
    root: Path
    config: DevPilotConfig
    offline: bool = False
    _text_cache: dict[str, str | None] = field(default_factory=dict)
    _ast_cache: dict[str, ast.Module | None] = field(default_factory=dict)

    @cached_property
    def git_root(self) -> Path | None:
        return gitutil.git_root(self.root)

    @cached_property
    def files(self) -> list[str]:
        """All non-excluded files (POSIX paths relative to root), honouring .gitignore when in git."""
        excludes = self.config.all_excludes
        candidates: list[str] = []
        if self.git_root is not None and (self.root / ".git").exists():
            tracked = gitutil.git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], self.root)
            if tracked.ok:
                candidates = [p for p in tracked.stdout.split("\0") if p]
        if not candidates:
            candidates = self._walk(excludes)
        result = []
        for rel in candidates:
            rel = rel.replace("\\", "/")
            if _excluded(rel, excludes):
                continue
            full = self.root / rel
            if full.is_file():
                result.append(rel)
        return sorted(set(result))

    def _walk(self, excludes: list[str]) -> list[str]:
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir
            dirnames[:] = [d for d in dirnames if not _excluded(f"{rel_dir}/{d}".lstrip("/"), excludes)]
            for name in filenames:
                out.append(f"{rel_dir}/{name}".lstrip("/"))
        return out

    @cached_property
    def python_files(self) -> list[str]:
        return [f for f in self.files if f.endswith(".py")]

    @cached_property
    def markdown_files(self) -> list[str]:
        return [f for f in self.files if f.lower().endswith((".md", ".rst", ".markdown"))]

    def read_text(self, rel: str) -> str | None:
        """Read a repository file. Refuses sensitive files (e.g. .env)."""
        if rel in self._text_cache:
            return self._text_cache[rel]
        text: str | None = None
        if not is_sensitive_file(rel):
            path = self.root / rel
            try:
                if path.stat().st_size <= MAX_FILE_BYTES:
                    text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None
        self._text_cache[rel] = text
        return text

    def parse(self, rel: str) -> ast.Module | None:
        if rel in self._ast_cache:
            return self._ast_cache[rel]
        tree: ast.Module | None = None
        text = self.read_text(rel)
        if text is not None:
            try:
                tree = ast.parse(text, filename=rel)
            except (SyntaxError, ValueError):
                tree = None
        self._ast_cache[rel] = tree
        return tree

    def line(self, rel: str, lineno: int | None) -> str:
        if lineno is None:
            return ""
        text = self.read_text(rel) or ""
        lines = text.splitlines()
        return lines[lineno - 1] if 0 < lineno <= len(lines) else ""
