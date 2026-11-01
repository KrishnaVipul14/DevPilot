"""Gemini REST API provider (stdlib urllib, no heavy SDK required)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from devpilot.ai.provider import AIProvider, AIProviderError, AIStatus, is_ai_disabled
from devpilot.core.config import DevPilotConfig

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, config: DevPilotConfig) -> None:
        self.config = config
        self.model = (
            config.ai.model
            or os.environ.get("DEVPILOT_GEMINI_MODEL", "").strip()
            or DEFAULT_GEMINI_MODEL
        )

    def _api_key(self) -> str:
        return (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
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
                reason="GEMINI_API_KEY environment variable is not set",
            )
        return AIStatus(available=True, provider=self.name, model=self.model, reason="Ready")

    def generate_json(self, system_prompt: str, user_prompt: str, timeout: float = 60) -> dict[str, Any]:
        st = self.status()
        if not st.available:
            raise AIProviderError(st.reason)
        url = f"{GEMINI_API_BASE}/{self.model}:generateContent"
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
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.config.ai.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise AIProviderError("Gemini API rate limit exceeded (HTTP 429). Please retry shortly.") from exc
            raise AIProviderError(f"Gemini API HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"Gemini API request failed: {exc}") from exc

        try:
            candidates = raw.get("candidates") or []
            parts = candidates[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (IndexError, KeyError, TypeError) as exc:
            raise AIProviderError("Gemini API returned an empty or unexpected response structure") from exc
        return extract_json_object(text)
