"""Repository intelligence graph (static, AST-based).

Nodes: modules, classes, functions, tests and HTTP routes.
Edges: ``imports`` (module→module), ``defines`` (module/class→def),
``calls`` (def→def, statically resolved or *inferred* by unique method name),
``routes_to`` (route→handler).

Limitations: this is static analysis. Dynamic dispatch, monkey patching,
reflection, string-based imports and framework magic are not followed;
relationships resolved only by method name are marked ``inferred``.
"""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from devpilot.core.context import RepoContext

ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "route", "api_route", "websocket"}
GRAPH_LIMITATIONS = [
    "Call relationships are derived statically from the AST; dynamic dispatch, reflection and runtime "
    "monkey-patching are not detected.",
    "Edges marked 'inferred' were matched by method name only and may be wrong.",
    "Routes are detected from decorator patterns such as @app.get('/path') / @router.route('/path').",
]


@dataclass
class Node:
    id: str
    kind: str  # module | class | function | test | route
    name: str
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    module: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    kind: str  # imports | defines | calls | routes_to
    certainty: str = "resolved"  # resolved | inferred


def module_name(rel: str) -> str:
    path = rel.removesuffix(".py")
    path = path.removeprefix("src/")
    parts = path.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel}" or name == "conftest.py"


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    a = node.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    n_defaults = len(a.defaults)
    required = positional[: len(positional) - n_defaults] if n_defaults else positional
    return {
        "params": positional + [x.arg for x in a.kwonlyargs],
        "positional": positional,
        "required": [p for p in required if p not in ("self", "cls")],
        "kwonly": [x.arg for x in a.kwonlyargs],
        "kwonly_required": [x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=False) if d is None],
        "varargs": a.vararg is not None,
        "varkw": a.kwarg is not None,
        "signature": _format_signature(node),
    }


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        return f"{node.name}({ast.unparse(node.args)})"
    except Exception:  # noqa: BLE001
        return f"{node.name}(...)"


class _ModuleIndex:
    """Per-module symbol table: definitions and import aliases."""

    def __init__(self, mod: str, rel: str, tree: ast.Module, is_pkg: bool):
        self.mod, self.rel, self.tree, self.is_pkg = mod, rel, tree, is_pkg
        self.defs: dict[str, str] = {}  # qualified name -> node id
        self.aliases: dict[str, str] = {}  # local name -> "module" or "module:name" (unresolved yet)
        self.module_imports: list[tuple[str, int]] = []

    def package(self) -> str:
        return self.mod if self.is_pkg else self.mod.rpartition(".")[0]

    def resolve_relative(self, module: str | None, level: int) -> str:
        if level == 0:
            return module or ""
        base = self.package().split(".") if self.package() else []
        if level > 1:
            base = base[: len(base) - (level - 1)]
        return ".".join([*base, module] if module else base)


class RepoGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._rev: dict[str, list[Edge]] | None = None
        self._fwd: dict[str, list[Edge]] | None = None

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, ctx: RepoContext) -> RepoGraph:
        graph = cls()
        indexes: dict[str, _ModuleIndex] = {}
        for rel in ctx.python_files:
            tree = ctx.parse(rel)
            if tree is None:
                continue
            mod = module_name(rel)
            idx = _ModuleIndex(mod, rel, tree, rel.endswith("__init__.py"))
            indexes[mod] = idx
            graph._add(Node(id=mod, kind="module", name=mod, file=rel, line=1, module=mod,
                            meta={"is_test": is_test_file(rel)}))
            graph._collect_defs(idx, tree.body, prefix="", parent=mod, test_file=is_test_file(rel))
        for idx in indexes.values():
            graph._collect_imports(idx, indexes)
        method_index = graph._method_name_index()
        for idx in indexes.values():
            _CallVisitor(graph, idx, indexes, method_index).visit(idx.tree)
        graph._dedupe_edges()
        return graph

    def _add(self, node: Node) -> None:
        self.nodes[node.id] = node

    def _collect_defs(self, idx: _ModuleIndex, body: list[ast.stmt], prefix: str, parent: str,
                      test_file: bool, in_test_class: bool = False) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.If, ast.Try)):
                inner = list(stmt.body) + list(getattr(stmt, "orelse", [])) + list(getattr(stmt, "finalbody", []))
                for handler in getattr(stmt, "handlers", []):
                    inner += handler.body
                self._collect_defs(idx, inner, prefix, parent, test_file, in_test_class)
                continue
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            qual = f"{prefix}{stmt.name}"
            node_id = f"{idx.mod}:{qual}"
            if isinstance(stmt, ast.ClassDef):
                kind, meta = "class", {"bases": [ast.unparse(b) for b in stmt.bases]}
            else:
                is_test = test_file and stmt.name.startswith("test") and (prefix == "" or in_test_class)
                kind, meta = ("test" if is_test else "function"), _signature(stmt)
                meta["async"] = isinstance(stmt, ast.AsyncFunctionDef)
                if is_test:
                    meta["nodeid"] = f"{idx.rel}::{qual.replace('.', '::')}"
            self._add(Node(id=node_id, kind=kind, name=qual, file=idx.rel, line=stmt.lineno,
                           end_line=stmt.end_lineno, module=idx.mod, meta=meta))
            self.edges.append(Edge(parent, node_id, "defines"))
            idx.defs[qual] = node_id
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._collect_routes(idx, stmt, node_id)
            self._collect_defs(idx, stmt.body, f"{qual}.", node_id, test_file,
                               in_test_class=isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"))

    def _collect_routes(self, idx: _ModuleIndex, fn: ast.FunctionDef | ast.AsyncFunctionDef, fn_id: str) -> None:
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            attr = dec.func.attr.lower()
            if attr not in ROUTE_METHODS or not dec.args:
                continue
            path = dec.args[0]
            if not (isinstance(path, ast.Constant) and isinstance(path.value, str) and path.value.startswith("/")):
                continue
            methods = [attr.upper()] if attr not in ("route", "api_route") else ["GET"]
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [str(e.value).upper() for e in kw.value.elts if isinstance(e, ast.Constant)]
            for method in methods:
                rid = f"route:{method} {path.value}"
                self._add(Node(id=rid, kind="route", name=f"{method} {path.value}", file=idx.rel,
                               line=dec.lineno, module=idx.mod,
                               meta={"method": method, "path": path.value, "handler": fn_id}))
                self.edges.append(Edge(rid, fn_id, "routes_to"))

    def _collect_imports(self, idx: _ModuleIndex, indexes: dict[str, _ModuleIndex]) -> None:
        for node in ast.walk(idx.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = self._longest_module(alias.name, indexes)
                    if alias.asname:
                        idx.aliases[alias.asname] = alias.name
                    else:
                        idx.aliases[alias.name.split(".")[0]] = alias.name.split(".")[0]
                    if target:
                        self.edges.append(Edge(idx.mod, target, "imports"))
            elif isinstance(node, ast.ImportFrom):
                base = idx.resolve_relative(node.module, node.level)
                base_mod = self._longest_module(base, indexes) if base else None
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    sub = f"{base}.{alias.name}" if base else alias.name
                    if sub in indexes:
                        idx.aliases[local] = sub
                        self.edges.append(Edge(idx.mod, sub, "imports"))
                    else:
                        idx.aliases[local] = f"{base}:{alias.name}"
                        if base_mod:
                            self.edges.append(Edge(idx.mod, base_mod, "imports"))

    @staticmethod
    def _longest_module(name: str, indexes: dict[str, _ModuleIndex]) -> str | None:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in indexes:
                return cand
        return None

    def _method_name_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for node in self.nodes.values():
            if node.kind == "function" and "." in node.name:
                index.setdefault(node.name.rsplit(".", 1)[-1], []).append(node.id)
        return index

    def _dedupe_edges(self) -> None:
        seen: dict[tuple[str, str, str], Edge] = {}
        for e in self.edges:
            if e.source == e.target and e.kind != "calls":
                continue
            key = (e.source, e.target, e.kind)
            if key not in seen or (seen[key].certainty == "inferred" and e.certainty == "resolved"):
                seen[key] = e
        self.edges = list(seen.values())
        self._rev = self._fwd = None

    # ------------------------------------------------------------------ query
    def _index(self) -> None:
        self._rev, self._fwd = {}, {}
        for e in self.edges:
            self._rev.setdefault(e.target, []).append(e)
            self._fwd.setdefault(e.source, []).append(e)

    def incoming(self, node_id: str, kinds: Iterable[str]) -> list[Edge]:
        if self._rev is None:
            self._index()
        kinds = set(kinds)
        return [e for e in (self._rev or {}).get(node_id, []) if e.kind in kinds]

    def outgoing(self, node_id: str, kinds: Iterable[str]) -> list[Edge]:
        if self._fwd is None:
            self._index()
        kinds = set(kinds)
        return [e for e in (self._fwd or {}).get(node_id, []) if e.kind in kinds]

    def transitive_callers(self, node_id: str, max_depth: int = 4) -> dict[str, tuple[int, str]]:
        """Return {caller_id: (depth, certainty)} following reverse call/route edges."""
        result: dict[str, tuple[int, str]] = {}
        queue: deque[tuple[str, int, str]] = deque([(node_id, 0, "resolved")])
        while queue:
            current, depth, certainty = queue.popleft()
            if depth >= max_depth:
                continue
            for e in self.incoming(current, ("calls", "routes_to")):
                cert = "inferred" if "inferred" in (certainty, e.certainty) else "resolved"
                if e.source not in result or (result[e.source][1] == "inferred" and cert == "resolved"):
                    result[e.source] = (depth + 1, cert)
                    queue.append((e.source, depth + 1, cert))
        result.pop(node_id, None)
        return result

    def importers(self, module: str) -> list[str]:
        return sorted({e.source for e in self.incoming(module, ("imports",))})

    def symbol_at(self, file: str, line: int) -> Node | None:
        best: Node | None = None
        for node in self.nodes.values():
            if node.file != file or node.kind not in ("function", "class", "test") or node.line is None:
                continue
            if node.line <= line <= (node.end_line or node.line):
                if best is None or (node.end_line or 0) - node.line < (best.end_line or 0) - (best.line or 0):
                    best = node
        return best

    def find(self, name: str) -> list[Node]:
        """Find definitions by id, qualified name or short name."""
        if name in self.nodes:
            return [self.nodes[name]]
        return [n for n in self.nodes.values() if n.kind in ("function", "class", "test")
                and (n.name == name or n.name.rsplit(".", 1)[-1] == name)]

    def summary(self) -> dict[str, int]:
        counts = {"modules": 0, "functions": 0, "classes": 0, "routes": 0, "tests": 0}
        key = {"module": "modules", "function": "functions", "class": "classes", "route": "routes", "test": "tests"}
        for n in self.nodes.values():
            counts[key[n.kind]] += 1
        counts["edges"] = len(self.edges)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [asdict(n) for n in self.nodes.values()],
                "edges": [asdict(e) for e in self.edges],
                "summary": self.summary(), "limitations": GRAPH_LIMITATIONS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoGraph:
        graph = cls()
        for n in data.get("nodes", []):
            graph._add(Node(**n))
        graph.edges = [Edge(**e) for e in data.get("edges", [])]
        return graph


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, graph: RepoGraph, idx: _ModuleIndex, indexes: dict[str, _ModuleIndex],
                 method_index: dict[str, list[str]]):
        self.g, self.idx, self.indexes, self.method_index = graph, idx, indexes, method_index
        self.stack: list[str] = []  # qualified names of enclosing defs
        self.class_stack: list[str] = []

    @property
    def current(self) -> str:
        return f"{self.idx.mod}:{self.stack[-1]}" if self.stack else self.idx.mod

    def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        # decorators belong to the enclosing scope's view but express a dependency of the def itself
        qual = f"{self.stack[-1]}.{node.name}" if self.stack else node.name
        self.stack.append(qual)
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            self._link(target)
        if isinstance(node, ast.ClassDef):
            self.class_stack.append(qual)
        for child in node.body:
            self.visit(child)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                self.visit(d)
        if isinstance(node, ast.ClassDef):
            self.class_stack.pop()
        self.stack.pop()

    visit_FunctionDef = _visit_def
    visit_AsyncFunctionDef = _visit_def
    visit_ClassDef = _visit_def

    def visit_Call(self, node: ast.Call) -> None:
        self._link(node.func)
        # functions passed by reference (callbacks, Depends(get_user), ...)
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, (ast.Name, ast.Attribute)):
                self._link(arg, reference=True)
        self.generic_visit(node)

    def _link(self, func: ast.AST, reference: bool = False) -> None:
        target, certainty = self._resolve(func)
        if target and target in self.g.nodes and self.g.nodes[target].kind != "module":
            if reference and certainty == "resolved":
                certainty = "inferred"
            self.g.edges.append(Edge(self.current, target, "calls", certainty))

    def _resolve_alias(self, ref: str) -> str | None:
        if ":" in ref:
            mod, name = ref.split(":", 1)
            real_mod = RepoGraph._longest_module(mod, self.indexes) if mod else None
            if real_mod and real_mod in self.indexes:
                found = self.indexes[real_mod].defs.get(name)
                if found:
                    return found
                # re-exported via package __init__
                alias = self.indexes[real_mod].aliases.get(name)
                if alias and alias != ref:
                    return self._resolve_alias(alias)
            return None
        return ref if ref in self.indexes else None

    def _resolve_name(self, func: ast.Name) -> str | None:
        for depth in range(len(self.stack), -1, -1):
            prefix = ".".join(self.stack[:depth])
            qual = f"{prefix}.{func.id}" if prefix else func.id
            if qual in self.idx.defs and not (self.class_stack and prefix == self.class_stack[-1]):
                return self.idx.defs[qual]
        alias = self.idx.aliases.get(func.id)
        return self._resolve_alias(alias) if alias else None

    def _resolve_attribute(self, base: str, attr: str) -> str | None:
        if base in ("self", "cls") and self.class_stack:
            cand = self.idx.defs.get(f"{self.class_stack[-1]}.{attr}")
            if cand:
                return cand
        if base in self.idx.defs:
            cand = self.idx.defs.get(f"{base}.{attr}")
            if cand:
                return cand
        alias = self.idx.aliases.get(base)
        if not alias:
            return None
        if ":" not in alias and alias in self.indexes:
            cand = self.indexes[alias].defs.get(attr)
            if cand:
                return cand
            sub_alias = self.indexes[alias].aliases.get(attr)
            return self._resolve_alias(sub_alias) if sub_alias else None
        cls_id = self._resolve_alias(alias)
        if cls_id:
            mod, qual = cls_id.split(":", 1)
            return self.indexes[mod].defs.get(f"{qual}.{attr}") if mod in self.indexes else None
        return None

    def _resolve(self, func: ast.AST) -> tuple[str | None, str]:
        if isinstance(func, ast.Name):
            return self._resolve_name(func), "resolved"
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                res = self._resolve_attribute(func.value.id, func.attr)
                if res:
                    return res, "resolved"
            candidates = self.method_index.get(func.attr, [])
            if len(candidates) == 1 and not func.attr.startswith("__"):
                return candidates[0], "inferred"
        return None, "resolved"
