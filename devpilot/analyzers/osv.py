"""Minimal OSV.dev client (stdlib only) and CVSS v3 base-score calculator."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

OSV_API = "https://api.osv.dev/v1"
USER_AGENT = "devpilot (+https://github.com/KrishnaVipul14/DevPilot)"


class OSVError(Exception):
    pass


def _request(url: str, payload: dict | None, timeout: float) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise OSVError(f"OSV request failed: {exc}") from exc


def query_batch(packages: list[tuple[str, str]], timeout: float = 30) -> list[list[str]]:
    """Return vulnerability ids for each (name, version) PyPI package."""
    results: list[list[str]] = []
    for start in range(0, len(packages), 500):
        chunk = packages[start:start + 500]
        body = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in chunk]}
        data = _request(f"{OSV_API}/querybatch", body, timeout)
        items = data.get("results") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        for idx in range(len(chunk)):
            item = items[idx] if idx < len(items) and isinstance(items[idx], dict) else {}
            vulns = item.get("vulns", []) or []
            results.append([v["id"] for v in vulns if isinstance(v, dict) and "id" in v])
    return results


def get_vulns(ids: list[str], timeout: float = 30) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def fetch(vid: str) -> tuple[str, dict | None]:
        try:
            return vid, _request(f"{OSV_API}/vulns/{vid}", None, timeout)
        except OSVError:
            return vid, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for vid, data in pool.map(fetch, sorted(set(ids))):
            if data:
                out[vid] = data
    return out


# --- CVSS v3.x base score ----------------------------------------------------
_W = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PR = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}}


def _roundup(x: float) -> float:
    i = int(round(x * 100000))
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss3_base_score(vector: str) -> float | None:
    try:
        parts = dict(p.split(":", 1) for p in vector.split("/")[1:])
        scope = parts["S"]
        iss = 1 - (1 - _W["C"][parts["C"]]) * (1 - _W["I"][parts["I"]]) * (1 - _W["A"][parts["A"]])
        impact = 6.42 * iss if scope == "U" else 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
        expl = 8.22 * _W["AV"][parts["AV"]] * _W["AC"][parts["AC"]] * _PR[scope][parts["PR"]] * _W["UI"][parts["UI"]]
    except (KeyError, ValueError, IndexError):
        return None
    if impact <= 0:
        return 0.0
    raw = impact + expl if scope == "U" else 1.08 * (impact + expl)
    return _roundup(min(raw, 10))


def score_to_label(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0:
        return "low"
    return "info"
