"""Small AST helpers shared by analyzers and the repository graph."""

from __future__ import annotations

import ast
from collections.abc import Iterator

FuncNode = ast.FunctionDef | ast.AsyncFunctionDef


def iter_defs(tree: ast.AST, prefix: str = "") -> Iterator[tuple[str, ast.AST]]:
    """Yield (qualified_name, node) for classes and functions, nested included."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qual = f"{prefix}{node.name}"
            yield qual, node
            yield from iter_defs(node, prefix=f"{qual}.")
        elif not isinstance(node, (ast.Lambda,)):
            # descend into if/try/with blocks at module/class level
            if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                yield from iter_defs(node, prefix=prefix)


def enclosing_symbol(tree: ast.AST | None, line: int | None) -> str | None:
    """Innermost function/class containing ``line``."""
    if tree is None or line is None:
        return None
    best: tuple[int, str] | None = None
    for qual, node in iter_defs(tree):
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None:
            continue
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start = min(start, min(d.lineno for d in decorators))
        if start <= line <= end:
            span = end - start
            if best is None or span < best[0]:
                best = (span, qual)
    return best[1] if best else None
