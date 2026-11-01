"""Validated data models shared by every DevPilot component.

All analyzers emit :class:`Finding` objects and every scan produces a
:class:`Report`. These models are the single contract between the scanner,
the memory layer, the CLI, the local API server and the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.index(self)


SEVERITY_ORDER: list[Severity] = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(str, Enum):
    NEW = "new"
    EXISTING = "existing"
    REINTRODUCED = "reintroduced"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    FAILED = "failed"
    NOT_VERIFIED = "not_verified"


class AnalyzerState(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    ERROR = "error"


class ScanStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"  # at least one analyzer errored or was skipped
    FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Finding(BaseModel):
    """A single deterministic finding produced by an analyzer."""

    id: str = ""  # Human friendly id assigned per report, e.g. DP001
    fingerprint: str = ""  # Stable across scans (independent of line numbers)
    module: str  # analyzer name, e.g. code_health
    rule: str  # rule identifier, e.g. F401 or env-missing-example
    severity: Severity
    title: str
    file: str | None = None  # POSIX path relative to repository root
    line: int | None = None
    end_line: int | None = None
    column: int | None = None
    symbol: str | None = None  # enclosing function/class if known
    evidence: str
    suggestion: str = ""
    confidence: Confidence = Confidence.HIGH
    status: FindingStatus = FindingStatus.NEW
    verification: VerificationStatus = VerificationStatus.NOT_VERIFIED
    fixable: bool = False  # a deterministic (non-AI) fix is available
    references: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyzerRun(BaseModel):
    name: str
    status: AnalyzerState
    duration_ms: int = 0
    findings: int = 0
    message: str = ""


class RepositoryInfo(BaseModel):
    name: str
    path: str
    git_root: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None


class Summary(BaseModel):
    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_module: dict[str, int] = Field(default_factory=dict)
    health_score: int = 100
    health_formula: str = ""
    files_scanned: int = 0


class MemoryDelta(BaseModel):
    """Comparison against the previous scan of the same repository."""

    previous_scan_id: str | None = None
    new: int = 0
    existing: int = 0
    reintroduced: int = 0
    resolved: int = 0
    severity_changed: int = 0
    resolved_findings: list[dict[str, Any]] = Field(default_factory=list)


class AIExplanation(BaseModel):
    """AI-generated content. Always kept separate from deterministic findings."""

    finding_fingerprint: str
    provider: str
    model: str
    created_at: datetime = Field(default_factory=utcnow)
    summary: str
    root_cause: str
    impact: str
    recommendation: str
    suggested_tests: list[str] = Field(default_factory=list)
    caveats: str = ""


class GraphSummary(BaseModel):
    modules: int = 0
    functions: int = 0
    classes: int = 0
    routes: int = 0
    tests: int = 0
    edges: int = 0


class Report(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tool: str = "devpilot"
    version: str
    scan_id: str
    repository: RepositoryInfo
    started_at: datetime
    finished_at: datetime
    status: ScanStatus
    summary: Summary
    findings: list[Finding]
    analyzers: list[AnalyzerRun]
    graph: GraphSummary | None = None
    memory: MemoryDelta | None = None
    ai: dict[str, AIExplanation] = Field(
        default_factory=dict,
        description="AI explanations keyed by finding fingerprint (non-deterministic).",
    )
    limitations: list[str] = Field(default_factory=list)
