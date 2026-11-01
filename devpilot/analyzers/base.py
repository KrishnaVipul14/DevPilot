"""Analyzer base class and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from devpilot.core.context import RepoContext
from devpilot.core.models import Finding


class AnalyzerSkipped(Exception):
    """Raised by an analyzer that cannot run in the current environment."""


@dataclass
class AnalyzerOutput:
    findings: list[Finding] = field(default_factory=list)
    # Line-independent anchor per finding, used for stable fingerprints.
    anchors: list[str] = field(default_factory=list)
    message: str = ""

    def add(self, finding: Finding, anchor: str) -> None:
        self.findings.append(finding)
        self.anchors.append(anchor)


class Analyzer(ABC):
    """Every analyzer is independent and returns findings via the common schema."""

    name: str = "base"
    description: str = ""
    requires_network: bool = False

    @abstractmethod
    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        raise NotImplementedError

    def enabled(self, ctx: RepoContext) -> bool:
        section = getattr(ctx.config.analyzers, self.name, None)
        return bool(getattr(section, "enabled", True))
