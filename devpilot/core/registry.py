"""Analyzer registry."""

from __future__ import annotations

from devpilot.analyzers.android import AndroidAnalyzer
from devpilot.analyzers.base import Analyzer
from devpilot.analyzers.code_health import CodeHealthAnalyzer
from devpilot.analyzers.dependencies import DependencyAnalyzer
from devpilot.analyzers.documentation import DocumentationAnalyzer
from devpilot.analyzers.setup_doctor import SetupDoctorAnalyzer


def default_analyzers() -> list[Analyzer]:
    return [
        AndroidAnalyzer(),
        CodeHealthAnalyzer(),
        DependencyAnalyzer(),
        SetupDoctorAnalyzer(),
        DocumentationAnalyzer(),
    ]
