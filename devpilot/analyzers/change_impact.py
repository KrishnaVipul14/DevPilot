"""Change impact analysis (Module C).

Integrates with Git diffs and the Repository Intelligence Graph to identify:
- Modified files and modified functions/classes.
- Potentially affected caller functions and dependent modules.
- Affected HTTP routes/endpoints.
- Relevant tests (resolved call graph edges and inferred module/naming conventions).
- Explainable risk levels (Low, Medium, High, Critical) with concrete evidence.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from devpilot.analyzers.repository_graph import GRAPH_LIMITATIONS, Node, RepoGraph, is_test_file, module_name
from devpilot.core.context import RepoContext
from devpilot.utils import git as gitutil

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_RISK_ORDER = ["low", "medium", "high", "critical"]
_CRITICAL_PATH_RE = re.compile(r"(auth|security|token|jwt|crypto|permission|session|payment|billing|secret|db|migration)",
                               re.IGNORECASE)


def _max_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER.index(a) >= _RISK_ORDER.index(b) else b


def parse_diff_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Parse unified diff (`git diff -U0`) into `{rel_path: {new_line_numbers}}`."""
    changed: dict[str, set[int]] = {}
    current_file: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:].strip()
            changed.setdefault(current_file, set())
        elif raw.startswith("+++ /dev/null"):
            current_file = None
        elif raw.startswith("@@ ") and current_file:
            m = _HUNK_RE.match(raw)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                if count == 0:
                    changed[current_file].add(max(1, start))
                else:
                    for ln in range(start, start + count):
                        changed[current_file].add(ln)
    return changed


def _symbol_impact(graph: RepoGraph, sym: Node) -> dict[str, Any]:
    callers_map = graph.transitive_callers(sym.id, max_depth=4)
    caller_functions: list[str] = []
    routes: list[dict[str, str]] = []
    tests_map: dict[str, dict[str, str]] = {}
    dependent_modules: set[str] = set()

    if sym.module:
        for mod in graph.importers(sym.module):
            dependent_modules.add(mod)

    for caller_id, (_depth, cert) in sorted(callers_map.items()):
        cnode = graph.nodes.get(caller_id)
        if not cnode:
            continue
        if cnode.module and cnode.module != sym.module:
            dependent_modules.add(cnode.module)
        if cnode.kind == "route":
            routes.append({
                "id": cnode.id,
                "method": str(cnode.meta.get("method", "GET")),
                "path": str(cnode.meta.get("path", "")),
                "handler": str(cnode.meta.get("handler", "")),
            })
        elif cnode.kind == "test":
            tests_map[cnode.id] = {
                "id": cnode.id,
                "nodeid": str(cnode.meta.get("nodeid") or f"{cnode.file}::{cnode.name}"),
                "file": cnode.file or "",
                "certainty": cert,
            }
        elif cnode.kind in ("function", "class"):
            caller_functions.append(cnode.id)

    # Also check if any test module imports the symbol's module or its dependent modules
    if sym.module:
        candidate_mods = {sym.module, *dependent_modules}
        for mod_id in candidate_mods:
            for importer in graph.importers(mod_id):
                mnode = graph.nodes.get(importer)
                if mnode and mnode.file and is_test_file(mnode.file):
                    for edge in graph.outgoing(importer, ("defines",)):
                        tnode = graph.nodes.get(edge.target)
                        if tnode and tnode.kind == "test" and tnode.id not in tests_map:
                            tests_map[tnode.id] = {
                                "id": tnode.id,
                                "nodeid": str(tnode.meta.get("nodeid") or f"{tnode.file}::{tnode.name}"),
                                "file": tnode.file or "",
                                "certainty": "inferred",
                            }

    # Assess risk based on transparent rules
    reasons: list[str] = []
    level = "low"
    is_sensitive = bool(_CRITICAL_PATH_RE.search(sym.file or "") or _CRITICAL_PATH_RE.search(sym.name))
    if is_sensitive:
        reasons.append(f"`{sym.name}` is in a security/auth/data-sensitive module or symbol (`{sym.file}`).")
        level = _max_risk(level, "high")

    if routes:
        reasons.append(f"{len(routes)} HTTP endpoint(s) reach `{sym.name}` ({', '.join(r['method'] + ' ' + r['path'] for r in routes[:4])}).")
        level = _max_risk(level, "high" if is_sensitive or len(routes) >= 2 else "medium")

    if caller_functions:
        reasons.append(f"{len(caller_functions)} dependent function(s) call `{sym.name}`.")
        if len(caller_functions) >= 4:
            level = _max_risk(level, "high")
        else:
            level = _max_risk(level, "medium")

    if dependent_modules:
        reasons.append(f"{len(dependent_modules)} module(s) depend on `{sym.module}`.")
        level = _max_risk(level, "medium")

    if not tests_map and (caller_functions or routes or is_sensitive):
        reasons.append(f"No automated tests were found covering `{sym.name}`.")
        level = _max_risk(level, "critical" if (is_sensitive and routes) else "high")
    elif is_sensitive and routes and len(caller_functions) >= 2:
        level = _max_risk(level, "critical")
    elif tests_map:
        reasons.append(f"{len(tests_map)} relevant test(s) identified for verification.")

    if not reasons:
        reasons.append(f"`{sym.name}` has no external callers or routes in the static graph.")

    return {
        "symbol": sym.id,
        "callers": sorted(caller_functions),
        "dependent_modules": sorted(dependent_modules),
        "routes": routes,
        "tests": list(tests_map.values()),
        "risk": {"level": level, "reasons": reasons},
    }


