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
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from devpilot.core.context import RepoContext

ROUTE_METHODS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "head",
    "options",
    "route",
    "api_route",
    "websocket",
}
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
    path = rel.replace("\\", "/").removesuffix(".py")
    path = path.removeprefix("src/")
    parts = path.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1].lower()
    return (
        name.startswith("test_")
        or name.endswith(
            (
                "_test.py",
                ".test.js",
                ".test.jsx",
                ".test.ts",
                ".test.tsx",
                ".spec.js",
                ".spec.jsx",
                ".spec.ts",
                ".spec.tsx",
            )
        )
        or "/tests/" in f"/{rel}"
        or "/__tests__/" in f"/{rel}"
        or name == "conftest.py"
    )


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


def _extract_call_path(call: ast.Call) -> str | None:
    if call.args:
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    for kw in call.keywords:
        if (
            kw.arg in ("path", "rule", "url")
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _extract_call_methods(call: ast.Call, default_m: str) -> list[str]:
    for kw in call.keywords:
        if kw.arg in ("methods", "method") and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
            res = [str(e.value).upper() for e in kw.value.elts if isinstance(e, ast.Constant)]
            if res:
                return res
    return [default_m.upper()]


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
            graph._add(
                Node(
                    id=mod,
                    kind="module",
                    name=mod,
                    file=rel,
                    line=1,
                    module=mod,
                    meta={"is_test": is_test_file(rel)},
                )
            )
            graph._collect_defs(idx, tree.body, prefix="", parent=mod, test_file=is_test_file(rel))
        for idx in indexes.values():
            graph._collect_imports(idx, indexes)
        method_index = graph._method_name_index()
        for idx in indexes.values():
            _CallVisitor(graph, idx, indexes, method_index).visit(idx.tree)
            graph._collect_django_routes(idx)
        graph._process_jvm_files(ctx)
        graph._process_js_ts_files(ctx)
        graph._dedupe_edges()
        return graph

    def _add(self, node: Node) -> None:
        self.nodes[node.id] = node

    def _process_jvm_files(self, ctx: RepoContext) -> None:
        pkg_re = re.compile(r"^\s*package\s+([a-zA-Z0-9._]+)", re.MULTILINE)
        import_re = re.compile(r"^\s*import\s+([a-zA-Z0-9._]+)", re.MULTILINE)
        class_re = re.compile(
            r"^\s*(?:open\s+|abstract\s+|data\s+|sealed\s+|internal\s+|public\s+|private\s+|protected\s+)*(?:class|interface|object|enum\s+class)\s+([a-zA-Z0-9_]+)(?:\s*:\s*([^{]+)|\s+extends\s+([^{]+)|\s+implements\s+([^{]+))?",
            re.MULTILINE,
        )
        fun_re = re.compile(
            r"^\s*(?:override\s+|suspend\s+|public\s+|private\s+|protected\s+|inline\s+|internal\s+)*(?:fun|(?:void|[a-zA-Z0-9_<>\[\]]+)\s+)\s*([a-zA-Z0-9_]+)\s*\([^)]*\)",
            re.MULTILINE,
        )

        for rel in ctx.jvm_files:
            text = ctx.read_text(rel)
            if not text:
                continue
            is_test = is_test_file(rel) or "/test/" in rel or "/androidTest/" in rel
            stem = rel.rsplit("/", 1)[-1].split(".")[0]
            pkg_m = pkg_re.search(text)
            pkg = pkg_m.group(1).strip() if pkg_m else ""
            mod = f"{pkg}.{stem}" if pkg else stem

            self._add(
                Node(
                    id=mod,
                    kind="module",
                    name=mod,
                    file=rel,
                    line=1,
                    module=mod,
                    meta={"is_test": is_test, "lang": "kotlin" if rel.endswith((".kt", ".kts")) else "java"},
                )
            )

            for imp in import_re.findall(text):
                self.edges.append(Edge(mod, imp.strip(), "imports"))

            last_cid: str | None = None
            for m in class_re.finditer(text):
                cname = m.group(1).strip()
                if cname in ("class", "interface", "object"):
                    continue
                cid = f"{mod}:{cname}"
                last_cid = cid
                line_no = text[: m.start()].count("\n") + 1
                raw_bases = m.group(2) or m.group(3) or m.group(4) or ""
                bases = [
                    b.strip().split("(")[0].strip()
                    for b in raw_bases.split(",")
                    if b.strip() and not b.strip().startswith("{")
                ]
                is_route = any("Activity" in b for b in bases)
                kind = "route" if is_route else "class"
                self._add(
                    Node(
                        id=cid,
                        kind=kind,
                        name=cname,
                        file=rel,
                        line=line_no,
                        module=mod,
                        meta={"is_test": is_test, "bases": bases},
                    )
                )
                self.edges.append(Edge(mod, cid, "defines"))
                for b in bases:
                    self.edges.append(Edge(cid, b, "extends"))

            for fm in fun_re.finditer(text):
                fname = fm.group(1).strip()
                if fname in (
                    "class",
                    "interface",
                    "object",
                    "package",
                    "import",
                    "if",
                    "while",
                    "for",
                    "switch",
                    "catch",
                    "return",
                ):
                    continue
                line_no = text[: fm.start()].count("\n") + 1
                parent_id = last_cid or mod
                fid = f"{parent_id}.{fname}" if last_cid else f"{mod}:{fname}"
                f_is_test = is_test or fname.startswith("test")
                kind = "test" if f_is_test else "function"
                self._add(
                    Node(
                        id=fid,
                        kind=kind,
                        name=fname,
                        file=rel,
                        line=line_no,
                        module=mod,
                        meta={"is_test": f_is_test},
                    )
                )
                self.edges.append(Edge(parent_id, fid, "defines"))

            self._scan_jvm_routes(rel, mod, text, last_cid)

    def _scan_jvm_routes(self, rel: str, mod: str, text: str, last_cid: str | None) -> None:
        retrofit_re = re.compile(
            r"""@(GET|POST|PUT|DELETE|PATCH|HEAD)\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            re.MULTILINE,
        )
        spring_re = re.compile(
            r"""@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(\s*(?:(?:value|path)\s*=\s*)?['"]([^'"]+)['"])?""",
            re.MULTILINE,
        )
        for rm in retrofit_re.finditer(text):
            r_method = rm.group(1).upper()
            r_path = "/" + rm.group(2).lstrip("/")
            r_id = f"route:{r_method} {r_path}"
            r_line = text[: rm.start()].count("\n") + 1
            self._add(
                Node(
                    id=r_id,
                    kind="route",
                    name=f"{r_method} {r_path}",
                    file=rel,
                    line=r_line,
                    module=mod,
                    meta={"method": r_method, "path": r_path, "framework": "retrofit"},
                )
            )
            if last_cid:
                self.edges.append(Edge(r_id, last_cid, "routes_to"))

        for sm in spring_re.finditer(text):
            m_type = sm.group(1)
            s_method = "ALL" if m_type == "RequestMapping" else m_type.replace("Mapping", "").upper()
            s_path = "/" + (sm.group(2) or "").lstrip("/")
            s_id = f"route:{s_method} {s_path}"
            s_line = text[: sm.start()].count("\n") + 1
            self._add(
                Node(
                    id=s_id,
                    kind="route",
                    name=f"{s_method} {s_path}",
                    file=rel,
                    line=s_line,
                    module=mod,
                    meta={"method": s_method, "path": s_path, "framework": "spring"},
                )
            )
            if last_cid:
                self.edges.append(Edge(s_id, last_cid, "routes_to"))

    def _process_js_ts_files(self, ctx: RepoContext) -> None:
        import_re = re.compile(
            r"""(?:^|\s*)(?:import\s+(?:(?:[\w*\s{},$]+from\s+)?['"]([^'"]+)['"])|(?:const|let|var)\s+[\w*\s{},$]+\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\))""",
            re.MULTILINE,
        )
        fun_re = re.compile(
            r"""(?:^|\s*)(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s+([A-Za-z0-9_$]+)|(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*=>)""",
            re.MULTILINE,
        )
        class_re = re.compile(
            r"""(?:^|\s*)(?:export\s+(?:default\s+)?)?class\s+([A-Za-z0-9_$]+)(?:\s+extends\s+([A-Za-z0-9_$.]+))?""",
            re.MULTILINE,
        )
        express_re = re.compile(
            r"""\b(?:app|router|server)\.(get|post|put|delete|patch|options|head|all)\s*\(\s*['"]([^'"]+)['"]""",
            re.MULTILINE,
        )
        for rel in ctx.js_ts_files:
            text = ctx.read_text(rel)
            if not text:
                continue
            clean_rel = rel.replace("\\", "/")
            mod = clean_rel.rsplit(".", 1)[0]
            is_test = is_test_file(clean_rel)
            is_ts = clean_rel.endswith((".ts", ".tsx"))

            self._add(
                Node(
                    id=mod,
                    kind="module",
                    name=mod,
                    file=clean_rel,
                    line=1,
                    module=mod,
                    meta={"is_test": is_test, "lang": "typescript" if is_ts else "javascript"},
                )
            )

            for m in import_re.finditer(text):
                target = (m.group(1) or m.group(2) or "").strip()
                if target and not target.startswith("."):
                    self.edges.append(Edge(mod, target, "imports"))

            for cm in class_re.finditer(text):
                cname = cm.group(1).strip()
                base = (cm.group(2) or "").strip()
                cid = f"{mod}:{cname}"
                line_no = text[: cm.start()].count("\n") + 1
                self._add(
                    Node(
                        id=cid,
                        kind="class",
                        name=cname,
                        file=clean_rel,
                        line=line_no,
                        module=mod,
                        meta={"is_test": is_test, "base": base},
                    )
                )
                self.edges.append(Edge(mod, cid, "defines"))
                if base:
                    self.edges.append(Edge(cid, base, "extends"))

            for fm in fun_re.finditer(text):
                fname = (fm.group(1) or fm.group(2) or "").strip()
                if not fname or fname in (
                    "if",
                    "for",
                    "while",
                    "switch",
                    "catch",
                    "return",
                    "require",
                    "import",
                ):
                    continue
                fid = f"{mod}:{fname}"
                line_no = text[: fm.start()].count("\n") + 1
                f_is_test = is_test or fname.startswith("test") or fname.startswith("it")
                kind = "test" if f_is_test else "function"
                self._add(
                    Node(
                        id=fid,
                        kind=kind,
                        name=fname,
                        file=clean_rel,
                        line=line_no,
                        module=mod,
                        meta={"is_test": f_is_test},
                    )
                )
                self.edges.append(Edge(mod, fid, "defines"))

            self._scan_js_ts_routes(clean_rel, mod, text, express_re)

    def _scan_js_ts_routes(self, clean_rel: str, mod: str, text: str, express_re: re.Pattern[str]) -> None:
        m_app = re.search(r"(?:^|/)app/(.+)/route\.[jt]sx?$", clean_rel)
        if m_app:
            sub_path = m_app.group(1)
            route_path = "/" + re.sub(r"\[([^\]]+)\]", r":\1", sub_path)
            for http_m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                if re.search(rf"\bexport\s+(?:async\s+)?function\s+{http_m}\b", text):
                    rid = f"route:{http_m} {route_path}"
                    self._add(
                        Node(
                            id=rid,
                            kind="route",
                            name=f"{http_m} {route_path}",
                            file=clean_rel,
                            line=1,
                            module=mod,
                            meta={"method": http_m, "path": route_path, "framework": "nextjs"},
                        )
                    )
        elif "/pages/api/" in clean_rel:
            sub_path = clean_rel.split("/pages/api/", 1)[-1].rsplit(".", 1)[0]
            if sub_path.endswith("/index"):
                sub_path = sub_path.removesuffix("/index")
            route_path = "/api/" + re.sub(r"\[([^\]]+)\]", r":\1", sub_path)
            rid = f"route:ALL {route_path}"
            self._add(
                Node(
                    id=rid,
                    kind="route",
                    name=f"ALL {route_path}",
                    file=clean_rel,
                    line=1,
                    module=mod,
                    meta={"method": "ALL", "path": route_path, "framework": "nextjs"},
                )
            )

        for m in express_re.finditer(text):
            method = m.group(1).upper()
            raw_p = m.group(2)
            norm_p = "/" + raw_p.lstrip("/") if raw_p else "/"
            rid = f"route:{method} {norm_p}"
            line_no = text[: m.start()].count("\n") + 1
            self._add(
                Node(
                    id=rid,
                    kind="route",
                    name=f"{method} {norm_p}",
                    file=clean_rel,
                    line=line_no,
                    module=mod,
                    meta={"method": method, "path": norm_p, "framework": "express"},
                )
            )

    def _collect_defs(
        self,
        idx: _ModuleIndex,
        body: list[ast.stmt],
        prefix: str,
        parent: str,
        test_file: bool,
        in_test_class: bool = False,
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.If, ast.Try)):
                inner = (
                    list(stmt.body) + list(getattr(stmt, "orelse", [])) + list(getattr(stmt, "finalbody", []))
                )
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
            self._add(
                Node(
                    id=node_id,
                    kind=kind,
                    name=qual,
                    file=idx.rel,
                    line=stmt.lineno,
                    end_line=stmt.end_lineno,
                    module=idx.mod,
                    meta=meta,
                )
            )
            self.edges.append(Edge(parent, node_id, "defines"))
            idx.defs[qual] = node_id
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._collect_routes(idx, stmt, node_id)
            self._collect_defs(
                idx,
                stmt.body,
                f"{qual}.",
                node_id,
                test_file,
                in_test_class=isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"),
            )

    def _collect_routes(
        self, idx: _ModuleIndex, fn: ast.FunctionDef | ast.AsyncFunctionDef, fn_id: str
    ) -> None:
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            attr = ""
            if isinstance(dec.func, ast.Attribute):
                attr = dec.func.attr.lower()
            elif isinstance(dec.func, ast.Name):
                attr = dec.func.id.lower()

            if attr not in ROUTE_METHODS and attr not in ("api_view", "action"):
                continue

            raw_path = _extract_call_path(dec)
            if raw_path is None:
                if attr == "api_view":
                    raw_path = f"/{fn.name.replace('_', '-')}"
                elif not dec.args and not dec.keywords:
                    raw_path = "/"
                else:
                    continue

            norm_path = "/" + raw_path.lstrip("/") if raw_path else "/"
            default_m = "GET" if attr in ("route", "api_route", "api_view", "action") else attr.upper()
            if attr == "api_view" and dec.args and isinstance(dec.args[0], (ast.List, ast.Tuple, ast.Set)):
                methods = [str(e.value).upper() for e in dec.args[0].elts if isinstance(e, ast.Constant)]
            else:
                methods = _extract_call_methods(dec, default_m)

            for method in methods:
                rid = f"route:{method} {norm_path}"
                self._add(
                    Node(
                        id=rid,
                        kind="route",
                        name=f"{method} {norm_path}",
                        file=idx.rel,
                        line=dec.lineno,
                        module=idx.mod,
                        meta={"method": method, "path": norm_path, "handler": fn_id},
                    )
                )
                self.edges.append(Edge(rid, fn_id, "routes_to"))

    def _collect_django_routes(self, idx: _ModuleIndex) -> None:
        for node in ast.walk(idx.tree):
            if not isinstance(node, ast.Call):
                continue
            fname = ""
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname in ("path", "re_path") and len(node.args) >= 2:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    raw_p = arg0.value.strip("^$ ")
                    norm_p = "/" + raw_p.strip("/")
                    handler_name = ""
                    arg1 = node.args[1]
                    if isinstance(arg1, ast.Name):
                        handler_name = arg1.id
                    elif isinstance(arg1, ast.Attribute):
                        handler_name = arg1.attr
                    elif isinstance(arg1, ast.Call) and isinstance(arg1.func, ast.Attribute):
                        if isinstance(arg1.func.value, ast.Name):
                            handler_name = arg1.func.value.id

                    rid = f"route:ALL {norm_p}"
                    self._add(
                        Node(
                            id=rid,
                            kind="route",
                            name=f"ALL {norm_p}",
                            file=idx.rel,
                            line=node.lineno,
                            module=idx.mod,
                            meta={"method": "ALL", "path": norm_p, "handler": handler_name},
                        )
                    )
                    if handler_name:
                        target_id = idx.defs.get(handler_name) or f"{idx.mod}:{handler_name}"
                        self.edges.append(Edge(rid, target_id, "routes_to"))

    def _collect_imports(self, idx: _ModuleIndex, indexes: dict[str, _ModuleIndex]) -> None:
        pkg = idx.package()
        for node in ast.walk(idx.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = self._longest_module(alias.name, indexes, pkg)
                    if alias.asname:
                        idx.aliases[alias.asname] = alias.name
                    else:
                        idx.aliases[alias.name.split(".")[0]] = alias.name.split(".")[0]
                    if target:
                        self.edges.append(Edge(idx.mod, target, "imports"))
            elif isinstance(node, ast.ImportFrom):
                base = idx.resolve_relative(node.module, node.level)
                base_mod = self._longest_module(base, indexes, pkg) if base else None
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    sub = f"{base}.{alias.name}" if base else alias.name
                    if sub in indexes:
                        idx.aliases[local] = sub
                        self.edges.append(Edge(idx.mod, sub, "imports"))
                    else:
                        idx.aliases[local] = f"{base_mod or base}:{alias.name}" if base else alias.name
                        if base_mod:
                            self.edges.append(Edge(idx.mod, base_mod, "imports"))

    @staticmethod
    def _longest_module(name: str, indexes: dict[str, _ModuleIndex], current_pkg: str = "") -> str | None:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in indexes:
                return cand
        if current_pkg:
            combined = f"{current_pkg}.{name}"
            c_parts = combined.split(".")
            for i in range(len(c_parts), 0, -1):
                cand = ".".join(c_parts[:i])
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
        return [
            n
            for n in self.nodes.values()
            if n.kind in ("function", "class", "test")
            and (n.name == name or n.name.rsplit(".", 1)[-1] == name)
        ]

    def summary(self) -> dict[str, int]:
        counts = {"modules": 0, "functions": 0, "classes": 0, "routes": 0, "tests": 0}
        key = {
            "module": "modules",
            "function": "functions",
            "class": "classes",
            "route": "routes",
            "test": "tests",
        }
        for n in self.nodes.values():
            counts[key[n.kind]] += 1
        counts["edges"] = len(self.edges)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "summary": self.summary(),
            "limitations": GRAPH_LIMITATIONS,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoGraph:
        graph = cls()
        for n in data.get("nodes", []):
            graph._add(Node(**n))
        graph.edges = [Edge(**e) for e in data.get("edges", [])]
        return graph


class _CallVisitor(ast.NodeVisitor):
    def __init__(
        self,
        graph: RepoGraph,
        idx: _ModuleIndex,
        indexes: dict[str, _ModuleIndex],
        method_index: dict[str, list[str]],
    ):
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
