"""Automated tests for DevPilot analyzers, graph, impact, memory, fixes, CLI, and server API."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from devpilot.analyzers.change_impact import analyze_git_impact, analyze_symbol_impact
from devpilot.analyzers.manifests import parse_pyproject, parse_requirements
from devpilot.analyzers.osv import cvss3_base_score, score_to_label
from devpilot.analyzers.repository_graph import RepoGraph
from devpilot.cli.main import app
from devpilot.core.config import load_config
from devpilot.core.context import RepoContext, is_sensitive_file
from devpilot.core.scanner import run_scan
from devpilot.dashboard_server.server import create_server
from devpilot.fixes.patch_generator import propose_patch
from devpilot.fixes.patch_manager import apply_patch, discard_patch, verify_patch
from devpilot.memory.fingerprints import compute_fingerprint
from devpilot.utils import git as gitutil

DEMO_APP = Path(__file__).parent.parent / "examples" / "demo-app"
runner = CliRunner()


def test_sensitive_file_protection() -> None:
    assert is_sensitive_file(".env") is True
    assert is_sensitive_file(".env.local") is True
    assert is_sensitive_file("secrets/id_rsa") is True
    assert is_sensitive_file(".env.example") is False
    assert is_sensitive_file("app.py") is False


def test_cvss3_score_and_manifest_parsing() -> None:
    score = cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert score == 9.8
    assert score_to_label(score) == "critical"

    deps = parse_requirements("requests==2.25.0\nflask>=2.0\n# comment\n", "requirements.txt")
    assert len(deps) == 2
    assert deps[0].name == "requests"
    assert deps[0].pinned is True
    assert deps[0].version == "2.25.0"
    assert deps[1].pinned is False

    py_deps = parse_pyproject('[project]\ndependencies = ["pydantic==2.5.0"]\n', "pyproject.toml")
    assert len(py_deps) == 1
    assert py_deps[0].name == "pydantic"
    assert py_deps[0].version == "2.5.0"


def test_stable_fingerprint_line_independence() -> None:
    fp1 = compute_fingerprint("code_health", "F401", "auth.py", "|`json` imported but unused|import json")
    fp2 = compute_fingerprint("code_health", "F401", "auth.py", "|`json`   imported but unused|import   json  ")
    assert fp1 == fp2


def test_repository_graph_and_symbol_impact(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    shutil.copytree(DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache"))
    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    graph = RepoGraph.build(ctx)
    summary = graph.summary()
    assert summary["modules"] == 4
    assert summary["routes"] == 3
    assert summary["tests"] == 5

    imp = analyze_symbol_impact(ctx, "validate_token", graph=graph)
    assert imp["overall_risk"]["level"] in ("high", "critical")
    assert len(imp["impacts"]) == 1
    entry = imp["impacts"][0]
    assert "auth:require_user" in entry["callers"]
    assert "billing:authorize_and_bill" in entry["callers"]
    assert len(entry["routes"]) == 3
    assert len(entry["tests"]) >= 3


def test_scan_memory_fix_verify_lifecycle(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    shutil.copytree(DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache"))

    # Initialize git repo so git worktree verification and git impact work end-to-end
    gitutil.git(["init"], cwd=repo)
    gitutil.git(["config", "user.email", "test@example.com"], cwd=repo)
    gitutil.git(["config", "user.name", "Test User"], cwd=repo)
    gitutil.git(["add", "."], cwd=repo)
    gitutil.git(["commit", "-m", "Initial demo commit"], cwd=repo)

    # Scan 1 (offline)
    report1 = run_scan(repo, offline=True, persist=True)
    assert report1.summary.total >= 10
    assert report1.memory is not None
    assert report1.memory.new == report1.summary.total
    assert report1.memory.existing == 0

    rules = {f.rule for f in report1.findings}
    assert "F401" in rules  # unused import
    assert "F821" in rules  # undefined name
    assert "env-missing-from-example" in rules  # setup doctor
    assert "readme-outdated-example" in rules  # doc drift
    assert "docstring-stale-param" in rules  # docstring drift

    # Propose, verify in isolated git worktree, and apply a fix for F401 in auth.py
    f401 = next(f for f in report1.findings if f.rule == "F401" and f.file == "auth.py")
    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    patch = propose_patch(ctx, f401, engine="ruff")
    assert patch["status"] == "proposed"
    assert "-import json" in patch["diff"]
    # Original file untouched before apply
    assert "import json" in (repo / "auth.py").read_text(encoding="utf-8")

    verified = verify_patch(ctx, patch["patch_id"])
    assert verified["status"] == "verified"
    assert verified["verification"]["mode"] == "git-worktree"
    # Original file still untouched after isolated verification
    assert "import json" in (repo / "auth.py").read_text(encoding="utf-8")

    applied = apply_patch(ctx, patch["patch_id"])
    assert applied["status"] == "applied"
    assert "import json" not in (repo / "auth.py").read_text(encoding="utf-8")

    # Git impact detects modified auth.py
    ctx_after = RepoContext(root=repo, config=load_config(repo), offline=True)
    git_imp = analyze_git_impact(ctx_after)
    assert any(cf["path"] == "auth.py" for cf in git_imp["changed_files"])

    # Scan 2 records 1 resolved issue and remaining as existing
    report2 = run_scan(repo, offline=True, persist=True)
    assert report2.memory is not None
    assert report2.memory.resolved == 1
    assert report2.memory.existing == report2.summary.total

    # Test discard flow on another fixable finding
    other_fixable = next(f for f in report2.findings if f.rule == "env-missing-from-example")
    p2 = propose_patch(ctx_after, other_fixable, engine="auto")
    discarded = discard_patch(ctx_after, p2["patch_id"])
    assert discarded["status"] == "discarded"


def test_cli_commands_and_local_api_server(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    shutil.copytree(DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache"))

    res_init = runner.invoke(app, ["init", str(repo)])
    assert res_init.exit_code == 0
    assert (repo / "devpilot.yml").is_file()

    res_scan = runner.invoke(app, ["scan", str(repo), "--offline"])
    assert res_scan.exit_code == 0
    assert (repo / ".devpilot" / "reports" / "latest.json").is_file()

    res_plan = runner.invoke(app, ["plan", "--path", str(repo), "--deterministic", "--json"])
    assert res_plan.exit_code == 0
    plan_data = json.loads(res_plan.stdout)
    assert plan_data["source"] == "deterministic"
    assert len(plan_data["tasks"]) >= 3

    # Test local HTTP server endpoints and security headers
    server = create_server(repo, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
            status_json = json.loads(resp.read().decode("utf-8"))
            assert status_json["has_report"] is True
            assert status_json["repository"]["name"] == "demo"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/report", timeout=5) as resp:
            rep_json = json.loads(resp.read().decode("utf-8"))
            assert rep_json["summary"]["total"] >= 10

        # Static index.html is served
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
            assert "DevPilot" in html

        # POST without X-DevPilot: 1 is rejected with 403
        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/plan",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        assert exc_info.value.code == 403

        # POST with X-DevPilot: 1 succeeds
        good_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/plan",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with urllib.request.urlopen(good_req, timeout=5) as resp:
            post_plan = json.loads(resp.read().decode("utf-8"))
            assert "plan" in post_plan
    finally:
        server.shutdown()
        server.server_close()
