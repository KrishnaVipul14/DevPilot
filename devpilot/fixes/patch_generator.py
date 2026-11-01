"""Patch generation engine.

Supports:
1. Deterministic fixes (Ruff safe edit ranges, vulnerable dependency version bumps,
   and missing `.env.example` variable entries) — works 100% offline without AI.
2. AI-assisted search-and-replace patch generation via the configured AI provider.

Never modifies the user's working tree during proposal. Produces a unified diff and
records the proposed file contents + original SHA-256 hashes in SQLite.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from devpilot.ai.context_builder import build_finding_context
from devpilot.ai.prompts import PATCH_SYSTEM_PROMPT, build_patch_user_prompt
from devpilot.ai.provider import AIProviderError, get_ai_provider
from devpilot.core.context import RepoContext, is_sensitive_file
from devpilot.core.models import Finding
from devpilot.memory.database import MemoryDB


class PatchError(Exception):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unified_diff_text(rel_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        n=3,
    )
    return "".join(diff)


def _line_col_to_offset(text: str, row: int, col: int) -> int:
    """Convert 1-based row and 1-based column (Ruff JSON convention) to character offset."""
    lines = text.splitlines(keepends=True)
    offset = sum(len(lines[i]) for i in range(min(row - 1, len(lines))))
    return offset + max(0, col - 1)


def _apply_ruff_edits(original: str, fix_data: dict[str, Any]) -> tuple[str, str] | None:
    edits = fix_data.get("edits") or []
    if not edits:
        return None
    spans: list[tuple[int, int, str]] = []
    for e in edits:
        loc = e.get("location") or {}
        end = e.get("end_location") or {}
        if not loc or not end:
            return None
        start_off = _line_col_to_offset(original, int(loc["row"]), int(loc["column"]))
        end_off = _line_col_to_offset(original, int(end["row"]), int(end["column"]))
        spans.append((start_off, end_off, str(e.get("content", ""))))
    spans.sort(key=lambda s: s[0], reverse=True)
    updated = original
    for s, e, content in spans:
        updated = updated[:s] + content + updated[e:]
    msg = str(fix_data.get("message") or "Apply safe Ruff fix")
    return updated, msg


def _try_deterministic_fix(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    """Return `(target_file, original_text, updated_text, summary)` if a safe deterministic fix exists."""
    # Case 1: Ruff safe edit in metadata
    fix_meta = (finding.metadata or {}).get("fix")
    if finding.file and fix_meta and isinstance(fix_meta, dict):
        orig = ctx.read_text(finding.file)
        if orig is not None:
            res = _apply_ruff_edits(orig, fix_meta)
            if res and res[0] != orig:
                return finding.file, orig, res[0], res[1]

    # Case 2: Vulnerable dependency with known fixed version in requirements.txt
    if finding.module == "dependencies" and finding.rule == "vulnerable-dependency" and finding.file:
        fixes = (finding.metadata or {}).get("fixed_versions") or []
        pkg = (finding.metadata or {}).get("package")
        installed = (finding.metadata or {}).get("installed_version")
        orig = ctx.read_text(finding.file)
        if fixes and pkg and installed and orig:
            target_ver = str(fixes[0])
            pattern = re.compile(
                rf"^(\s*{re.escape(str(pkg))}\s*===?\s*){re.escape(str(installed))}(\b.*)$",
                re.IGNORECASE | re.MULTILINE,
            )
            updated, count = pattern.subn(rf"\g<1>{target_ver}\g<2>", orig, count=1)
            if count > 0 and updated != orig:
                return (
                    finding.file,
                    orig,
                    updated,
                    f"Upgrade {pkg} from {installed} to fixed version {target_ver}",
                )

    # Case 3: Missing variable in .env.example
    if finding.module == "setup_doctor" and finding.rule == "env-missing-from-example":
        var = (finding.metadata or {}).get("variable")
        example_file = (finding.metadata or {}).get("example_file") or ".env.example"
        orig = ctx.read_text(example_file)
        if var and orig is not None and f"{var}=" not in orig:
            suffix = "" if orig.endswith("\n") or not orig else "\n"
            updated = f"{orig}{suffix}{var}=\n"
            return (
                example_file,
                orig,
                updated,
                f"Document `{var}=` placeholder in {example_file}",
            )

    return None


def _try_ai_fix(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str]:
    if not finding.file or is_sensitive_file(finding.file):
        raise PatchError("Finding does not reference a modifiable source file.")
    orig = ctx.read_text(finding.file)
    if orig is None:
        raise PatchError(f"Could not read file `{finding.file}`.")

    provider = get_ai_provider(ctx.config)
    st = provider.status()
    if not st.available:
        raise PatchError(f"No deterministic fix available for `{finding.rule}` and AI is unavailable ({st.reason}).")

    context = build_finding_context(ctx, finding)
    try:
        raw = provider.generate_json(
            PATCH_SYSTEM_PROMPT,
            build_patch_user_prompt(context),
            timeout=ctx.config.ai.timeout,
        )
    except AIProviderError as exc:
        raise PatchError(str(exc)) from exc

    replacements = raw.get("Replacements") or raw.get("replacements") or []
    if not isinstance(replacements, list) or not replacements:
        raise PatchError("AI did not return any valid search/replace edits.")

    updated = orig
    for item in replacements:
        if not isinstance(item, dict):
            continue
        search = str(item.get("search") or "")
        replace = str(item.get("replace") or "")
        if not search:
            continue
        if search in updated:
            updated = updated.replace(search, replace, 1)
        elif search.strip() in updated:
            updated = updated.replace(search.strip(), replace.strip(), 1)
        else:
            raise PatchError("AI proposed a search block that did not match the exact file contents.")

    if updated == orig:
        raise PatchError("Proposed edit produced no changes.")

    if finding.file.endswith(".py"):
        try:
            ast.parse(updated, filename=finding.file)
        except SyntaxError as exc:
            raise PatchError(f"Rejected AI patch because it introduced a Python syntax error: {exc.msg}") from exc

    summary = str(raw.get("summary") or f"AI proposed fix for {finding.id} ({finding.title})")
    return finding.file, orig, updated, summary


def propose_patch(
    ctx: RepoContext,
    finding: Finding,
    engine: Literal["auto", "ruff", "ai"] = "auto",
) -> dict[str, Any]:
    det = _try_deterministic_fix(ctx, finding) if engine in ("auto", "ruff") else None
    if det is not None:
        target_file, orig, updated, summary = det
        used_engine = "ruff"
    elif engine == "ruff":
        raise PatchError(f"Finding `{finding.id}` (`{finding.rule}`) does not have a deterministic auto-fix.")
    else:
        target_file, orig, updated, summary = _try_ai_fix(ctx, finding)
        used_engine = "ai"

    diff = unified_diff_text(target_file, orig, updated)
    if not diff.strip():
        raise PatchError("Generated patch is empty.")

    patch_id = "patch-" + uuid.uuid4().hex[:8]
    patch_dict: dict[str, Any] = {
        "patch_id": patch_id,
        "finding_id": finding.id,
        "fingerprint": finding.fingerprint,
        "title": finding.title,
        "engine": used_engine,
        "summary": summary,
        "status": "proposed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "diff": diff,
        "files": [target_file],
        "verification": None,
    }
    db = MemoryDB(ctx.root)
    db.save_patch(
        patch_dict,
        edits={target_file: updated},
        file_hashes={target_file: sha256_text(orig)},
    )
    return patch_dict
