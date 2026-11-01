"""Repository configuration (``devpilot.yml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

CONFIG_FILENAMES = ("devpilot.yml", "devpilot.yaml", ".devpilot.yml")
STATE_DIR = ".devpilot"

DEFAULT_EXCLUDES = [
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".devpilot", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "build", "dist", "site-packages", ".next", ".eggs",
]

DEFAULT_RUFF_SELECT = [
    "F",      # pyflakes: unused imports/variables, undefined names, ...
    "E9",     # syntax / IO errors
    "B",      # bugbear: likely bugs and design problems
    "C901",   # cyclomatic complexity
    "S102",   # use of exec
    "S307",   # use of eval
    "S602",   # subprocess with shell=True
    "S506",   # unsafe yaml.load
    "E722",   # bare except
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


def load_config(root: Path) -> DevPilotConfig:
    path = find_config(root)
    if path is None:
        return DevPilotConfig()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping at the top level")
    try:
        return DevPilotConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {path.name}:\n{exc}") from exc


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
