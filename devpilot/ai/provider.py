"""Modular AI provider interface."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from devpilot.core.config import DevPilotConfig


class AIProviderError(Exception):
    """Raised when an AI provider call fails or returns invalid data."""


@dataclass
class AIStatus:
    available: bool
    provider: str
    model: str
    reason: str = ""


class AIProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def status(self) -> AIStatus:
        raise NotImplementedError

    @abstractmethod
    def generate_json(self, system_prompt: str, user_prompt: str, timeout: float = 60) -> dict[str, Any]:
        raise NotImplementedError


def get_ai_provider(config: DevPilotConfig) -> AIProvider:
    if config.ai.provider == "gemini":
        from devpilot.ai.gemini import GeminiProvider

        return GeminiProvider(config)
    from devpilot.ai.groq import GroqProvider

    return GroqProvider(config)


def is_ai_disabled(config: DevPilotConfig) -> tuple[bool, str]:
    if not config.ai.enabled:
        return True, "AI is disabled in devpilot.yml"
    env_flag = os.environ.get("DEVPILOT_AI_DISABLED", "").strip().lower()
    if env_flag in ("1", "true", "yes"):
        return True, "AI is disabled via DEVPILOT_AI_DISABLED"
    return False, ""
