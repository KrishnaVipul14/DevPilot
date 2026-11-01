"""Environment-variable usage extraction and secret detection helpers."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)


@dataclass
class EnvUsage:
    name: str
    file: str
    line: int
    has_default: bool


def _is_environ(node: ast.AST) -> bool:
    # os.environ  |  environ
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ"
    )


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def env_usages(tree: ast.AST, rel: str) -> list[EnvUsage]:
    found: list[EnvUsage] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            name = _const_str(node.slice)
            if name and isinstance(node.ctx, ast.Load):
                found.append(EnvUsage(name, rel, node.lineno, False))
        elif isinstance(node, ast.Call):
            func = node.func
            name = _const_str(node.args[0]) if node.args else None
            if not name:
                continue
            has_default = len(node.args) > 1 or any(k.arg == "default" for k in node.keywords)
            if isinstance(func, ast.Attribute):
                if (
                    func.attr in ("get", "setdefault", "pop")
                    and _is_environ(func.value)
                    or func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    found.append(EnvUsage(name, rel, node.lineno, has_default))
            elif isinstance(func, ast.Name) and func.id == "getenv":
                found.append(EnvUsage(name, rel, node.lineno, has_default))
        elif (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.In, ast.NotIn))
        ):
            name = _const_str(node.left)
            if name and _is_environ(node.comparators[0]):
                found.append(EnvUsage(name, rel, node.lineno, True))
    return found


def parse_env_keys(text: str) -> dict[str, int]:
    keys: dict[str, int] = {}
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        m = ENV_KEY_RE.match(line)
        if m and m.group(1) not in keys:
            keys[m.group(1)] = idx
    return keys


# --- secrets -----------------------------------------------------------------
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[0-9A-Za-z]{20,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
]
SECRET_NAME_RE = re.compile(
    r"(pass(word|wd)?|secret|api[_-]?key|apikey|token|access[_-]?key|private[_-]?key|auth[_-]?key)$",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(
    r"(your|example|changeme|change_me|xxx|placeholder|dummy|sample|<|>|\$\{|\*\*\*|todo|redacted|test)",
    re.IGNORECASE,
)


def mask(value: str) -> str:
    return f"<redacted {len(value)} chars>"


def redact_text(text: str) -> str:
    """Remove known secret formats and secret-looking assignments from text (used before AI calls)."""
    for _label, pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: mask(m.group(0)), text)
    assign = re.compile(
        r"""((?:pass(?:word|wd)?|secret|api[_-]?key|apikey|token|access[_-]?key|private[_-]?key)\w*\s*[:=]\s*)(['"])([^'"\n]{6,})\2""",
        re.IGNORECASE,
    )
    return assign.sub(lambda m: f"{m.group(1)}{m.group(2)}{mask(m.group(3))}{m.group(2)}", text)


@dataclass
class SecretHit:
    kind: str
    line: int
    name: str | None
    length: int
    confidence: str


def scan_text_for_secrets(text: str) -> list[SecretHit]:
    hits = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for label, pattern in SECRET_PATTERNS:
            m = pattern.search(line)
            if m:
                hits.append(SecretHit(label, idx, None, len(m.group(0)), "high"))
    return hits


def scan_python_for_secrets(tree: ast.AST) -> list[SecretHit]:
    hits = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.keyword) and node.arg:
            if SECRET_NAME_RE.search(node.arg):
                s = _const_str(node.value)
                if s and len(s) >= 8 and not PLACEHOLDER_RE.search(s) and " " not in s:
                    hits.append(
                        SecretHit("Hardcoded credential", node.value.lineno, node.arg, len(s), "medium")
                    )
            continue
        s = _const_str(value)
        if not s or len(s) < 8 or PLACEHOLDER_RE.search(s) or " " in s:
            continue
        for target in targets:
            name = (
                target.id
                if isinstance(target, ast.Name)
                else target.attr
                if isinstance(target, ast.Attribute)
                else None
            )
            if name and SECRET_NAME_RE.search(name):
                hits.append(SecretHit("Hardcoded credential", node.lineno, name, len(s), "medium"))
    return hits
