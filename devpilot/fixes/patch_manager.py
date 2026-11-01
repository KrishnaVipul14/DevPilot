"""Patch lifecycle manager: verify, apply (with hash safety checks), and discard."""

from __future__ import annotations

from typing import Any

from devpilot.core.context import RepoContext
from devpilot.fixes.patch_generator import PatchError, sha256_text
from devpilot.fixes.verifier import verify_patch_edits
from devpilot.memory.database import MemoryDB


def verify_patch(ctx: RepoContext, ref: str) -> dict[str, Any]:
    db = MemoryDB(ctx.root)
    rec = db.find_patch_for_ref(ref)
    if rec is None:
        raise PatchError(f"No proposed patch found for `{ref}`. Run `devpilot fix {ref}` first.")
    patch, edits, file_hashes = rec
    if patch["status"] == "discarded":
        raise PatchError(f"Patch `{patch['patch_id']}` was discarded.")

    verification = verify_patch_edits(ctx, edits)
    patch["verification"] = verification
    patch["status"] = verification["status"]
    db.save_patch(patch, edits, file_hashes)
    return patch


def apply_patch(ctx: RepoContext, ref: str) -> dict[str, Any]:
    db = MemoryDB(ctx.root)
    rec = db.find_patch_for_ref(ref)
    if rec is None:
        raise PatchError(f"No patch found for `{ref}`.")
    patch, edits, file_hashes = rec
    if patch["status"] == "discarded":
        raise PatchError(f"Patch `{patch['patch_id']}` was discarded and cannot be applied.")
    if patch["status"] == "failed":
        raise PatchError(f"Patch `{patch['patch_id']}` failed verification and cannot be applied.")

    for rel, expected_hash in file_hashes.items():
        current = ctx.read_text(rel)
        is_new_file = expected_hash in (sha256_text(""), "")
        if is_new_file:
            if current is not None and current != "":
                raise PatchError(
                    f"Refusing to apply patch: `{rel}` was proposed as a new file, but already exists on disk."
                )
        else:
            if current is None or sha256_text(current) != expected_hash:
                raise PatchError(
                    f"Refusing to apply patch: `{rel}` has changed since patch `{patch['patch_id']}` was proposed."
                )

    for rel, content in edits.items():
        target = ctx.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    patch["status"] = "applied"
    db.save_patch(patch, edits, file_hashes)
    return patch


def discard_patch(ctx: RepoContext, ref: str) -> dict[str, Any]:
    db = MemoryDB(ctx.root)
    rec = db.find_patch_for_ref(ref)
    if rec is None:
        raise PatchError(f"No patch found for `{ref}`.")
    patch, edits, file_hashes = rec
    patch["status"] = "discarded"
    db.save_patch(patch, edits, file_hashes)
    return patch
