"""Configuration & setup doctor.

* Compares environment variables referenced in code with ``.env.example``.
* Checks that ``.env`` files are ignored and not committed (without reading them).
* Detects likely hardcoded secrets - values are never printed, stored or sent.
* Checks for basic setup documentation.
"""

from __future__ import annotations

import re

from devpilot.analyzers.base import Analyzer, AnalyzerOutput
from devpilot.analyzers.envsecrets import (
    EnvUsage,
    env_usages,
    parse_env_keys,
    scan_python_for_secrets,
    scan_text_for_secrets,
)
from devpilot.core.context import ENV_EXAMPLE_NAMES, RepoContext, is_sensitive_file
from devpilot.core.models import Confidence, Finding, Severity
from devpilot.utils import git as gitutil

TEXT_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg",
                 ".sh", ".ps1", ".md", ".txt", ".env.example", ".go", ".rb", ".java", ".php", ".tf")
LOCK_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock")
# Variables commonly provided by the platform; not expected in .env.example.
PLATFORM_VARS = {"PATH", "HOME", "USER", "PWD", "SHELL", "TERM", "LANG", "TMPDIR", "TEMP", "TMP", "CI",
                 "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_WORKSPACE", "GITHUB_BASE_REF",
                 "GITHUB_SHA", "GITHUB_REF", "GITHUB_EVENT_PATH", "VIRTUAL_ENV", "PYTHONPATH", "APPDATA",
                 "LOCALAPPDATA", "USERPROFILE", "SYSTEMROOT", "COMSPEC", "PYTHONIOENCODING", "NO_COLOR",
                 "PYTEST_CURRENT_TEST"}


