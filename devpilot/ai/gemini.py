"""Gemini REST API provider (stdlib urllib, no heavy SDK required).

Includes automatic `.env` key discovery (without exposing values), model
fallback across common Gemini model IDs if a model returns HTTP 404 on the
user's API key tier, and detailed error diagnostics.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from devpilot.ai.provider import AIProvider, AIProviderError, AIStatus, is_ai_disabled
from devpilot.core.config import DevPilotConfig

DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"
FALLBACK_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-pro-latest",
]
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_ENV_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?(GEMINI_API_KEY|GOOGLE_API_KEY|DEVPILOT_GEMINI_MODEL)\s*=\s*(.*?)\s*$"
)


def _read_dotenv_vars(root: Path | None = None) -> dict[str, str]:
    """Read only GEMINI_API_KEY / GOOGLE_API_KEY / DEVPILOT_GEMINI_MODEL from a local `.env` if not in os.environ."""
    found: dict[str, str] = {}
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
    ]
    if root is not None:
        candidates.insert(0, root / ".env")
        candidates.insert(1, root.parent / ".env")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = _ENV_LINE_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1].strip()
                    if val and key not in found:
                        found[key] = val
        except OSError:
            continue
    return found


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"AI response was not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise AIProviderError("AI response JSON was not an object")
    return obj


def _normalize_model_name(name: str) -> str:
    name = name.strip()
    if name.startswith("models/"):
        name = name[len("models/") :]
    return name


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, config: DevPilotConfig) -> None:
        self.config = config
        extra_root = getattr(config, "root", None)
        dotenv = _read_dotenv_vars(extra_root)
        raw_model = (
            config.ai.model
            or os.environ.get("DEVPILOT_GEMINI_MODEL", "").strip()
            or dotenv.get("DEVPILOT_GEMINI_MODEL", "").strip()
            or DEFAULT_GEMINI_MODEL
        )
        norm_raw = raw_model.strip().lower()
        if any(
            k in norm_raw for k in ("llama", "mixtral", "gemma", "openai", "gpt", "qwen", "deepseek")
        ) or norm_raw in ("gemini-pro", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"):
            raw_model = DEFAULT_GEMINI_MODEL
        self.model = _normalize_model_name(raw_model)
        self._dotenv = dotenv

    def _api_key(self) -> str:
        return (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
            or self._dotenv.get("GEMINI_API_KEY", "").strip()
            or self._dotenv.get("GOOGLE_API_KEY", "").strip()
        )

    def status(self) -> AIStatus:
        disabled, reason = is_ai_disabled(self.config)
        if disabled:
            return AIStatus(available=False, provider=self.name, model=self.model, reason=reason)
        if not self._api_key():
            return AIStatus(
                available=False,
                provider=self.name,
                model=self.model,
                reason="GEMINI_API_KEY is not set (add it in .env or via Web Settings)",
            )
        return AIStatus(available=True, provider=self.name, model=self.model, reason="Ready")

    def _discover_available_model(self, timeout: float) -> str | None:
        """Query ListModels on the user's API key if static model names return 404."""
        req = urllib.request.Request(
            GEMINI_API_BASE,
            method="GET",
            headers={"x-goog-api-key": self._api_key()},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        for m in data.get("models") or []:
            methods = m.get("supportedGenerationMethods") or []
            name = _normalize_model_name(str(m.get("name") or ""))
            if (
                "generateContent" in methods
                and "gemini" in name
                and "vision" not in name
                and "embedding" not in name
            ):
                return name
        return None

    def _call_model(
        self, model_name: str, system_prompt: str, user_prompt: str, timeout: float
    ) -> dict[str, Any]:
        url = f"{GEMINI_API_BASE}/{model_name}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key(),
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def generate_json(self, system_prompt: str, user_prompt: str, timeout: float = 60) -> dict[str, Any]:
        st = self.status()
        if not st.available:
            raise AIProviderError(st.reason)

        effective_timeout = timeout or self.config.ai.timeout
        candidates_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        last_404_detail = ""
        raw: dict[str, Any] | None = None

        for candidate in candidates_to_try:
            try:
                raw = self._call_model(candidate, system_prompt, user_prompt, effective_timeout)
                self.model = candidate
                break
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    err_json = json.loads(exc.read().decode("utf-8", errors="ignore"))
                    err_body = str((err_json.get("error") or {}).get("message") or "")
                except Exception:  # noqa: BLE001
                    pass
                if exc.code == 404:
                    last_404_detail = err_body or f"model '{candidate}' not found"
                    continue
                if exc.code == 429:
                    raise AIProviderError(
                        "Gemini API rate limit exceeded (HTTP 429). Please retry shortly."
                    ) from exc
                detail = f" ({err_body})" if err_body else ""
                raise AIProviderError(f"Gemini API HTTP {exc.code}: {exc.reason}{detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise AIProviderError(f"Gemini API request failed: {exc}") from exc

        if raw is None:
            discovered = self._discover_available_model(effective_timeout)
            if discovered and discovered not in candidates_to_try:
                try:
                    raw = self._call_model(discovered, system_prompt, user_prompt, effective_timeout)
                    self.model = discovered
                except Exception as exc:  # noqa: BLE001
                    raise AIProviderError(f"Gemini API HTTP 404 ({last_404_detail})") from exc
            else:
                raise AIProviderError(
                    f"Gemini API HTTP 404: No compatible Gemini model found for this API key ({last_404_detail}). "
                    "Check that your GEMINI_API_KEY is a valid Google AI Studio key."
                )

        try:
            candidates = raw.get("candidates") or []
            parts = candidates[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (IndexError, KeyError, TypeError) as exc:
            raise AIProviderError("Gemini API returned an empty or unexpected response structure") from exc
        return extract_json_object(text)
