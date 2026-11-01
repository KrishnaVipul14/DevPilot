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
    # Normalize newlines so hashes match regardless of CRLF vs LF line endings
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def _fix_ruff(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    fix_meta = (finding.metadata or {}).get("fix")
    if finding.file and fix_meta and isinstance(fix_meta, dict):
        orig = ctx.read_text(finding.file)
        if orig is not None:
            res = _apply_ruff_edits(orig, fix_meta)
            if res and res[0] != orig:
                return finding.file, orig, res[0], res[1]
    return None


def _upgrade_requirements(pkg: str, installed: str, target_ver: str, orig: str) -> str | None:
    pattern = re.compile(
        rf"^(\s*{re.escape(pkg)}\s*===?\s*){re.escape(installed)}(\b.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    updated, count = pattern.subn(rf"\g<1>{target_ver}\g<2>", orig, count=1)
    return updated if count > 0 and updated != orig else None


def _upgrade_package_json(pkg: str, target_ver: str, orig: str) -> str | None:
    pattern = re.compile(rf'("{re.escape(pkg)}"\s*:\s*")[^"]+(")')
    updated, count = pattern.subn(rf"\g<1>{target_ver}\g<2>", orig, count=1)
    return updated if count > 0 and updated != orig else None


def _upgrade_gradle(pkg: str, target_ver: str, orig: str) -> str | None:
    pattern = re.compile(rf'([\'"]{re.escape(pkg)}:)[^\'"]+([\'"])')
    updated, count = pattern.subn(rf"\g<1>{target_ver}\g<2>", orig, count=1)
    return updated if count > 0 and updated != orig else None


def _upgrade_pom(pkg: str, target_ver: str, orig: str) -> str | None:
    aid = pkg.split(":", 1)[1] if ":" in pkg else pkg
    pattern = re.compile(
        rf"(<artifactId>{re.escape(aid)}</artifactId>[\s\S]*?<version>)[^<]+(</version>)",
        re.MULTILINE,
    )
    updated, count = pattern.subn(rf"\g<1>{target_ver}\g<2>", orig, count=1)
    return updated if count > 0 and updated != orig else None


def _fix_vulnerable_dep(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    if finding.module != "dependencies" or finding.rule != "vulnerable-dependency" or not finding.file:
        return None
    fixes = (finding.metadata or {}).get("fixed_versions") or []
    pkg = (finding.metadata or {}).get("package")
    installed = (finding.metadata or {}).get("installed_version")
    orig = ctx.read_text(finding.file)
    if not (fixes and pkg and installed and orig):
        return None
    target_ver = str(fixes[0])
    fname = finding.file.lower()
    updated: str | None = None
    if "requirements" in fname or fname.endswith(".txt"):
        updated = _upgrade_requirements(str(pkg), str(installed), target_ver, orig)
    elif fname.endswith("package.json"):
        updated = _upgrade_package_json(str(pkg), target_ver, orig)
    elif fname.endswith((".gradle", ".gradle.kts")):
        updated = _upgrade_gradle(str(pkg), target_ver, orig)
    elif fname.endswith("pom.xml"):
        updated = _upgrade_pom(str(pkg), target_ver, orig)

    if updated is not None:
        return (finding.file, orig, updated, f"Upgrade {pkg} to fixed version {target_ver}")
    return None


def _fix_env_setup(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    if finding.module == "setup_doctor" and finding.rule == "env-missing-from-example":
        var = (finding.metadata or {}).get("variable")
        example_file = (finding.metadata or {}).get("example_file") or ".env.example"
        orig = ctx.read_text(example_file) or ""
        if var and f"{var}=" not in orig:
            suffix = "" if orig.endswith("\n") or not orig else "\n"
            updated = f"{orig}{suffix}{var}=\n"
            return (
                example_file,
                orig,
                updated,
                f"Document `{var}=` placeholder in {example_file}",
            )
    if finding.module == "setup_doctor" and finding.rule == "env-example-missing":
        variables = (finding.metadata or {}).get("variables") or []
        example_file = ".env.example"
        orig = ctx.read_text(example_file) or ""
        lines = [f"{v}=" for v in sorted(variables)]
        content = "\n".join(lines) + ("\n" if lines else "")
        return (
            example_file,
            orig,
            content,
            f"Create {example_file} with placeholders for {len(variables)} variables",
        )
    return None


def _fix_android(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    if not finding.file:
        return None
    orig = ctx.read_text(finding.file)
    if not orig:
        return None
    if finding.rule == "android-cleartext-traffic" and 'android:usesCleartextTraffic="true"' in orig:
        updated = orig.replace(
            'android:usesCleartextTraffic="true"', 'android:usesCleartextTraffic="false"', 1
        )
        return (
            finding.file,
            orig,
            updated,
            "Disable cleartext HTTP traffic in AndroidManifest.xml (enforce HTTPS)",
        )
    if finding.rule == "android-allow-backup" and 'android:allowBackup="true"' in orig:
        updated = orig.replace('android:allowBackup="true"', 'android:allowBackup="false"', 1)
        return finding.file, orig, updated, "Disable adb backup in AndroidManifest.xml"
    if finding.rule == "android-debuggable" and 'android:debuggable="true"' in orig:
        updated = orig.replace('android:debuggable="true"', 'android:debuggable="false"', 1)
        return finding.file, orig, updated, "Set android:debuggable='false' in AndroidManifest.xml"
    if finding.rule == "android-insecure-repo-url":
        url = (finding.metadata or {}).get("url")
        if url and url in orig and url.startswith("http://"):
            secure_url = "https://" + url[len("http://") :]
            updated = orig.replace(url, secure_url, 1)
            return finding.file, orig, updated, f"Upgrade repository URL `{url}` to secure HTTPS"
    return None


def _try_deterministic_fix(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str] | None:
    """Return `(target_file, original_text, updated_text, summary)` if a safe deterministic fix exists."""
    for fn in (_fix_ruff, _fix_vulnerable_dep, _fix_env_setup, _fix_android):
        res = fn(ctx, finding)
        if res is not None:
            return res
    return None


def _apply_search_replace_edits(orig: str, replacements: list[Any]) -> str:
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
    return updated


def _validate_updated_syntax(file: str, updated: str) -> None:
    if file.endswith(".py"):
        try:
            ast.parse(updated, filename=file)
        except SyntaxError as exc:
            raise PatchError(
                f"Rejected AI patch because it introduced a Python syntax error: {exc.msg}"
            ) from exc
    elif file.endswith(".json"):
        import json

        try:
            json.loads(updated)
        except Exception as exc:  # noqa: BLE001
            raise PatchError(f"Rejected AI patch because it introduced a JSON syntax error: {exc}") from exc
    elif file.endswith(".xml"):
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(updated)
        except Exception as exc:  # noqa: BLE001
            raise PatchError(f"Rejected AI patch because it introduced an XML syntax error: {exc}") from exc


def _try_ai_fix(ctx: RepoContext, finding: Finding) -> tuple[str, str, str, str]:
    if not finding.file or is_sensitive_file(finding.file):
        raise PatchError("Finding does not reference a modifiable source file.")
    orig = ctx.read_text(finding.file)
    if orig is None:
        raise PatchError(f"Could not read file `{finding.file}`.")

    provider = get_ai_provider(ctx.config)
    st = provider.status()
    if not st.available:
        raise PatchError(
            f"No deterministic fix available for `{finding.rule}` and AI is unavailable ({st.reason})."
        )

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

    updated = _apply_search_replace_edits(orig, replacements)
    _validate_updated_syntax(finding.file, updated)

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
