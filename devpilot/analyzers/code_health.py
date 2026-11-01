"""Code health analyzer: Ruff (pyflakes, bugbear, complexity, selected security
rules) plus AST-based maintainability checks."""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path

from devpilot.analyzers.base import Analyzer, AnalyzerOutput, AnalyzerSkipped
from devpilot.core.astutil import enclosing_symbol, iter_defs
from devpilot.core.context import RepoContext
from devpilot.core.models import Confidence, Finding, Severity
from devpilot.utils.proc import run

# Explicit severities for well-known rules; prefixes used as fallback.
RULE_SEVERITY: dict[str, Severity] = {
    "F821": Severity.HIGH,  # undefined name
    "F822": Severity.HIGH,  # undefined name in __all__
    "F823": Severity.HIGH,  # local variable referenced before assignment
    "F811": Severity.MEDIUM,  # redefinition of unused name
    "F401": Severity.LOW,  # unused import
    "F841": Severity.LOW,  # unused local variable
    "F541": Severity.LOW,  # f-string without placeholders
    "F403": Severity.LOW,
    "F405": Severity.MEDIUM,
    "F632": Severity.HIGH,  # is-literal comparison
    "F701": Severity.HIGH,
    "F702": Severity.HIGH,
    "F704": Severity.HIGH,
    "F706": Severity.HIGH,
    "E999": Severity.CRITICAL,  # syntax error
    "E902": Severity.CRITICAL,  # token/IO error
    "S608": Severity.CRITICAL,  # SQL injection via string concatenation
    "S301": Severity.CRITICAL,  # unsafe deserialization with pickle
    "S102": Severity.CRITICAL,  # use of exec()
    "S307": Severity.CRITICAL,  # use of eval()
    "S602": Severity.CRITICAL,  # subprocess call with shell=True
    "S506": Severity.CRITICAL,  # unsafe yaml.load()
    "S105": Severity.CRITICAL,  # hardcoded password string
    "S106": Severity.CRITICAL,  # hardcoded password in func call
    "S107": Severity.CRITICAL,  # hardcoded password in func default
    "S324": Severity.HIGH,  # insecure MD5/SHA-1 hash
    "S104": Severity.HIGH,  # binding to 0.0.0.0
    "S201": Severity.HIGH,  # debug mode enabled
    "S701": Severity.HIGH,  # autoescape disabled
    "B006": Severity.MEDIUM,
    "B008": Severity.MEDIUM,
    "B904": Severity.LOW,
    "B007": Severity.LOW,
    "B905": Severity.LOW,
    "B028": Severity.LOW,
    "E722": Severity.MEDIUM,
    "C901": Severity.MEDIUM,
}
PREFIX_SEVERITY: list[tuple[str, Severity]] = [
    ("E9", Severity.CRITICAL),
    ("F", Severity.MEDIUM),
    ("B", Severity.MEDIUM),
    ("S", Severity.HIGH),
]

RULE_TITLES: dict[str, str] = {
    "F821": "Undefined name",
    "F401": "Unused import",
    "F841": "Unused local variable",
    "C901": "Function is too complex",
    "E722": "Bare except clause",
    "E999": "Syntax error",
    "S608": "Possible SQL injection vector",
    "S301": "Insecure deserialization (pickle)",
    "S307": "Use of eval() (code execution)",
    "S102": "Use of exec() (code execution)",
    "S602": "subprocess call with shell=True (command injection)",
    "S506": "Unsafe yaml.load() (code execution)",
    "S105": "Possible hardcoded password",
    "S106": "Hardcoded password argument",
    "S107": "Hardcoded password in default argument",
    "S324": "Insecure hash algorithm (MD5/SHA-1)",
    "S104": "Socket binding to all network interfaces (0.0.0.0)",
    "S201": "Flask debug mode enabled",
    "B006": "Mutable default argument",
}

