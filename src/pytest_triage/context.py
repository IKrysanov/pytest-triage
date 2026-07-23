# Copyright 2026 the pytest-triage contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FailureContext (public contract) and its collection from pytest reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pytest_triage.redact import redact

if TYPE_CHECKING:
    import pytest

    from pytest_triage.config import RedactMode

# Byte budgets. Truncation is by bytes, not characters, and always leaves a
# marker (see _truncate_*). These are internal knobs, not yet configurable.
_MAX_TRACEBACK_BYTES = 4000
_MAX_OUTPUT_TAIL_BYTES = 2000
_MAX_MESSAGE_BYTES = 1000


@dataclass(frozen=True)
class FailureContext:
    """Public contract. Frozen; new fields must be added with defaults only."""

    nodeid: str
    phase: str
    outcome: str
    exc_type: str | None = None
    exc_message: str | None = None
    traceback: str = ""
    duration: float = 0.0
    stdout_tail: str = ""
    stderr_tail: str = ""


def build_context(
    report: pytest.TestReport,
    *,
    exc_type: str | None,
    exc_message: str | None,
    redact_mode: RedactMode,
) -> FailureContext:
    """Assemble a FailureContext from a failed test report."""
    traceback = _truncate_tail(report.longreprtext, _MAX_TRACEBACK_BYTES)
    stdout_tail = _truncate_tail(report.capstdout, _MAX_OUTPUT_TAIL_BYTES)
    stderr_tail = _truncate_tail(report.capstderr, _MAX_OUTPUT_TAIL_BYTES)
    message = (
        _truncate_head(exc_message, _MAX_MESSAGE_BYTES) if exc_message else exc_message
    )
    if redact_mode == "strict":
        traceback = redact(traceback)
        stdout_tail = redact(stdout_tail)
        stderr_tail = redact(stderr_tail)
        if message:
            message = redact(message)
    return FailureContext(
        nodeid=report.nodeid,
        phase=report.when or "",
        outcome=report.outcome,
        exc_type=exc_type,
        exc_message=message,
        traceback=traceback,
        duration=report.duration,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def safe_message(exc: BaseException) -> str:
    """Best-effort str(exc); a broken __str__ must never break triage."""
    try:
        return str(exc)
    except Exception:
        return f"<unprintable {type(exc).__name__}>"


def _truncate_tail(text: str, limit: int) -> str:
    """Keep the last `limit` bytes (the crash end of a traceback), mark the cut."""
    raw = text.encode("utf-8", "replace")
    if len(raw) <= limit:
        return text
    dropped = len(raw) - limit
    kept = raw[-limit:].decode("utf-8", "ignore")
    return f"...[truncated {dropped} bytes]...\n{kept}"


def _truncate_head(text: str, limit: int) -> str:
    """Keep the first `limit` bytes (the start of a message), mark the cut."""
    raw = text.encode("utf-8", "replace")
    if len(raw) <= limit:
        return text
    dropped = len(raw) - limit
    kept = raw[:limit].decode("utf-8", "ignore")
    return f"{kept}\n...[truncated {dropped} bytes]..."
