"""Repository configuration (``devpilot.yml``)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

CONFIG_FILENAMES = ("devpilot.yml", "devpilot.yaml", ".devpilot.yml")
STATE_DIR = ".devpilot"

DEFAULT_EXCLUDES = [
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".devpilot",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "site-packages",
    ".next",
    ".eggs",
]

DEFAULT_RUFF_SELECT = [
    "F",  # pyflakes: unused imports/variables, undefined names, ...
    "E9",  # syntax / IO errors
    "B",  # bugbear: likely bugs and design problems
    "C901",  # cyclomatic complexity
    "S102",  # use of exec
    "S307",  # use of eval
    "S602",  # subprocess with shell=True
    "S506",  # unsafe yaml.load
    "E722",  # bare except
]


class CodeHealthConfig(BaseModel):
    enabled: bool = True
    select: list[str] = Field(default_factory=lambda: list(DEFAULT_RUFF_SELECT))
    max_complexity: int = 12
    max_function_lines: int = 80
    max_parameters: int = 7


class DependencyConfig(BaseModel):
    enabled: bool = True
    engine: Literal["osv", "pip-audit"] = "osv"
    check_outdated: bool = False
    timeout: float = 30


class ToggleConfig(BaseModel):
    enabled: bool = True


class AnalyzersConfig(BaseModel):
    android: ToggleConfig = Field(default_factory=ToggleConfig)
    code_health: CodeHealthConfig = Field(default_factory=CodeHealthConfig)
    dependencies: DependencyConfig = Field(default_factory=DependencyConfig)
    setup_doctor: ToggleConfig = Field(default_factory=ToggleConfig)
    documentation: ToggleConfig = Field(default_factory=ToggleConfig)


class AIConfig(BaseModel):
    enabled: bool = True
    provider: Literal["groq", "gemini"] = "groq"
    model: str | None = None  # default comes from the provider / env
    timeout: float = 60
    max_context_chars: int = 24000


class VerifyConfig(BaseModel):
    python: str | None = None  # interpreter used to run tests; auto-detected if empty
    timeout: float = 180
    run_tests: bool = True


class DevPilotConfig(BaseModel):
    root: Path | None = None
    exclude: list[str] = Field(default_factory=list)
    analyzers: AnalyzersConfig = Field(default_factory=AnalyzersConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)

    @property
    def all_excludes(self) -> list[str]:
        return DEFAULT_EXCLUDES + list(self.exclude)


class ConfigError(Exception):
    pass


def find_config(root: Path) -> Path | None:
    for name in CONFIG_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv_keys(env_path: Path) -> dict[str, str]:
    vars_found: dict[str, str] = {}
    if not env_path.is_file():
        return vars_found
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = pattern.match(line)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1].strip()
                if v and k not in vars_found:
                    vars_found[k] = v
    except OSError:
        pass
    return vars_found


def load_config(root: Path) -> DevPilotConfig:
    resolved_root = root.resolve()
    # Read any .env keys from target project root or current working dir into os.environ if not set
    for env_cand in (resolved_root / ".env", Path.cwd() / ".env"):
        for k, v in _load_dotenv_keys(env_cand).items():
            if k in (
                "GROQ_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "DEVPILOT_AI_PROVIDER",
                "DEVPILOT_AI_MODEL",
            ):
                if k not in os.environ and v:
                    os.environ[k] = v

    path = find_config(resolved_root)
    has_explicit_provider = False
    if path is None:
        cfg = DevPilotConfig()
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path.name} must contain a mapping at the top level")
        try:
            cfg = DevPilotConfig.model_validate(data)
            has_explicit_provider = bool(data.get("ai", {}).get("provider"))
        except ValidationError as exc:
            raise ConfigError(f"Invalid configuration in {path.name}:\n{exc}") from exc

    cfg.root = resolved_root

    env_provider = os.environ.get("DEVPILOT_AI_PROVIDER", "").strip().lower()
    if env_provider in ("groq", "gemini"):
        cfg.ai.provider = env_provider  # type: ignore[assignment]
    elif not has_explicit_provider:
        # Auto-detect if user provided a Gemini key and no Groq key
        has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        has_groq = bool(os.environ.get("GROQ_API_KEY"))
        if has_gemini and not has_groq:
            cfg.ai.provider = "gemini"

    env_model = os.environ.get("DEVPILOT_AI_MODEL", "").strip()
    if env_model:
        cfg.ai.model = env_model
    return cfg


DEFAULT_CONFIG_TEMPLATE = """\
# DevPilot configuration - https://github.com/KrishnaVipul14/DevPilot
# Paths/globs (relative to this file) excluded from analysis, in addition to
# virtualenvs, node_modules, build output and other common directories.
exclude: []

analyzers:
  code_health:
    enabled: true
    max_complexity: 12        # ruff C901 threshold
    max_function_lines: 80
    max_parameters: 7
  dependencies:
    enabled: true
    engine: osv               # osv (direct OSV.dev query) or pip-audit
    check_outdated: false     # also report newer releases from PyPI (info only)
  setup_doctor:
    enabled: true
  documentation:
    enabled: true

ai:
  enabled: true
  provider: groq              # key read from GROQ_API_KEY (never stored here)

verify:
  timeout: 180                # seconds per verification command
  run_tests: true
"""


def state_dir(root: Path) -> Path:
    return root / STATE_DIR