RULE_SUGGESTIONS: dict[str, str] = {
    "F821": "Define or import the name before use, or fix the typo. This will raise NameError at runtime.",
    "F401": "Remove the unused import (or re-export it explicitly via __all__).",
    "F841": "Remove the unused variable or use it.",
    "C901": "Split the function into smaller, well-named helpers.",
    "E722": "Catch specific exceptions (e.g. `except ValueError:`) so real errors are not swallowed.",
    "E999": "Fix the syntax error to ensure valid Python syntax.",
    "S608": "Use parameterized queries or ORM query builders to prevent SQL injection.",
    "S301": "Avoid pickle for untrusted input; use JSON or safe serialization formats.",
    "S307": "Avoid eval(); use ast.literal_eval() or explicit parsing to avoid code execution.",
    "S102": "Avoid exec(); restructure the code to call functions directly.",
    "S602": "Pass an argument list and shell=False to avoid command injection vulnerabilities.",
    "S506": "Use yaml.safe_load() instead of yaml.load().",
    "S105": "Never hardcode passwords; load credentials from environment variables or a secrets manager.",
    "S106": "Pass sensitive credentials via configuration or environment variables.",
    "S107": "Do not specify credentials as default arguments; require them at runtime from secure sources.",
    "S324": "Use secure hash algorithms such as SHA-256 or SHA-512.",
    "S104": "Bind to localhost (127.0.0.1) or a specific network interface rather than 0.0.0.0.",
    "S201": "Ensure debug=False in production deployments.",
    "B006": "Use None as the default and create the mutable object inside the function.",
}


def _severity_for(code: str) -> Severity:
    if code in RULE_SEVERITY:
        return RULE_SEVERITY[code]
    for prefix, sev in PREFIX_SEVERITY:
        if code.startswith(prefix):
            return sev
    return Severity.LOW


def find_ruff() -> str | None:
    try:
        from ruff.__main__ import find_ruff_bin  # type: ignore[import-not-found]

        return str(find_ruff_bin())
    except Exception:  # noqa: BLE001 - optional import path
        pass
    found = shutil.which("ruff")
    if found:
        return found
    candidate = Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff")
    return str(candidate) if candidate.exists() else None


