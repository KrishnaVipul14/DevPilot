"""Documentation drift analyzer.

Detects:
1. Function docstrings that document parameters (`:param x:` or Args/Parameters sections)
   that no longer match the actual function signature.
2. Python code blocks in Markdown/README files that contain syntax errors or call
   repository functions with outdated argument counts / unknown keyword arguments.
3. Environment variables mentioned in Markdown documentation (`os.getenv("X")`,
   `os.environ["X"]`, or `export X=...` in shell blocks) that are missing from `.env.example`
   or unreferenced in Python code.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from devpilot.analyzers.base import Analyzer, AnalyzerOutput, AnalyzerSkipped
from devpilot.analyzers.envsecrets import env_usages, parse_env_keys
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.analyzers.setup_doctor import PLATFORM_VARS
from devpilot.core.astutil import iter_defs
from devpilot.core.context import ENV_EXAMPLE_NAMES, RepoContext
from devpilot.core.models import Confidence, Finding, Severity

_SPHINX_PARAM_RE = re.compile(r":param\s+(?:[A-Za-z_][\w.\[\], ]*\s+)?([A-Za-z_]\w*)\s*:")
_GOOGLE_SECTION_RE = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.MULTILINE)
_GOOGLE_PARAM_RE = re.compile(r"^(\s+)\*{0,2}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:")
_FENCE_RE = re.compile(r"```([A-Za-z0-9_-]*)\s*\n(.*?)```", re.DOTALL)
_ENV_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)


def _extract_docstring_params(doc: str) -> set[str]:
    params: set[str] = set(_SPHINX_PARAM_RE.findall(doc))
    m = _GOOGLE_SECTION_RE.search(doc)
    if m:
        after = doc[m.end() :]
        lines = after.splitlines()
        param_indent: int | None = None
        for line in lines:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if param_indent is not None and indent < param_indent:
                break
            if re.match(r"^\s*(Returns|Yields|Raises|Examples|Notes|Attributes)\s*:\s*$", line):
                break
            pm = _GOOGLE_PARAM_RE.match(line)
            if pm:
                if param_indent is None:
                    param_indent = len(pm.group(1))
                if len(pm.group(1)) == param_indent:
                    params.add(pm.group(2))
    return params


def _check_call_mismatch(target: dict[str, Any], call: ast.Call) -> str | None:
    meta = target["meta"]
    is_method = "." in target["name"]
    pos_params = [p for p in meta.get("positional", []) if p not in ("self", "cls")]
    req_params = list(meta.get("required", []))
    kwonly = list(meta.get("kwonly", []))
    has_varargs = bool(meta.get("varargs"))
    has_varkw = bool(meta.get("varkw"))
    all_allowed = set(pos_params) | set(kwonly)

    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None
    n_pos = len(call.args)
    kw_names = [k.arg for k in call.keywords if k.arg is not None]

    unknown_kw = [k for k in kw_names if k not in all_allowed] if not has_varkw else []
    if unknown_kw:
        return f"passes unknown keyword argument(s) {', '.join(f'`{k}`' for k in unknown_kw)}"
    if not has_varargs and n_pos > len(pos_params):
        return (
            f"passes {n_pos} positional arguments, but `{target['name']}` accepts at most {len(pos_params)}"
        )
    bound = set(pos_params[:n_pos]) | set(kw_names)
    missing_req = [p for p in req_params + list(meta.get("kwonly_required", [])) if p not in bound]
    if missing_req and not (is_method and isinstance(call.func, ast.Name)):
        return f"omits required argument(s) {', '.join(f'`{p}`' for p in missing_req)}"
    return None


class DocumentationAnalyzer(Analyzer):
    name = "documentation"
    description = "Docstring parameter drift, outdated README code examples, and documented env mismatch"

    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        if not ctx.python_files and not ctx.markdown_files:
            raise AnalyzerSkipped("No Python or Markdown files found")
        out = AnalyzerOutput()
        graph = RepoGraph.build(ctx)
        self._check_docstring_params(ctx, out)
        self._check_markdown_examples(ctx, graph, out)
        self._check_documented_env_vars(ctx, out)
        out.message = f"Checked {len(ctx.python_files)} Python files and {len(ctx.markdown_files)} docs"
        return out

    def _check_docstring_params(self, ctx: RepoContext, out: AnalyzerOutput) -> None:
        for rel in ctx.python_files:
            tree = ctx.parse(rel)
            if tree is None:
                continue
            for qual, node in iter_defs(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node)
                if not doc:
                    continue
                doc_params = _extract_docstring_params(doc)
                if not doc_params:
                    continue
                a = node.args
                actual = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
                if a.vararg:
                    actual.add(a.vararg.arg)
                if a.kwarg:
                    actual.add(a.kwarg.arg)
                stale = sorted(doc_params - actual)
                if stale:
                    out.add(
                        Finding(
                            module=self.name,
                            rule="docstring-stale-param",
                            severity=Severity.LOW,
                            title=f"Docstring in `{qual}` documents non-existent parameter(s): {', '.join(stale)}",
                            file=rel,
                            line=node.lineno,
                            symbol=qual,
                            evidence=(
                                f"Docstring mentions parameter(s) {', '.join(f'`{p}`' for p in stale)}, "
                                f"but `{node.name}` accepts ({', '.join(sorted(actual - {'self', 'cls'}))})."
                            ),
                            suggestion="Update the docstring parameters to match the current function signature.",
                            confidence=Confidence.HIGH,
                            metadata={"symbol": qual, "stale_params": stale, "actual_params": sorted(actual)},
                        ),
                        anchor=f"docparam:{qual}:{','.join(stale)}",
                    )

    def _check_fence_block(
        self,
        rel: str,
        text: str,
        match: re.Match[str],
        fn_by_name: dict[str, list[dict[str, Any]]],
        out: AnalyzerOutput,
    ) -> None:
        lang = (match.group(1) or "").lower()
        code = match.group(2)
        fence_line = text[: match.start()].count("\n") + 1
        if lang not in ("python", "py"):
            return
        cleaned_lines = []
        for line in code.splitlines():
            if line.lstrip().startswith(">>> ") or line.lstrip().startswith("... "):
                cleaned_lines.append(line.lstrip()[4:])
            elif not line.lstrip().startswith(">>>"):
                cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)
        try:
            block_tree = ast.parse(cleaned)
        except SyntaxError as exc:
            out.add(
                Finding(
                    module=self.name,
                    rule="readme-example-syntax-error",
                    severity=Severity.LOW,
                    title=f"Python example in {rel} has a syntax error",
                    file=rel,
                    line=fence_line + (exc.lineno or 1),
                    evidence=f"SyntaxError in fenced Python block starting at line {fence_line}: {exc.msg}",
                    suggestion="Fix the Python code example in the documentation so it parses cleanly.",
                    confidence=Confidence.MEDIUM,
                ),
                anchor=f"md-syntax:{rel}:{fence_line}",
            )
            return

        for call in ast.walk(block_tree):
            if not isinstance(call, ast.Call):
                continue
            fn_name = (
                call.func.id
                if isinstance(call.func, ast.Name)
                else call.func.attr
                if isinstance(call.func, ast.Attribute)
                else None
            )
            if not fn_name or fn_name not in fn_by_name:
                continue
            candidates = fn_by_name[fn_name]
            if len(candidates) != 1:
                continue
            target = candidates[0]
            issue_reason = _check_call_mismatch(target, call)
            if issue_reason:
                call_line = fence_line + getattr(call, "lineno", 1)
                sig = target["meta"].get("signature", f"{fn_name}(...)")
                out.add(
                    Finding(
                        module=self.name,
                        rule="readme-outdated-example",
                        severity=Severity.MEDIUM,
                        title=f"Documentation example calls `{fn_name}()` with outdated signature",
                        file=rel,
                        line=call_line,
                        symbol=target["name"],
                        evidence=(
                            f"Example in {rel}:{call_line} {issue_reason}.\n"
                            f"Actual signature in {target['file']}: `def {sig}`"
                        ),
                        suggestion=f"Update the example in {rel} to match `def {sig}`.",
                        confidence=Confidence.HIGH,
                        metadata={
                            "function": target["id"],
                            "signature": sig,
                            "definition_file": target["file"],
                        },
                    ),
                    anchor=f"md-call:{rel}:{fn_name}:{issue_reason}",
                )

    def _check_markdown_examples(self, ctx: RepoContext, graph: RepoGraph, out: AnalyzerOutput) -> None:
        # Index unique function names in repository (excluding tests and dunder methods)
        fn_by_name: dict[str, list[dict[str, Any]]] = {}
        for node in graph.nodes.values():
            if node.kind == "function":
                short = node.name.rsplit(".", 1)[-1]
                if not short.startswith("_"):
                    fn_by_name.setdefault(short, []).append(
                        {"id": node.id, "name": node.name, "file": node.file, "meta": node.meta}
                    )

        for rel in ctx.markdown_files:
            text = ctx.read_text(rel)
            if not text:
                continue
            for match in _FENCE_RE.finditer(text):
                self._check_fence_block(rel, text, match, fn_by_name, out)

    def _check_documented_env_vars(self, ctx: RepoContext, out: AnalyzerOutput) -> None:
        code_vars: set[str] = set()
        for rel in ctx.python_files:
            tree = ctx.parse(rel)
            if tree is not None:
                code_vars.update(u.name for u in env_usages(tree, rel))
        root_examples = [f for f in ctx.files if f in ENV_EXAMPLE_NAMES]
        all_examples = [f for f in ctx.files if f.rsplit("/", 1)[-1] in ENV_EXAMPLE_NAMES]
        examples = root_examples or all_examples
        example_vars = set(parse_env_keys(ctx.read_text(examples[0]) or "")) if examples else set()
        known_vars = code_vars | example_vars | PLATFORM_VARS
        if not code_vars and not example_vars:
            return

        for rel in ctx.markdown_files:
            text = ctx.read_text(rel) or ""
            for match in _FENCE_RE.finditer(text):
                lang = (match.group(1) or "").lower()
                code = match.group(2)
                fence_line = text[: match.start()].count("\n") + 1
                if lang in ("bash", "sh", "shell", "zsh", "dotenv", "env", ""):
                    for m in _ENV_ASSIGN_RE.finditer(code):
                        var = m.group(1)
                        if var not in known_vars and "_" in var:
                            line = fence_line + code[: m.start()].count("\n") + 1
                            out.add(
                                Finding(
                                    module=self.name,
                                    rule="doc-env-not-in-code",
                                    severity=Severity.LOW,
                                    title=f"Documented env variable `{var}` is not used in code or .env.example",
                                    file=rel,
                                    line=line,
                                    evidence=f"`{var}` appears in a configuration block in {rel}:{line} but was not found in Python code or .env.example.",
                                    suggestion=f"Update {rel} if `{var}` was renamed, or add it to `.env.example`.",
                                    confidence=Confidence.MEDIUM,
                                    metadata={"variable": var},
                                ),
                                anchor=f"doc-env:{rel}:{var}",
                            )
