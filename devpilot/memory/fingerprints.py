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
    file_clean = (file or "").replace("\\", "/")
    raw = "\x1f".join([module, rule, file_clean, normalize_code(anchor)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def assign_fingerprints(findings: list[Finding], anchors: list[str]) -> None:
    """Assign stable fingerprints in-place; duplicates get an occurrence suffix."""
    seen: Counter[str] = Counter()
    for idx, finding in enumerate(findings):
        anchor = ""
        if idx < len(anchors) and anchors[idx]:
            anchor = anchors[idx]
        if not anchor.strip():
            meta = finding.metadata or {}
            key_val = meta.get("package") or meta.get("variable") or meta.get("url") or meta.get("name")
            anchor = str(key_val) if key_val else (finding.evidence or finding.title or finding.rule)

        base = compute_fingerprint(finding.module, finding.rule, finding.file, anchor)
        seen[base] += 1
        finding.fingerprint = base if seen[base] == 1 else f"{base}-{seen[base]}"