def run_ruff_json(
    ruff: str,
    root: Path,
    select: list[str],
    max_complexity: int,
    excludes: list[str],
    targets: list[str] | None = None,
) -> list[dict]:
    args = [
        ruff,
        "check",
        "--output-format",
        "json",
        "--exit-zero",
        "--no-cache",
        "--select",
        ",".join(select),
        "--config",
        f"lint.mccabe.max-complexity = {int(max_complexity)}",
        "--config",
        'lint.flake8-bugbear.extend-immutable-calls = ["typer.Argument", "typer.Option", "fastapi.Depends", "fastapi.Query", "fastapi.Path", "fastapi.Body", "fastapi.Header"]',
    ]
    if excludes:
        args += ["--extend-exclude", ",".join(excludes)]
    args += targets or ["."]
    res = run(args, cwd=root, timeout=180)
    if res.timed_out:
        raise RuntimeError("ruff timed out")
    try:
        data = json.loads(res.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse ruff output: {res.stderr.strip()[:300]}") from exc
    if not isinstance(data, list):
        raise RuntimeError("Unexpected ruff output format")
    return data


class CodeHealthAnalyzer(Analyzer):
    name = "code_health"
    description = "Ruff static analysis + AST maintainability checks"

    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        out = AnalyzerOutput()
        if not ctx.python_files:
            raise AnalyzerSkipped("No Python files found")
        cfg = ctx.config.analyzers.code_health
        ruff = find_ruff()
        if ruff is None:
            out.message = "ruff not found; only AST checks were run"
        else:
            self._ruff(ctx, ruff, out)
        self._ast_checks(ctx, out, cfg.max_function_lines, cfg.max_parameters)
        return out

    # -- ruff -----------------------------------------------------------------
    def _ruff(self, ctx: RepoContext, ruff: str, out: AnalyzerOutput) -> None:
        cfg = ctx.config.analyzers.code_health
        excludes = [e for e in ctx.config.exclude]
        records = run_ruff_json(ruff, ctx.root, cfg.select, cfg.max_complexity, excludes)
        allowed = set(ctx.python_files)
        for rec in records:
            raw_fn = rec.get("filename")
            if not raw_fn:
                continue
            p_fn = Path(raw_fn)
            abs_fn = p_fn if p_fn.is_absolute() else (ctx.root / p_fn)
            try:
                rel = abs_fn.resolve().relative_to(ctx.root.resolve()).as_posix()
            except ValueError:
                rel = p_fn.as_posix().replace("\\", "/")
            if rel not in allowed:
                continue
            code = rec.get("code") or "syntax-error"
            row = (rec.get("location") or {}).get("row")
            col = (rec.get("location") or {}).get("column")
            end_row = (rec.get("end_location") or {}).get("row")
            message = rec.get("message", "")
            severity = Severity.CRITICAL if code == "syntax-error" else _severity_for(code)
            symbol = enclosing_symbol(ctx.parse(rel), row)
            source_line = ctx.line(rel, row)
            fix = rec.get("fix") or None
            safe_fix = bool(fix and fix.get("applicability") == "safe" and fix.get("edits"))
            title = RULE_TITLES.get(
                code, message.split(":")[0][:80] if code != "syntax-error" else "Syntax error"
            )
            evidence = f"{code}: {message}"
            if source_line.strip():
                evidence += f"\n  {row} | {source_line.strip()}"
            finding = Finding(
                module=self.name,
                rule=code,
                severity=severity,
                title=title,
                file=rel,
                line=row,
                end_line=end_row,
                column=col,
                symbol=symbol,
                evidence=evidence,
                suggestion=RULE_SUGGESTIONS.get(
                    code, (fix or {}).get("message") or "Review and fix the reported issue."
                ),
                confidence=Confidence.HIGH,
                fixable=safe_fix,
                references=[rec["url"]] if rec.get("url") else [],
                metadata={"engine": "ruff", "fix": fix} if fix else {"engine": "ruff"},
            )
            out.add(finding, anchor=f"{symbol or ''}|{message}|{source_line}")

    # -- AST maintainability -------------------------------------------------
    def _ast_checks(self, ctx: RepoContext, out: AnalyzerOutput, max_lines: int, max_params: int) -> None:
        for rel in ctx.python_files:
            tree = ctx.parse(rel)
            if tree is None:
                continue
            for qual, node in iter_defs(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > max_lines:
                    out.add(
                        Finding(
                            module=self.name,
                            rule="long-function",
                            severity=Severity.LOW,
                            title="Function is very long",
                            file=rel,
                            line=node.lineno,
                            end_line=node.end_lineno,
                            symbol=qual,
                            evidence=f"`{qual}` spans {length} lines (threshold {max_lines}).",
                            suggestion="Extract cohesive blocks into helper functions to improve readability and testability.",
                            confidence=Confidence.HIGH,
                            metadata={"engine": "ast", "lines": length},
                        ),
                        anchor=qual,
                    )
                args = node.args
                params = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
                params = [p for p in params if p not in ("self", "cls")]
                if len(params) > max_params:
                    out.add(
                        Finding(
                            module=self.name,
                            rule="too-many-parameters",
                            severity=Severity.LOW,
                            title="Function has many parameters",
                            file=rel,
                            line=node.lineno,
                            symbol=qual,
                            evidence=f"`{qual}` takes {len(params)} parameters (threshold {max_params}).",
                            suggestion="Group related parameters into a dataclass or configuration object.",
                            confidence=Confidence.HIGH,
                            metadata={"engine": "ast", "parameters": len(params)},
                        ),
                        anchor=qual,
                    )
