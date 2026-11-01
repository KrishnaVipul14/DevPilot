"""Safe subprocess execution helpers (no shell, always with timeouts)."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run(
    args: Sequence[str],
    cwd: str | Path | None = None,
    timeout: float = 60,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> ProcResult:
    """Run a command without a shell. Never raises on non-zero exit or timeout."""
    start = time.monotonic()
    merged_env = {**os.environ, **(env or {})}
    merged_env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(
            list(args),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged_env,
            input=input_text,
            shell=False,
        )
        return ProcResult(
            list(args),
            proc.returncode,
            proc.stdout or "",
            proc.stderr or "",
            int((time.monotonic() - start) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ProcResult(
            list(args),
            -1,
            out,
            err + f"\nTimed out after {timeout}s",
            int((time.monotonic() - start) * 1000),
            timed_out=True,
        )
    except FileNotFoundError as exc:
        return ProcResult(list(args), 127, "", str(exc), int((time.monotonic() - start) * 1000))
