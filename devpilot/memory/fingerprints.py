"""Stable finding fingerprints.

A fingerprint identifies "the same problem" across scans even when line
numbers shift. It hashes the analyzer module, rule, file and a *line-independent
anchor* (normalised source text of the offending line, the enclosing symbol,
or an analyzer-specific key such as ``package@version:advisory``). Duplicate
fingerprints within one scan are disambiguated by occurrence order.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from devpilot.core.models import Finding

_WS = re.compile(r"\s+")


def normalize_code(text: str) -> str:
    return _WS.sub(" ", text.strip())


def compute_fingerprint(module: str, rule: str, file: str | None, anchor: str) -> str:
    raw = "\x1f".join([module, rule, file or "", normalize_code(anchor)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def assign_fingerprints(findings: list[Finding], anchors: list[str]) -> None:
    """Assign fingerprints in-place; duplicates get an occurrence suffix."""
    seen: Counter[str] = Counter()
    for finding, anchor in zip(findings, anchors, strict=False):
        base = compute_fingerprint(finding.module, finding.rule, finding.file, anchor)
        seen[base] += 1
        finding.fingerprint = base if seen[base] == 1 else f"{base}-{seen[base]}"
