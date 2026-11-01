"""Local-only HTTP server serving both the static Next.js dashboard and `/api/*`."""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from devpilot.dashboard_server.api import APIHTTPError, LocalAPI

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

STATIC_MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
}

_EXPLAIN_RE = re.compile(r"^/api/findings/([^/]+)/explain/?$")
_FIX_RE = re.compile(r"^/api/findings/([^/]+)/fix/?$")
_PATCH_ACTION_RE = re.compile(r"^/api/patches/([^/]+)/(verify|apply|discard)/?$")


def _valid_host(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.split(":", 1)[0].strip().lower()
    return host in ALLOWED_HOSTS


class DevPilotRequestHandler(BaseHTTPRequestHandler):
    api: LocalAPI
    static_dir: Path

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_security(self, is_post: bool = False) -> bool:
        if not _valid_host(self.headers.get("Host")):
            self._send_json(403, {"error": "Forbidden Host header"})
            return False
        if is_post:
            if self.headers.get("X-DevPilot") != "1":
                self._send_json(403, {"error": "Missing required X-DevPilot: 1 header"})
                return False
        return True

    def do_GET(self) -> None:
        if not self._check_security(is_post=False):
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            try:
                if path.rstrip("/") == "/api/status":
                    self._send_json(200, self.api.get_status())
                elif path.rstrip("/") == "/api/report":
                    self._send_json(200, self.api.get_report())
                elif path.rstrip("/") == "/api/history":
                    self._send_json(200, self.api.get_history())
                elif path.rstrip("/") == "/api/graph":
                    self._send_json(200, self.api.get_graph())
                elif path.rstrip("/") == "/api/impact":
                    self._send_json(200, self.api.get_impact(query))
                elif path.rstrip("/") == "/api/plan":
                    self._send_json(200, self.api.get_plan())
                elif path.rstrip("/") == "/api/patches":
                    self._send_json(200, self.api.get_patches())
                elif path.rstrip("/") == "/api/settings":
                    self._send_json(200, self.api.get_settings())
                elif path.rstrip("/") == "/api/mermaid":
                    self._send_json(200, self.api.get_mermaid())
                else:
                    self._send_json(404, {"error": f"Unknown API endpoint {path}"})
            except APIHTTPError as exc:
                self._send_json(exc.status_code, {"error": exc.message})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": f"Internal error: {exc}"})
            return

        self._serve_static(path)

    def _dispatch_post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        norm = path.rstrip("/")
        handlers = {
            "/api/plan": lambda: self.api.post_plan(body),
            "/api/settings": lambda: self.api.post_settings(body),
            "/api/repository": lambda: self.api.post_repository(body),
            "/api/demo": lambda: self.api.post_demo(),
            "/api/scan": lambda: self.api.post_scan(body),
            "/api/ask": lambda: self.api.post_ask(body),
            "/api/testgen": lambda: self.api.post_testgen(body),
        }
        if norm in handlers:
            return 200, handlers[norm]()

        m = _EXPLAIN_RE.match(path)
        if m:
            return 200, self.api.post_explain(m.group(1))
        m = _FIX_RE.match(path)
        if m:
            return 200, self.api.post_fix(m.group(1), body)
        m = _PATCH_ACTION_RE.match(path)
        if m:
            return 200, self.api.post_patch_action(m.group(1), m.group(2))
        return 404, {"error": f"Unknown POST endpoint {path}"}

    def do_POST(self) -> None:
        if not self._check_security(is_post=True):
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw_body or "{}")
            if not isinstance(body, dict):
                body = {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Request body must be valid JSON"})
            return

        try:
            code, res = self._dispatch_post(path, body)
            self._send_json(code, res)
        except APIHTTPError as exc:
            self._send_json(exc.status_code, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": f"Internal error: {exc}"})

    def _serve_static(self, url_path: str) -> None:
        clean = urllib.parse.unquote(url_path).lstrip("/").replace("\\", "/")
        if ".." in clean.split("/"):
            self._send_json(403, {"error": "Forbidden path traversal"})
            return

        static_root = self.static_dir.resolve()
        candidates = [
            static_root / clean,
            static_root / clean / "index.html",
            static_root / f"{clean}.html",
        ]
        target: Path | None = None
        for cand in candidates:
            try:
                resolved = cand.resolve()
                resolved.relative_to(static_root)
            except ValueError:
                continue
            if resolved.is_file():
                target = resolved
                break

        if target is None:
            fallback = static_root / "index.html"
            if fallback.is_file() and not clean.startswith("_next/"):
                target = fallback
            else:
                self._send_json(404, {"error": f"Not found: {url_path}"})
                return

        ext = target.suffix.lower()
        ctype = STATIC_MIME_TYPES.get(ext)
        if not ctype:
            ctype, _ = mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_server(root: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("For security, DevPilot local server only binds to 127.0.0.1.")

    class BoundHandler(DevPilotRequestHandler):
        pass

    BoundHandler.api = LocalAPI(root)
    BoundHandler.static_dir = STATIC_DIR
    return ThreadingHTTPServer((host, port), BoundHandler)
