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
    ecosystem: str = "PyPI"

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


_GRADLE_DEP_RE = re.compile(
    r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|androidTestImplementation|classpath)\s*\(?['"]([a-zA-Z0-9._-]+):([a-zA-Z0-9._-]+)(?::([^'"]+))?['"]\)?(?:.*)"""
)
_GRADLE_MAP_RE = re.compile(
    r"""group\s*:\s*['"]([^'"]+)['"]\s*,\s*name\s*:\s*['"]([^'"]+)['"](?:\s*,\s*version\s*:\s*['"]([^'"]+)['"])?"""
)


def parse_gradle(text: str, manifest: str) -> list[Dependency]:
    deps: list[Dependency] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        clean = line.split("//", 1)[0].strip()
        if not clean or clean.startswith("/*"):
            continue
        m = _GRADLE_DEP_RE.search(clean)
        if m:
            group, artifact, raw_ver = m.group(1), m.group(2), m.group(3)
            name = f"{group}:{artifact}"
            ver = raw_ver.strip() if raw_ver else None
            is_pinned = (
                ver is not None
                and not ver.startswith("$")
                and not ver.startswith("@")
                and "+" not in ver
                and "[" not in ver
                and "(" not in ver
            )
            deps.append(
                Dependency(
                    name,
                    f"=={ver}" if ver else "",
                    ver if is_pinned else None,
                    manifest,
                    idx,
                    ecosystem="Maven",
                )
            )
            continue
        m_map = _GRADLE_MAP_RE.search(clean)
        if m_map:
            group, artifact, raw_ver = m_map.group(1), m_map.group(2), m_map.group(3)
            name = f"{group}:{artifact}"
            ver = raw_ver.strip() if raw_ver else None
            is_pinned = ver is not None and not ver.startswith("$") and "+" not in ver
            deps.append(
                Dependency(
                    name,
                    f"=={ver}" if ver else "",
                    ver if is_pinned else None,
                    manifest,
                    idx,
                    ecosystem="Maven",
                )
            )
    return deps


def parse_libs_versions_toml(text: str, manifest: str) -> list[Dependency]:
    try:
        data = tomllib.loads(text)
    except Exception:  # noqa: BLE001
        return []
    deps: list[Dependency] = []
    versions = data.get("versions", {}) or {}
    libraries = data.get("libraries", {}) or {}
    for alias, spec in libraries.items():
        name: str | None = None
        ver: str | None = None
        if isinstance(spec, str):
            parts = spec.split(":")
            if len(parts) >= 2:
                name = f"{parts[0]}:{parts[1]}"
                if len(parts) >= 3:
                    ver = parts[2]
        elif isinstance(spec, dict):
            if "module" in spec:
                name = str(spec["module"])
            elif "group" in spec and "name" in spec:
                name = f"{spec['group']}:{spec['name']}"
            if "version.ref" in spec:
                ref = spec["version.ref"]
                ver = str(versions.get(ref, "")) or None
            elif "version" in spec:
                v = spec["version"]
                ver = (
                    str(v)
                    if isinstance(v, (str, int, float))
                    else str(v.get("strictly") or v.get("prefer") or "")
                )
        if name:
            is_pinned = ver is not None and "+" not in ver
            line_no = _line_of(text, alias)
            deps.append(
                Dependency(
                    name,
                    f"=={ver}" if ver else "",
                    ver if is_pinned else None,
                    manifest,
                    line_no,
                    ecosystem="Maven",
                )
            )
    return deps


def parse_pom_xml(text: str, manifest: str) -> list[Dependency]:
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
    except Exception:  # noqa: BLE001
        return []
    deps: list[Dependency] = []
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    for dep in root.findall(f".//{ns}dependency"):
        gid = dep.find(f"{ns}groupId")
        aid = dep.find(f"{ns}artifactId")
        ver = dep.find(f"{ns}version")
        if gid is not None and aid is not None and gid.text and aid.text:
            name = f"{gid.text.strip()}:{aid.text.strip()}"
            v = ver.text.strip() if (ver is not None and ver.text) else None
            is_pinned = v is not None and not v.startswith("${") and "+" not in v
            deps.append(
                Dependency(
                    name,
                    f"=={v}" if v else "",
                    v if is_pinned else None,
                    manifest,
                    _line_of(text, aid.text.strip()),
                    ecosystem="Maven",
                )
            )
    return deps


def parse_package_json(text: str, manifest: str) -> list[Dependency]:
    import json

    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    deps: list[Dependency] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        sec_dict = data.get(section, {}) or {}
        if isinstance(sec_dict, dict):
            for name, spec in sec_dict.items():
                spec_str = str(spec).strip()
                s = spec_str.lstrip("=v").strip()
                is_pinned = bool(re.fullmatch(r"\d+\.\d+\.\d+.*", s))
                clean_ver = s if is_pinned else None
                deps.append(
                    Dependency(
                        name,
                        spec_str,
                        clean_ver,
                        manifest,
                        _line_of(text, f'"{name}"'),
                        ecosystem="npm",
                    )
                )
    return deps


def _parse_manifest_file(rel: str, text: str) -> list[Dependency]:
    name = rel.rsplit("/", 1)[-1].lower()
    if re.fullmatch(r"requirements.*\.txt", name) or name.endswith("-requirements.txt"):
        return parse_requirements(text, rel)
    if name == "pyproject.toml":
        return parse_pyproject(text, rel)
    if name in ("poetry.lock", "uv.lock"):
        return parse_lockfile(text, rel)
    if name in ("build.gradle", "build.gradle.kts"):
        return parse_gradle(text, rel)
    if name == "libs.versions.toml":
        return parse_libs_versions_toml(text, rel)
    if name == "pom.xml":
        return parse_pom_xml(text, rel)
    if name == "package.json":
        return parse_package_json(text, rel)
    return []


def discover_dependencies(ctx: RepoContext) -> list[Dependency]:
    deps: list[Dependency] = []
    for rel in ctx.files:
        text = ctx.read_text(rel)
        if text is not None:
            deps.extend(_parse_manifest_file(rel, text))
    return deps
