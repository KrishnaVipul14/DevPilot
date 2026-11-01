"""Automated tests for DevPilot analyzers, graph, impact, memory, fixes, CLI, and server API."""

from __future__ import annotations

import json
import os
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
from devpilot.core.models import Confidence, Finding, Severity
from devpilot.core.scanner import run_scan
from devpilot.dashboard_server.server import create_server
from devpilot.fixes.patch_generator import propose_patch
from devpilot.fixes.patch_manager import apply_patch, discard_patch, verify_patch
from devpilot.memory.database import MemoryDB
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
    fp2 = compute_fingerprint(
        "code_health", "F401", "auth.py", "|`json`   imported but unused|import   json  "
    )
    assert fp1 == fp2


def test_repository_graph_and_symbol_impact(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    shutil.copytree(
        DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache")
    )
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
    shutil.copytree(
        DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache")
    )

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
    shutil.copytree(
        DEMO_APP, repo, ignore=shutil.ignore_patterns(".devpilot", "__pycache__", ".pytest_cache")
    )

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
            data=b'{"deterministic": true}',
            method="POST",
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with urllib.request.urlopen(good_req, timeout=15) as resp:
            post_plan = json.loads(resp.read().decode("utf-8"))
            assert "plan" in post_plan
    finally:
        server.shutdown()
        server.server_close()


def test_offline_dependency_unpinned_preservation(tmp_path: Path) -> None:
    repo = tmp_path / "offline_dep_repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn\nrequests==2.25.0\n", encoding="utf-8")
    report = run_scan(repo, offline=True, persist=False)
    # The unpinned finding must NOT be dropped in offline mode
    unpinned_findings = [f for f in report.findings if f.rule == "unpinned-dependencies"]
    assert len(unpinned_findings) == 1
    assert "fastapi" in unpinned_findings[0].evidence


def test_patch_manager_new_file_creation(tmp_path: Path) -> None:
    repo = tmp_path / "patch_new_file_repo"
    repo.mkdir()
    (repo / "app.py").write_text("import os\napi_key = os.getenv('API_KEY')\n", encoding="utf-8")
    report = run_scan(repo, offline=True, persist=True)
    missing_env_finding = next(f for f in report.findings if f.rule == "env-example-missing")
    assert missing_env_finding.fixable is True

    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    patch = propose_patch(ctx, missing_env_finding, engine="auto")
    assert patch["status"] == "proposed"
    assert ".env.example" in patch["files"]

    verified = verify_patch(ctx, patch["patch_id"])
    assert verified["status"] in ("verified", "partially_verified")

    applied = apply_patch(ctx, patch["patch_id"])
    assert applied["status"] == "applied"
    assert (repo / ".env.example").is_file()
    assert "API_KEY=" in (repo / ".env.example").read_text(encoding="utf-8")


def test_setup_doctor_subdirectory_and_fixable(tmp_path: Path) -> None:
    repo = tmp_path / "sub_repo"
    sub = repo / "services" / "auth"
    sub.mkdir(parents=True)
    (sub / "auth.py").write_text("import os\nsecret = os.environ['AUTH_SECRET']\n", encoding="utf-8")
    (sub / ".env").write_text("AUTH_SECRET=supersecret123\n", encoding="utf-8")

    gitutil.git(["init"], cwd=repo)
    gitutil.git(["config", "user.email", "test@example.com"], cwd=repo)
    gitutil.git(["config", "user.name", "Test User"], cwd=repo)
    # Do not ignore .env
    report = run_scan(repo, offline=True, persist=False)
    rules = {f.rule for f in report.findings}
    # It must detect that services/auth/.env is not ignored
    assert "env-file-not-ignored" in rules
    not_ignored = next(f for f in report.findings if f.rule == "env-file-not-ignored")
    assert "services/auth/.env" in not_ignored.file


