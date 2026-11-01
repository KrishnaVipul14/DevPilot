"""Mermaid architecture diagram generator for repository graphs."""

from __future__ import annotations

import re

from devpilot.analyzers.repository_graph import RepoGraph


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def export_mermaid(graph: RepoGraph, max_nodes: int = 40) -> str:
    """Generate a Mermaid `flowchart TD` representation of routes, modules, and functions."""
    lines: list[str] = ["flowchart TD", "    %% DevPilot Architecture Flowchart"]

    routes = [n for n in graph.nodes.values() if n.kind == "route"][:15]
    modules = [
        n for n in graph.nodes.values() if n.kind == "module" and not (n.file or "").startswith("test")
    ][:20]
    classes = [n for n in graph.nodes.values() if n.kind == "class"][:10]

    # Subgraph for API Routes
    if routes:
        lines.append('    subgraph Routes["API Routes"]')
        for r in routes:
            node_id = f"R_{_sanitize(r.id)}"
            clean_label = r.name.replace('"', '\\"')
            lines.append(f'        {node_id}["{clean_label}"]')
        lines.append("    end")

    # Subgraph for Core Modules
    if modules:
        lines.append('    subgraph Modules["Core Modules"]')
        for m in modules:
            node_id = f"M_{_sanitize(m.id)}"
            lines.append(f'        {node_id}["{m.name}"]')
        lines.append("    end")

    # Subgraph for Classes / Domain Models
    if classes:
        lines.append('    subgraph Classes["Classes & Entities"]')
        for c in classes:
            node_id = f"C_{_sanitize(c.id)}"
            lines.append(f'        {node_id}["{c.name}"]')
        lines.append("    end")

    # Edges
    seen_edges: set[tuple[str, str]] = set()
    node_keys = {n.id for n in routes + modules + classes}

    for edge in graph.edges:
        if edge.source in node_keys and edge.target in node_keys:
            s_key = f"{'R_' if edge.source.startswith('route:') else 'M_'}{_sanitize(edge.source)}"
            t_key = f"{'C_' if ':' in edge.target else 'M_'}{_sanitize(edge.target)}"
            pair = (s_key, t_key)
            if pair not in seen_edges and s_key != t_key:
                seen_edges.add(pair)
                label = f" -- {edge.kind} --> "
                lines.append(f"    {s_key}{label}{t_key}")
                if len(seen_edges) >= max_nodes:
                    break

    # If no internal edges matched, connect routes to their containing modules
    if not seen_edges:
        for r in routes:
            if r.module:
                r_key = f"R_{_sanitize(r.id)}"
                m_key = f"M_{_sanitize(r.module)}"
                lines.append(f"    {r_key} --> {m_key}")

    return "\n".join(lines)
