"""Groq REST API provider (OpenAI-compatible chat completions endpoint).

Supports reading `GROQ_API_KEY` from environment variables or a local `.env`
file (which is ignored by Git and never committed), and automatically falls
back across Groq production models (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`,
`qwen/qwen3.8-27b`, `llama-3.3-70b-versatile`) or queries `/openai/v1/models`
if a model is retired or unavailable.
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

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
FALLBACK_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
USER_AGENT = "devpilot/0.1 (+https://github.com/KrishnaVipul14/DevPilot)"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?(GROQ_API_KEY|DEVPILOT_GROQ_MODEL)\s*=\s*(.*?)\s*$")


def _read_dotenv_vars() -> dict[str, str]:
    """Read `GROQ_API_KEY` / `DEVPILOT_GROQ_MODEL` from a local `.env` file if present."""
    found: dict[str, str] = {}
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        repo_root / ".env",
    ]
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
    # Strip <think>...</think> reasoning blocks if returned by reasoning models
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, config: DevPilotConfig) -> None:
        self.config = config
        self._dotenv = _read_dotenv_vars()
        self.model = (
            config.ai.model
            or os.environ.get("DEVPILOT_GROQ_MODEL", "").strip()
            or self._dotenv.get("DEVPILOT_GROQ_MODEL", "").strip()
            or DEFAULT_GROQ_MODEL
        )

    def _api_key(self) -> str:
        return (
            os.environ.get("GROQ_API_KEY", "").strip()
            or self._dotenv.get("GROQ_API_KEY", "").strip()
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
                reason="GROQ_API_KEY environment variable is not set",
            )
        return AIStatus(available=True, provider=self.name, model=self.model, reason="Ready")

    def _discover_models(self, timeout: float) -> list[str]:
        req = urllib.request.Request(
            GROQ_MODELS_URL,
            method="GET",
            headers={"Authorization": f"Bearer {self._api_key()}", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return []
        skip = ("whisper", "guard", "safeguard", "orpheus", "tts", "embed")
        return [
            str(m["id"])
            for m in (data.get("data") or [])
            if m.get("id") and not any(s in str(m["id"]).lower() for s in skip)
        ]

    def _call_model(
        self, model_name: str, system_prompt: str, user_prompt: str, timeout: float, use_json_format: bool = True
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        if use_json_format:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            GROQ_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
                "User-Agent": USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def generate_json(self, system_prompt: str, user_prompt: str, timeout: float = 60) -> dict[str, Any]:
        st = self.status()
        if not st.available:
            raise AIProviderError(st.reason)

        effective_timeout = timeout or self.config.ai.timeout
        candidates = [self.model] + [m for m in FALLBACK_GROQ_MODELS if m != self.model]
        raw: dict[str, Any] | None = None
        last_err = ""

        for idx, candidate in enumerate(candidates):
            try:
                raw = self._call_model(candidate, system_prompt, user_prompt, effective_timeout, use_json_format=True)
                self.model = candidate
                break
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    err_json = json.loads(exc.read().decode("utf-8", errors="ignore"))
                    err_body = str((err_json.get("error") or {}).get("message") or "")
                except Exception:  # noqa: BLE001
                    pass
                # Retry without response_format if the model rejects json_object mode
                if exc.code == 400 and "response_format" in err_body.lower():
                    try:
                        raw = self._call_model(
                            candidate, system_prompt, user_prompt, effective_timeout, use_json_format=False
                        )
                        self.model = candidate
                        break
                    except Exception:  # noqa: BLE001
                        pass
                if exc.code in (400, 404) and ("model" in err_body.lower() or exc.code == 404):
                    last_err = err_body or f"model '{candidate}' not found"
                    if idx == len(candidates) - 1:
                        for disc in self._discover_models(effective_timeout):
                            if disc not in candidates:
                                candidates.append(disc)
                    continue
                if exc.code == 429:
                    raise AIProviderError("Groq API rate limit exceeded (HTTP 429). Please retry shortly.") from exc
                detail = f" ({err_body})" if err_body else ""
                raise AIProviderError(f"Groq API HTTP {exc.code}: {exc.reason}{detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise AIProviderError(f"Groq API request failed: {exc}") from exc

        if raw is None:
            raise AIProviderError(f"Groq API error: no available model succeeded ({last_err})")

        try:
            choices = raw.get("choices") or []
            text = str(choices[0]["message"]["content"] or "")
        except (IndexError, KeyError, TypeError) as exc:
            raise AIProviderError("Groq API returned an empty or unexpected response structure") from exc
        return extract_json_object(text)
