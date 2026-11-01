"""Automated unit test scaffold generator based on code intelligence and signatures."""

from __future__ import annotations

from typing import Any

from devpilot.analyzers.repository_graph import Node, RepoGraph
from devpilot.core.context import RepoContext


def _generate_python_test(
    node: Node, clean_file: str, stem: str, func_name: str, is_async: bool
) -> dict[str, Any]:
    mod_import = clean_file.removesuffix(".py").replace("/", ".").removeprefix("src.")
    test_path = f"tests/test_{stem}.py"
    call_stmt = f"await {func_name}()" if is_async else f"{func_name}()"
    async_dec = "@pytest.mark.asyncio\n" if is_async else ""
    async_def = "async def" if is_async else "def"

    test_code = f'''"""Unit tests for `{func_name}` in `{clean_file}`."""

import pytest
from {mod_import} import {func_name}


{async_dec}{async_def} test_{func_name}_happy_path():
    """Verify expected behavior with valid inputs."""
    # Arrange & Act
    # TODO: Supply valid parameters based on implementation
    result = {call_stmt}

    # Assert
    assert result is not None


{async_dec}{async_def} test_{func_name}_edge_case_or_error():
    """Verify robust error handling or edge-case behavior."""
    # Assert proper handling of invalid arguments
    with pytest.raises(Exception):
        # Pass unexpected or empty parameters to assert error boundary
        pass
'''
    return {
        "symbol": node.name,
        "target_file": clean_file,
        "suggested_test_file": test_path,
        "language": "python",
        "framework": "pytest",
        "command": f"pytest {test_path} -v",
        "success": True,
        "test_code": test_code,
    }


def _generate_js_test(node: Node, clean_file: str, stem: str, func_name: str) -> dict[str, Any]:
    test_path = (
        f"src/__tests__/{stem}.test.ts"
        if clean_file.endswith((".ts", ".tsx"))
        else f"src/__tests__/{stem}.test.js"
    )
    test_code = f"""/**
 * Unit tests for `{func_name}` in `{clean_file}`.
 */
import {{ describe, it, expect }} from 'vitest'; // or jest
import {{ {func_name} }} from '../{stem}';

describe('{func_name}', () => {{
    it('executes successfully with valid input', async () => {{
        // Arrange & Act
        const result = await {func_name}();

        // Assert
        expect(result).toBeDefined();
    }});

    it('handles unexpected inputs gracefully', async () => {{
        expect(() => {func_name}(null)).not.toThrow();
    }});
}});
"""
    return {
        "symbol": node.name,
        "target_file": clean_file,
        "suggested_test_file": test_path,
        "language": "javascript",
        "framework": "jest/vitest",
        "command": f"npm test -- {test_path}",
        "success": True,
        "test_code": test_code,
    }


def generate_test_scaffold(
    ctx: RepoContext,
    symbol_name: str,
    graph: RepoGraph | None = None,
) -> dict[str, Any]:
    """Generate a runnable unit test scaffold for a function, class, or endpoint."""
    graph = graph or RepoGraph.build(ctx)
    nodes = graph.find(symbol_name)
    node: Node | None = nodes[0] if nodes else None

    # Fallback search if exact symbol not found
    if node is None:
        for n in graph.nodes.values():
            if symbol_name.lower() in n.name.lower() and n.kind in ("function", "class", "route"):
                node = n
                break

    if node is None:
        return {
            "symbol": symbol_name,
            "success": False,
            "error": f"Symbol `{symbol_name}` not found in repository intelligence graph.",
            "test_code": "",
        }

    rel_file = node.file or "src/app.py"
    clean_file = rel_file.replace("\\", "/")
    stem = clean_file.rsplit("/", 1)[-1].split(".")[0]
    func_name = node.name.rsplit(".", 1)[-1]
    is_async = bool(node.meta.get("async", False))

    if clean_file.endswith(".py"):
        return _generate_python_test(node, clean_file, stem, func_name, is_async)

    if clean_file.endswith((".js", ".jsx", ".ts", ".tsx")):
        return _generate_js_test(node, clean_file, stem, func_name)

    return {
        "symbol": node.name,
        "target_file": clean_file,
        "suggested_test_file": f"tests/test_{stem}",
        "language": "generic",
        "framework": "unit-test",
        "command": "devpilot test",
        "success": True,
        "test_code": f"// Unit test scaffold for {func_name} in {clean_file}\n",
    }