def analyze_symbol_impact(ctx: RepoContext, symbol_query: str, graph: RepoGraph | None = None) -> dict[str, Any]:
    """Compute hypothetical change impact for a named function or class."""
    graph = graph or RepoGraph.build(ctx)
    matches = graph.find(symbol_query)
    changed_symbols: list[dict[str, Any]] = []
    impacts: list[dict[str, Any]] = []
    changed_files_map: dict[str, list[str]] = {}
    all_test_files: set[str] = set()
    overall_level = "low"
    overall_reasons: list[str] = []

    for sym in matches:
        changed_symbols.append({
            "id": sym.id, "name": sym.name, "kind": sym.kind,
            "file": sym.file or "", "line": sym.line,
        })
        if sym.file:
            changed_files_map.setdefault(sym.file, []).append(sym.id)
        imp = _symbol_impact(graph, sym)
        impacts.append(imp)
        overall_level = _max_risk(overall_level, imp["risk"]["level"])
        for r in imp["risk"]["reasons"]:
            if r not in overall_reasons:
                overall_reasons.append(r)
        for t in imp["tests"]:
            if t.get("file"):
                all_test_files.add(t["file"])

    if not matches:
        overall_reasons.append(f"No symbol matching `{symbol_query}` was found in the repository graph.")

    suggested_commands: list[str] = []
    if all_test_files:
        suggested_commands.append(f"pytest {' '.join(sorted(all_test_files))}")
    elif matches:
        suggested_commands.append("pytest")

    return {
        "base": None,
        "mode": "symbol",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "changed_files": [
            {"path": p, "status": "modified", "changed_symbols": syms}
            for p, syms in sorted(changed_files_map.items())
        ],
        "changed_symbols": changed_symbols,
        "impacts": impacts,
        "overall_risk": {"level": overall_level, "reasons": overall_reasons},
        "suggested_commands": suggested_commands,
        "limitations": list(GRAPH_LIMITATIONS),
    }


