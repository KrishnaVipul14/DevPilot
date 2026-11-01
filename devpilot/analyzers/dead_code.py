"""Dead code and orphaned symbol detector based on AST call graphs."""

from __future__ import annotations

import re
from typing import Any

from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.core.context import RepoContext

EXEMPT_NAMES = {
    "__init__",
    "__post_init__",
    "__str__",
    "__repr__",
    "__enter__",
    "__exit__",
    "__call__",
    "__eq__",
    "main",
    "cli",
    "app",
    "run",
    "handler",
    "default",
}


def find_dead_code(
    ctx: RepoContext,
    graph: RepoGraph | None = None,
) -> dict[str, Any]:
    """Find unused functions and orphaned classes with zero incoming call edges."""
    graph = graph or RepoGraph.build(ctx)

    # Collect incoming edges per target node
    incoming_calls: dict[str, int] = {}
    for edge in graph.edges:
        if edge.kind in ("calls", "routes_to"):
            incoming_calls[edge.target] = incoming_calls.get(edge.target, 0) + 1

    # Identify route handlers to exempt
    route_targets: set[str] = set()
    for n in graph.nodes.values():
        if n.kind == "route":
            handler = str(n.meta.get("handler") or "")
            if handler:
                route_targets.add(handler)

    dead_symbols: list[dict[str, Any]] = []
    total_lines = 0

    for n in graph.nodes.values():
        if n.kind not in ("function", "class"):
            continue

        file_path = n.file or ""
        # Skip test files and migration files
        if bool(
            re.search(r"(^|/)(tests?|fixtures?|migrations?)/", file_path) or file_path.startswith("test_")
        ):
            continue

        short_name = n.name.rsplit(".", 1)[-1]
        if short_name.startswith("__") and short_name.endswith("__"):
            continue
        if short_name in EXEMPT_NAMES or short_name in route_targets or n.id in route_targets:
            continue

        # Check callers
        call_count = incoming_calls.get(n.id, 0)
        # Also check short name match in case calls were un-namespaced
        if call_count == 0:
            call_count = incoming_calls.get(short_name, 0)

        if call_count == 0:
            length = ((n.end_line or n.line or 1) - (n.line or 1)) + 1
            total_lines += length
            dead_symbols.append(
                {
                    "id": n.id,
                    "name": n.name,
                    "kind": n.kind,
                    "file": file_path,
                    "line": n.line,
                    "lines_of_code": length,
                    "reason": "Zero incoming callers or route references found in AST graph",
                }
            )

    dead_symbols.sort(key=lambda x: (x["file"], x["line"] or 0))

    return {
        "dead_symbols_count": len(dead_symbols),
        "lines_reclaimable": total_lines,
        "symbols": dead_symbols,
    }
