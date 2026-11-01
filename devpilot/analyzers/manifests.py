"""Dependency manifest parsing (requirements*.txt, pyproject.toml, poetry.lock, uv.lock)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from devpilot.core.context import RepoContext

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*?)\s*(;[^#]*)?\s*(#.*)?$")
_PIN_RE = re.compile(r"^===?\s*([A-Za-z0-9][A-Za-z0-9.+!_-]*)$")


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Dependency:
    name: str
    specifier: str
    version: str | None  # exact pinned version, if any
    manifest: str
    line: int | None

    @property
    def pinned(self) -> bool:
        return self.version is not None


def _pinned_version(spec: str) -> str | None:
    spec = spec.strip()
    m = _PIN_RE.match(spec)
    if m and "*" not in m.group(1):
        return m.group(1)
    return None


def parse_requirement_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith(("#", "-", "git+", "http://", "https://", "file:")):
        return None
    if "://" in line or line.startswith("."):
        return None
    m = _REQ_RE.match(line)
    if not m:
        return None
    return m.group(1), (m.group(3) or "").strip()


def parse_requirements(text: str, manifest: str) -> list[Dependency]:
    deps = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        parsed = parse_requirement_line(raw.split(" #", 1)[0])
        if parsed:
            name, spec = parsed
            deps.append(Dependency(normalize_name(name), spec, _pinned_version(spec), manifest, idx))
    return deps


def _line_of(text: str, needle: str) -> int | None:
    for idx, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return idx
    return None


def parse_pyproject(text: str, manifest: str) -> list[Dependency]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    deps: list[Dependency] = []
    project = data.get("project", {}) or {}
    entries: list[str] = list(project.get("dependencies", []) or [])
    for group in (project.get("optional-dependencies", {}) or {}).values():
        entries.extend(group or [])
    for entry in entries:
        parsed = parse_requirement_line(str(entry))
        if parsed:
            name, spec = parsed
            deps.append(
                Dependency(
                    normalize_name(name), spec, _pinned_version(spec), manifest, _line_of(text, str(entry))
                )
            )
    poetry = ((data.get("tool", {}) or {}).get("poetry", {}) or {}).get("dependencies", {}) or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        version_spec = spec.get("version", "") if isinstance(spec, dict) else str(spec)
        exact = (
            version_spec
            if re.fullmatch(r"\d+(\.\d+)*", version_spec or "")
            else _pinned_version(version_spec)
        )
        deps.append(Dependency(normalize_name(name), version_spec, exact, manifest, _line_of(text, name)))
    return deps


def parse_lockfile(text: str, manifest: str) -> list[Dependency]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    deps = []
    for pkg in data.get("package", []) or []:
        name, version = pkg.get("name"), pkg.get("version")
        if name and version:
            deps.append(
                Dependency(
                    normalize_name(name),
                    f"=={version}",
                    str(version),
                    manifest,
                    _line_of(text, f'name = "{name}"'),
                )
            )
    return deps


def discover_dependencies(ctx: RepoContext) -> list[Dependency]:
    deps: list[Dependency] = []
    for rel in ctx.files:
        name = rel.rsplit("/", 1)[-1].lower()
        text = None
        if re.fullmatch(r"requirements.*\.txt", name) or name.endswith("-requirements.txt"):
            text = ctx.read_text(rel)
            if text is not None:
                deps.extend(parse_requirements(text, rel))
        elif name == "pyproject.toml":
            text = ctx.read_text(rel)
            if text is not None:
                deps.extend(parse_pyproject(text, rel))
        elif name in ("poetry.lock", "uv.lock"):
            text = ctx.read_text(rel)
            if text is not None:
                deps.extend(parse_lockfile(text, rel))
    return deps