class SetupDoctorAnalyzer(Analyzer):
    name = "setup_doctor"
    description = "Environment configuration, secret hygiene and setup documentation"

    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        out = AnalyzerOutput()
        usages = self._collect_env_usages(ctx)
        self._check_env_example(ctx, usages, out)
        self._check_env_files(ctx, out)
        self._check_secrets(ctx, out)
        self._check_readme(ctx, out)
        out.message = f"{len({u.name for u in usages})} environment variables referenced in code"
        return out

    @staticmethod
    def _collect_env_usages(ctx: RepoContext) -> list[EnvUsage]:
        usages: list[EnvUsage] = []
        for rel in ctx.python_files:
            tree = ctx.parse(rel)
            if tree is not None:
                usages.extend(u for u in env_usages(tree, rel) if u.name not in PLATFORM_VARS)
        return usages

    def _check_env_example(self, ctx: RepoContext, usages: list[EnvUsage], out: AnalyzerOutput) -> None:
        examples = [f for f in ctx.files if f.rsplit("/", 1)[-1] in ENV_EXAMPLE_NAMES and "/" not in f]
        by_name: dict[str, list[EnvUsage]] = {}
        for u in usages:
            by_name.setdefault(u.name, []).append(u)
        if not examples:
            if by_name:
                required = sorted(n for n, us in by_name.items() if not all(u.has_default for u in us))
                first = min(usages, key=lambda u: (u.file, u.line))
                out.add(Finding(
                    module=self.name, rule="env-example-missing", severity=Severity.MEDIUM,
                    title="Environment variables are used but no .env.example exists",
                    file=first.file, line=first.line,
                    evidence=(f"{len(by_name)} variables referenced in code ({', '.join(sorted(by_name)[:10])}); "
                              f"{len(required)} have no default."),
                    suggestion="Add a .env.example listing every variable with a placeholder value and document it in the README.",
                    confidence=Confidence.HIGH, metadata={"variables": sorted(by_name), "required": required},
                ), anchor="env-example-missing")
            return
        example = examples[0]
        keys = parse_env_keys(ctx.read_text(example) or "")
        for name, us in sorted(by_name.items()):
            if name in keys:
                continue
            required = not all(u.has_default for u in us)
            u = us[0]
            out.add(Finding(
                module=self.name, rule="env-missing-from-example",
                severity=Severity.MEDIUM if required else Severity.LOW,
                title=f"{name} is used in code but missing from {example}",
                file=u.file, line=u.line,
                evidence=(f"`{name}` is read at {', '.join(f'{x.file}:{x.line}' for x in us[:3])}"
                          f"{' without a default value' if required else ' (has a default)'}; not listed in {example}."),
                suggestion=f"Add `{name}=` with a placeholder value to {example} and document its purpose.",
                confidence=Confidence.HIGH, metadata={"variable": name, "required": required, "example_file": example},
            ), anchor=f"env:{name}")
        used = set(by_name)
        for name, line in keys.items():
            if name not in used:
                out.add(Finding(
                    module=self.name, rule="env-unused-in-code", severity=Severity.INFO,
                    title=f"{name} is documented in {example} but not referenced in Python code",
                    file=example, line=line,
                    evidence=f"No os.environ/os.getenv reference to `{name}` was found in analyzed Python files.",
                    suggestion="Remove the stale variable, or ignore this if it is consumed by tooling outside Python.",
                    confidence=Confidence.MEDIUM, metadata={"variable": name},
                ), anchor=f"env-unused:{name}")

    def _check_env_files(self, ctx: RepoContext, out: AnalyzerOutput) -> None:
        # Never open .env files - only check presence, git tracking and ignore status.
        candidates = [p for p in ctx.root.glob(".env*") if p.is_file() and p.name not in ENV_EXAMPLE_NAMES]
        tracked = gitutil.tracked_files(ctx.root) if ctx.git_root else None
        for path in candidates:
            rel = path.name
            if tracked is not None and self._tracked(ctx, rel, tracked):
                out.add(Finding(
                    module=self.name, rule="env-file-committed", severity=Severity.CRITICAL,
                    title=f"{rel} is committed to git", file=rel,
                    evidence=f"`{rel}` is tracked by git. Environment files typically contain credentials. Contents were not read.",
                    suggestion=f"Run `git rm --cached {rel}`, add it to .gitignore and rotate any credentials it contained.",
                    confidence=Confidence.HIGH,
                ), anchor=f"committed:{rel}")
            elif ctx.git_root and not gitutil.is_ignored(ctx.root, rel):
                out.add(Finding(
                    module=self.name, rule="env-file-not-ignored", severity=Severity.HIGH,
                    title=f"{rel} is not covered by .gitignore", file=rel,
                    evidence=f"`{rel}` exists and is not ignored, so it could be committed accidentally.",
                    suggestion=f"Add `{rel}` (or `.env*` with `!.env.example`) to .gitignore.",
                    confidence=Confidence.HIGH,
                ), anchor=f"not-ignored:{rel}")

    @staticmethod
    def _tracked(ctx: RepoContext, rel: str, tracked: set[str]) -> bool:
        prefix = ""
        if ctx.git_root and ctx.git_root != ctx.root.resolve():
            prefix = ctx.root.resolve().relative_to(ctx.git_root).as_posix() + "/"
        return f"{prefix}{rel}" in tracked or rel in tracked

    def _check_secrets(self, ctx: RepoContext, out: AnalyzerOutput) -> None:
        for rel in ctx.files:
            name = rel.rsplit("/", 1)[-1]
            if is_sensitive_file(rel) or name in LOCK_FILES or not rel.lower().endswith(TEXT_SUFFIXES):
                continue
            text = ctx.read_text(rel)
            if not text:
                continue
            hits = scan_text_for_secrets(text)
            if rel.endswith(".py"):
                tree = ctx.parse(rel)
                if tree is not None:
                    hits.extend(scan_python_for_secrets(tree))
            in_tests = bool(re.search(r"(^|/)(tests?|fixtures?)/", rel))
            for hit in hits:
                label = f"`{hit.name}`" if hit.name else hit.kind
                confidence = Confidence.LOW if in_tests else Confidence(hit.confidence)
                out.add(Finding(
                    module=self.name, rule="hardcoded-secret",
                    severity=Severity.MEDIUM if in_tests else Severity.HIGH,
                    title=f"Possible hardcoded secret ({hit.kind})", file=rel, line=hit.line,
                    evidence=f"{label} appears to contain a literal secret (value redacted, {hit.length} characters).",
                    suggestion="Move the value to an environment variable / secret manager, and rotate it if it was ever committed.",
                    confidence=confidence, metadata={"kind": hit.kind, "name": hit.name},
                ), anchor=f"{hit.kind}:{hit.name or ''}:{hit.length}")

    def _check_readme(self, ctx: RepoContext, out: AnalyzerOutput) -> None:
        readmes = [f for f in ctx.files if "/" not in f and f.lower().startswith("readme")]
        if not readmes:
            out.add(Finding(
                module=self.name, rule="readme-missing", severity=Severity.LOW,
                title="No README found", evidence="The repository root has no README file.",
                suggestion="Add a README describing purpose, installation, configuration and usage.",
                confidence=Confidence.HIGH,
            ), anchor="readme-missing")
            return
        text = (ctx.read_text(readmes[0]) or "").lower()
        if not re.search(r"\b(install|setup|set up|getting started|quick ?start)\b", text):
            out.add(Finding(
                module=self.name, rule="setup-instructions-missing", severity=Severity.LOW,
                title="README has no setup/installation instructions", file=readmes[0],
                evidence="No installation, setup or getting-started section was found in the README.",
                suggestion="Document how to install dependencies, configure environment variables and run the project.",
                confidence=Confidence.MEDIUM,
            ), anchor="setup-missing")