def test_server_mime_and_path_traversal_protection(tmp_path: Path) -> None:
    server = create_server(tmp_path, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Directory traversal attempt should be rejected with 403
        traversal_req = urllib.request.Request(f"http://127.0.0.1:{port}/../../etc/passwd")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(traversal_req, timeout=5)
        assert exc_info.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_settings_and_repository_change_endpoints(tmp_path: Path) -> None:
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    (repo1 / "app.py").write_text("x = 1\n", encoding="utf-8")

    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / "app.py").write_text("y = 2\n", encoding="utf-8")

    server = create_server(repo1, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /api/settings
        req = urllib.request.Request(f"{base_url}/api/settings")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["repository"]["path"] == str(repo1)
            assert "ai" in data

        # 2. POST /api/settings (update AI provider and keys)
        update_body = json.dumps(
            {
                "provider": "gemini",
                "model": "gemini-1.5-flash",
                "gemini_api_key": "AIzaSyTestGeminiKey1234",
                "persist_to_env": False,
            }
        ).encode("utf-8")
        post_req = urllib.request.Request(
            f"{base_url}/api/settings",
            data=update_body,
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with urllib.request.urlopen(post_req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ai"]["provider"] == "gemini"
            assert data["ai"]["has_gemini_key"] is True
            assert "AIza••••1234" in data["ai"]["gemini_key_preview"]

        # 3. POST /api/repository (switch directory)
        repo_body = json.dumps({"path": str(repo2)}).encode("utf-8")
        repo_req = urllib.request.Request(
            f"{base_url}/api/repository",
            data=repo_body,
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with urllib.request.urlopen(repo_req, timeout=5) as resp:
            status = json.loads(resp.read().decode("utf-8"))
            assert status["repository"]["path"] == str(repo2)

        # 4. POST /api/repository invalid path -> 400
        bad_repo_body = json.dumps({"path": str(tmp_path / "does_not_exist")}).encode("utf-8")
        bad_req = urllib.request.Request(
            f"{base_url}/api/repository",
            data=bad_repo_body,
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        assert exc_info.value.code == 400

        # 5. POST /api/scan (trigger scan on active repo)
        scan_body = json.dumps({"offline": True}).encode("utf-8")
        scan_req = urllib.request.Request(
            f"{base_url}/api/scan",
            data=scan_body,
            headers={"Content-Type": "application/json", "X-DevPilot": "1"},
        )
        with urllib.request.urlopen(scan_req, timeout=10) as resp:
            scan_res = json.loads(resp.read().decode("utf-8"))
            assert "report" in scan_res
            assert scan_res["report"]["repository"]["path"] == str(repo2)
    finally:
        server.shutdown()
        server.server_close()
        for k in ("DEVPILOT_AI_PROVIDER", "DEVPILOT_AI_MODEL", "GEMINI_API_KEY", "GROQ_API_KEY"):
            os.environ.pop(k, None)


def test_new_project_module_discovery_and_ai_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEVPILOT_AI_PROVIDER", raising=False)
    monkeypatch.delenv("DEVPILOT_AI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    # Standalone non-git project with nested packages and local sibling imports
    proj = tmp_path / "standalone_project"
    (proj / "app").mkdir(parents=True)
    (proj / "app" / "models.py").write_text("class User:\n    pass\n", encoding="utf-8")
    (proj / "app" / "services.py").write_text(
        "from models import User\nimport os\ndef get_user():\n    unused = 123\n    return User()\n",
        encoding="utf-8",
    )
    (proj / ".env").write_text("GROQ_API_KEY=gsk_test_key_from_env_123456\n", encoding="utf-8")

    cfg = load_config(proj)
    assert cfg.root == proj.resolve()

    # Verify AI provider loaded the key from proj/.env and uses the valid default model
    from devpilot.ai.provider import get_ai_provider

    provider = get_ai_provider(cfg)
    assert provider.name == "groq"
    assert provider.model == "llama-3.3-70b-versatile"
    status = provider.status()
    assert status.available is True

    # Scan standalone project
    report = run_scan(proj, config=cfg, offline=True, persist=True)
    assert report.summary.files_scanned >= 2
    assert report.graph is not None
    assert report.graph.modules >= 2

    # Verify that Ruff findings in an external directory outside cwd are kept (not dropped)
    rules = {f.rule for f in report.findings}
    assert "F841" in rules  # unused local variable in services.py


def test_android_project_scanning_and_fixes(tmp_path: Path) -> None:
    android_repo = tmp_path / "my_android_app"
    (android_repo / "app" / "src" / "main").mkdir(parents=True)

    manifest_xml = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.insecureapp">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.READ_SMS" />

    <application
        android:allowBackup="true"
        android:debuggable="true"
        android:usesCleartextTraffic="true"
        android:label="InsecureApp">
        <activity android:name=".MainActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
        <activity android:name=".PaymentActivity">
            <intent-filter>
                <action android:name="com.example.ACTION_PAY" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
    (android_repo / "app" / "src" / "main" / "AndroidManifest.xml").write_text(manifest_xml, encoding="utf-8")

    build_gradle = """plugins {
    id 'com.android.application'
    id 'kotlin-android'
}

android {
    compileSdk 33
    defaultConfig {
        minSdk 21
        targetSdk 31
    }
    signingConfigs {
        release {
            storePassword "hardcoded_keystore_secret"
        }
    }
}

repositories {
    maven { url 'http://insecure-repo.example.com/maven2' }
    mavenCentral()
}

dependencies {
    implementation 'com.squareup.okhttp3:okhttp:4.9.0'
    implementation 'com.google.code.gson:gson'
}
"""
    (android_repo / "build.gradle").write_text(build_gradle, encoding="utf-8")

    kt_src = """package com.example.insecureapp

import androidx.appcompat.app.AppCompatActivity
import android.os.Bundle
import javax.crypto.Cipher

class OrderRepository {
    fun submitOrder(): Boolean = true
}

class MainActivity : AppCompatActivity() {
    private val repo = OrderRepository()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val cipher = Cipher.getInstance("AES/ECB/PKCS5Padding")
    }

    fun doSecretAction() {
        println("Performing action")
    }
}
"""
    (android_repo / "app" / "src" / "main" / "MainActivity.kt").write_text(kt_src, encoding="utf-8")

    report = run_scan(android_repo, offline=True, persist=True)

    assert report.summary.files_scanned >= 3
    assert report.graph is not None
    assert report.graph.modules >= 1
    assert report.graph.routes >= 1
    assert report.graph.classes >= 1
    assert report.graph.functions >= 2

    rules = {f.rule for f in report.findings}
    assert "android-debuggable" in rules
    assert "android-cleartext-traffic" in rules
    assert "android-allow-backup" in rules
    assert "android-exported-missing" in rules
    assert "android-dangerous-permission" in rules
    assert "android-min-sdk-outdated" in rules
    assert "android-target-sdk-outdated" in rules
    assert "android-insecure-repo-url" in rules
    assert "android-hardcoded-keystore-password" in rules
    assert "android-insecure-cipher" in rules

    unpinned_rules = [
        f for f in report.findings if f.module == "dependencies" and f.rule == "unpinned-dependencies"
    ]
    assert len(unpinned_rules) >= 1

    ctx = RepoContext(root=android_repo, config=load_config(android_repo), offline=True)
    cleartext_finding = next(f for f in report.findings if f.rule == "android-cleartext-traffic")
    patch = propose_patch(ctx, cleartext_finding, engine="auto")
    assert patch["engine"] == "ruff"
    assert 'android:usesCleartextTraffic="false"' in patch["diff"]

    repo_url_finding = next(f for f in report.findings if f.rule == "android-insecure-repo-url")
    patch_repo = propose_patch(ctx, repo_url_finding, engine="auto")
    assert "https://insecure-repo.example.com/maven2" in patch_repo["diff"]

    # Verify and apply Android patch in isolation
    verified = verify_patch(ctx, patch["patch_id"])
    assert verified["status"] == "verified"
    applied = apply_patch(ctx, patch["patch_id"])
    assert applied["status"] == "applied"
    updated_xml = (android_repo / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:usesCleartextTraffic="false"' in updated_xml


def test_multilang_dependency_fixes_and_sqlite_resilience(tmp_path: Path) -> None:
    repo = tmp_path / "polyglot_app"
    repo.mkdir()

    # 1. SQLite WAL mode resilience
    db = MemoryDB(repo)
    with db._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    # 2. Node.js package.json vulnerability auto-fix and JSON validation
    pkg_json = '{\n  "name": "sample",\n  "dependencies": {\n    "axios": "0.21.1"\n  }\n}\n'
    (repo / "package.json").write_text(pkg_json, encoding="utf-8")

    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    f_node = Finding(
        module="dependencies",
        rule="vulnerable-dependency",
        severity=Severity.HIGH,
        title="axios 0.21.1 has known SSRF vulnerability",
        file="package.json",
        line=4,
        evidence="axios 0.21.1",
        confidence=Confidence.HIGH,
        metadata={"package": "axios", "installed_version": "0.21.1", "fixed_versions": ["0.21.2"]},
    )
    patch_node = propose_patch(ctx, f_node, engine="auto")
    assert '"axios": "0.21.2"' in patch_node["diff"]
    ver_node = verify_patch(ctx, patch_node["patch_id"])
    assert ver_node["status"] == "verified"
    apply_patch(ctx, patch_node["patch_id"])
    assert '"axios": "0.21.2"' in (repo / "package.json").read_text(encoding="utf-8")

    # 3. Gradle build.gradle vulnerability auto-fix
    gradle_file = "dependencies {\n    implementation 'com.squareup.okhttp3:okhttp:4.9.0'\n}\n"
    (repo / "build.gradle").write_text(gradle_file, encoding="utf-8")

    f_gradle = Finding(
        module="dependencies",
        rule="vulnerable-dependency",
        severity=Severity.HIGH,
        title="okhttp 4.9.0 has known vulnerability",
        file="build.gradle",
        line=2,
        evidence="okhttp 4.9.0",
        confidence=Confidence.HIGH,
        metadata={
            "package": "com.squareup.okhttp3:okhttp",
            "installed_version": "4.9.0",
            "fixed_versions": ["4.9.3"],
        },
    )
    patch_gradle = propose_patch(ctx, f_gradle, engine="auto")
    assert "'com.squareup.okhttp3:okhttp:4.9.3'" in patch_gradle["diff"]
    ver_gradle = verify_patch(ctx, patch_gradle["patch_id"])
    assert ver_gradle["status"] == "verified"
    apply_patch(ctx, patch_gradle["patch_id"])
    assert "'com.squareup.okhttp3:okhttp:4.9.3'" in (repo / "build.gradle").read_text(encoding="utf-8")


def test_route_detection_and_critical_health_and_hashing(tmp_path: Path) -> None:
    from devpilot.fixes.patch_generator import sha256_text

    # 1. Hashing robustness
    # Line endings CRLF vs LF produce identical hashes
    assert sha256_text("line1\r\nline2\r\n") == sha256_text("line1\nline2\n")
    # Path separators \ vs / produce identical fingerprints
    assert compute_fingerprint("mod", "rule", "src\\api\\v1.py", "anchor") == compute_fingerprint(
        "mod", "rule", "src/api/v1.py", "anchor"
    )

    # 2. Comprehensive API Route Detection across Python, Next.js, Express, and Kotlin
    repo = tmp_path / "routes_and_security_app"
    repo.mkdir()

    # FastAPI route with keyword path and missing leading slash
    py_code = """
from fastapi import FastAPI
app = FastAPI()

@app.get(path="items")
def get_items():
    return []

@app.post("/login")
def login():
    return {"token": "123"}
"""
    (repo / "main.py").write_text(py_code, encoding="utf-8")

    # Django urlpatterns
    django_code = """
from django.urls import path

urlpatterns = [
    path("api/v1/users/", list_users),
]
"""
    (repo / "urls.py").write_text(django_code, encoding="utf-8")

    # Next.js App Router route.ts
    (repo / "app" / "api" / "checkout").mkdir(parents=True)
    next_ts = """
export async function POST(req) {
    return new Response(JSON.stringify({ ok: true }));
}
export async function GET(req) {
    return new Response(JSON.stringify({ status: "healthy" }));
}
"""
    (repo / "app" / "api" / "checkout" / "route.ts").write_text(next_ts, encoding="utf-8")

    # Express.js route
    express_js = """
const express = require('express');
const app = express();
app.get('/api/health', (req, res) => res.json({ ok: true }));
"""
    (repo / "server.js").write_text(express_js, encoding="utf-8")

    # Kotlin Retrofit route
    kt_code = """
package com.example.api
import retrofit2.http.GET

interface ApiClient {
    @GET("v2/profile")
    suspend fun getProfile(): String
}
"""
    (repo / "ApiClient.kt").write_text(kt_code, encoding="utf-8")

    # Critical security issue: hardcoded private key
    sec_code = """
# Secret key embedded
KEY = \"\"\"-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Yq3...
-----END RSA PRIVATE KEY-----\"\"\"
"""
    (repo / "secrets_leak.py").write_text(sec_code, encoding="utf-8")

    # Scan project
    report = run_scan(repo, offline=True, persist=True)

    # Verify commit hash generated for non-git repository
    assert report.repository.commit is not None
    assert report.repository.commit.startswith("tree-")

    # Verify all API routes detected across frameworks
    assert report.graph is not None
    assert report.graph.routes >= 6

    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    graph = RepoGraph.build(ctx)
    routes = {n.name for n in graph.nodes.values() if n.kind == "route"}

    assert "GET /items" in routes
    assert "POST /login" in routes
    assert "ALL /api/v1/users" in routes
    assert "POST /api/checkout" in routes
    assert "GET /api/checkout" in routes
    assert "GET /api/health" in routes
    assert "GET /v2/profile" in routes

    # Verify Critical Security finding and Health Score penalty
    crit_findings = [f for f in report.findings if f.severity == Severity.CRITICAL]
    assert len(crit_findings) >= 1
    assert any("Private key" in f.title or "Private key" in f.evidence for f in crit_findings)
    assert report.summary.by_severity["critical"] >= 1
    # Health score must reflect the 25-point penalty for critical issues
    assert report.summary.health_score <= 75


def test_react_project_module_and_env_discovery(tmp_path: Path) -> None:
    repo = tmp_path / "react_web_app"
    repo.mkdir()

    # package.json
    pkg = {
        "name": "my-react-app",
        "version": "1.0.0",
        "dependencies": {
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
        },
    }
    (repo / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    # .env.example
    env_example = """# React & Vite environment variables
REACT_APP_API_URL=https://api.example.com
VITE_AUTH_TOKEN=secret-token-here
REACT_APP_FEATURE_FLAG=true
STALE_UNUSED_CONFIG=unused_val
"""
    (repo / ".env.example").write_text(env_example, encoding="utf-8")

    # src/components/Header.jsx
    src = repo / "src"
    src.mkdir()
    components = src / "components"
    components.mkdir()

    header_jsx = """
import React from 'react';
import './Header.css';

export default function Header({ title }) {
    return <header><h1>{title}</h1></header>;
}

export const Navigation = () => {
    return <nav><a href="/">Home</a></nav>;
};
"""
    (components / "Header.jsx").write_text(header_jsx, encoding="utf-8")

    # src/App.jsx
    app_jsx = """
import React, { useState, useEffect } from 'react';
import Header, { Navigation } from './components/Header';
import { fetchConfig } from './api';

export class ErrorBoundary extends React.Component {
    render() {
        return this.props.children;
    }
}

export const App = () => {
    const apiUrl = process.env.REACT_APP_API_URL;
    const isFeatureEnabled = process.env['REACT_APP_FEATURE_FLAG'] || 'false';
    const stripeKey = process.env.REACT_APP_STRIPE_KEY;

    return (
        <ErrorBoundary>
            <Header title="React App" />
            <Navigation />
            <div>API: {apiUrl}</div>
        </ErrorBoundary>
    );
};

export default App;
"""
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")

    # src/api.ts
    api_ts = """
import axios from 'axios';

export async function fetchConfig() {
    const token = import.meta.env.VITE_AUTH_TOKEN;
    const client = import.meta.env['VITE_CLIENT_ID'] ?? 'default_client';
    return { token, client };
}
"""
    (src / "api.ts").write_text(api_ts, encoding="utf-8")

    # Scan the React project
    report = run_scan(repo, offline=True, persist=True)

    # 1. Module and component discovery assertions
    assert report.graph is not None
    # Must discover React modules (Header.jsx, App.jsx, api.ts)
    assert report.graph.modules >= 3
    # Must discover functions and React functional components (Header, Navigation, App, fetchConfig)
    assert report.graph.functions >= 4
    # Must discover classes (ErrorBoundary)
    assert report.graph.classes >= 1

    ctx = RepoContext(root=repo, config=load_config(repo), offline=True)
    graph = RepoGraph.build(ctx)

    node_names = {n.name for n in graph.nodes.values()}
    assert "Header" in node_names
    assert "Navigation" in node_names
    assert "App" in node_names
    assert "fetchConfig" in node_names
    assert "ErrorBoundary" in node_names

    # Check import edges exist
    import_edges = [e for e in graph.edges if e.kind == "imports"]
    assert len(import_edges) >= 2

    # 2. .env.example analysis assertions
    setup_findings = [f for f in report.findings if f.module == "setup_doctor"]
    unused_env_findings = [f for f in setup_findings if f.rule == "env-unused-in-code"]
    unused_vars = {f.metadata.get("variable") for f in unused_env_findings}

    # REACT_APP_API_URL, VITE_AUTH_TOKEN, REACT_APP_FEATURE_FLAG are used in JS/TS!
    # They MUST NOT be flagged as unused
    assert "REACT_APP_API_URL" not in unused_vars
    assert "VITE_AUTH_TOKEN" not in unused_vars
    assert "REACT_APP_FEATURE_FLAG" not in unused_vars

    # STALE_UNUSED_CONFIG is never used, so it SHOULD be flagged
    assert "STALE_UNUSED_CONFIG" in unused_vars
    stale_f = next(f for f in unused_env_findings if f.metadata.get("variable") == "STALE_UNUSED_CONFIG")
    # Message should refer to JavaScript/TypeScript code, not Python code
    assert "JavaScript/TypeScript" in stale_f.title

    # REACT_APP_STRIPE_KEY is used in App.jsx without default and missing from .env.example
    missing_env_findings = [f for f in setup_findings if f.rule == "env-missing-from-example"]
    missing_vars = {f.metadata.get("variable") for f in missing_env_findings}
    assert "REACT_APP_STRIPE_KEY" in missing_vars