def analyze_git_impact(ctx: RepoContext, base: str = "HEAD", graph: RepoGraph | None = None) -> dict[str, Any]:
    """Analyze uncommitted working-tree changes (and staged changes) against `base`."""
    graph = graph or RepoGraph.build(ctx)
    now = datetime.now(timezone.utc).isoformat()
    if ctx.git_root is None:
        return {
            "base": base, "mode": "git", "generated_at": now,
            "changed_files": [], "changed_symbols": [], "impacts": [],
            "overall_risk": {"level": "low", "reasons": ["Not a Git repository."]},
            "suggested_commands": [], "limitations": list(GRAPH_LIMITATIONS),
        }

    # Diff working tree vs base; if empty and base=="HEAD", compare HEAD~1..HEAD if available
    diff_res = gitutil.git(["diff", "-U0", base], ctx.root)
    effective_base = base
    if not diff_res.stdout.strip() and base == "HEAD":
        prev_res = gitutil.git(["diff", "-U0", "HEAD~1", "HEAD"], ctx.root)
        if prev_res.ok and prev_res.stdout.strip():
            diff_res = prev_res
            effective_base = "HEAD~1..HEAD"

    changed_lines = parse_diff_changed_lines(diff_res.stdout) if diff_res.ok else {}
    for untracked in gitutil.untracked_files(ctx.root):
        rel = untracked.replace("\\", "/")
        if rel in ctx.files and rel not in changed_lines:
            text = ctx.read_text(rel) or ""
            changed_lines[rel] = set(range(1, len(text.splitlines()) + 2))

    changed_files: list[dict[str, Any]] = []
    changed_symbols_map: dict[str, Node] = {}

    for rel, lines in sorted(changed_lines.items()):
        if not rel.endswith(".py"):
            changed_files.append({"path": rel, "status": "modified", "changed_symbols": []})
            continue
        file_syms: list[str] = []
        for ln in sorted(lines):
            sym = graph.symbol_at(rel, ln)
            if sym and sym.id not in changed_symbols_map:
                changed_symbols_map[sym.id] = sym
                file_syms.append(sym.id)
            elif sym and sym.id not in file_syms:
                file_syms.append(sym.id)
        # If module-level lines changed outside any function/class, include module functions Imported by others
        if not file_syms:
            mod = module_name(rel)
            for edge in graph.outgoing(mod, ("defines",)):
                node = graph.nodes.get(edge.target)
                if node and node.kind in ("function", "class"):
                    changed_symbols_map.setdefault(node.id, node)
                    file_syms.append(node.id)
        changed_files.append({"path": rel, "status": "modified", "changed_symbols": file_syms})

    impacts: list[dict[str, Any]] = []
    all_test_files: set[str] = set()
    overall_level = "low"
    overall_reasons: list[str] = []

    for sym in changed_symbols_map.values():
        if sym.kind == "test" and sym.file:
            all_test_files.add(sym.file)
            continue
        imp = _symbol_impact(graph, sym)
        impacts.append(imp)
        overall_level = _max_risk(overall_level, imp["risk"]["level"])
        for r in imp["risk"]["reasons"]:
            if r not in overall_reasons:
                overall_reasons.append(r)
        for t in imp["tests"]:
            if t.get("file"):
                all_test_files.add(t["file"])

    if not changed_files:
        overall_reasons.append("No modified files detected in Git diff.")
    elif not overall_reasons:
        overall_reasons.append(f"{len(changed_files)} file(s) modified with low static blast radius.")

    suggested_commands: list[str] = []
    if all_test_files:
        suggested_commands.append(f"pytest {' '.join(sorted(all_test_files))}")
    elif changed_files:
        suggested_commands.append("pytest")

    return {
        "base": effective_base,
        "mode": "git",
        "generated_at": now,
        "changed_files": changed_files,
        "changed_symbols": [
            {"id": s.id, "name": s.name, "kind": s.kind, "file": s.file or "", "line": s.line}
            for s in changed_symbols_map.values()
        ],
        "impacts": impacts,
        "overall_risk": {"level": overall_level, "reasons": overall_reasons},
        "suggested_commands": suggested_commands,
        "limitations": list(GRAPH_LIMITATIONS),
    }
