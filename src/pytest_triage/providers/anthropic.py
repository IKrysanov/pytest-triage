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

"""AnthropicClient: LLM triage via the Anthropic Messages API (optional extra).

Requires ``pytest-triage[anthropic]``. The ``anthropic`` package is imported
lazily so that resolving or importing this module never fails when the extra is
absent — the clear error is raised only when a client is actually constructed.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from pytest_triage.providers._prompt import SYSTEM_PROMPT
from pytest_triage.providers.base import (
    BaseTriageClient,
    redact_nodeid,
    render_sections,
)

if TYPE_CHECKING:
    from pytest_triage.context import FailureContext

_DEFAULT_MODEL = "claude-sonnet-5"
_MODEL_ENV = "ANTHROPIC_MODEL"
_MAX_TOKENS = 1024
# Fail fast: the plugin's budget/timeout layer owns resilience, so SDK retries
# only fight the wall-clock cap and leave abandoned threads hitting the API.
_MAX_RETRIES = 0

# Strict tool use makes the model return a structured verdict directly; the
# schema mirrors Verdict. The tolerant BaseTriageClient parser still guards
# against an unexpected value (-> category="unknown").
_VERDICT_TOOL: dict[str, Any] = {
    "name": "record_verdict",
    "description": "Record the triage verdict for the failed test.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["regression", "flaky", "env", "test_bug", "unknown"],
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "hypothesis": {"type": "string"},
            "suggested_fix": {"type": ["string", "null"]},
        },
        "required": ["category", "confidence", "hypothesis", "suggested_fix"],
        "additionalProperties": False,
    },
}


class AnthropicClient(BaseTriageClient):
    """Triage via Anthropic tool use. Requires ``pytest-triage[anthropic]``.

    The model defaults to ``claude-sonnet-5`` and can be overridden with the
    ``ANTHROPIC_MODEL`` environment variable or the ``model`` argument. The API
    key is read from ``ANTHROPIC_API_KEY`` by the SDK unless passed here.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise _missing_dependency_error() from exc
        self._model = model or os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)
        # Typed Any: the SDK is untyped in CI (not installed); keep the create()
        # call consistent whether or not anthropic is present locally.
        self._client: Any = anthropic.Anthropic(
            api_key=api_key, max_retries=_MAX_RETRIES
        )

    @property
    def model(self) -> str:
        """The model queried for triage (surfaced as `ai_model` in the report)."""
        return self._model

    def _render_prompt(self, ctx: FailureContext) -> str:
        return render_sections(
            [
                ("nodeid: ", redact_nodeid(ctx.nodeid)),
                ("phase: ", ctx.phase),
                ("exception: ", f"{ctx.exc_type}: {ctx.exc_message}"),
                ("traceback:\n", ctx.traceback),
                ("stdout tail:\n", ctx.stdout_tail),
                ("stderr tail:\n", ctx.stderr_tail),
                ("log tail:\n", ctx.log_tail),
            ]
        )

    def _request(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "record_verdict"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return json.dumps(block.input)
        return ""  # no tool_use block -> parser yields category="unknown"

    def close(self) -> None:
        # Self-protecting and idempotent (the conformance kit calls it twice): a
        # second close, or an SDK that raises on teardown, must never surface.
        with contextlib.suppress(Exception):
            self._client.close()


def _missing_dependency_error() -> Exception:
    return pytest.UsageError(
        "pytest-triage: the 'anthropic' provider requires the anthropic package; "
        "install it with: pip install 'pytest-triage[anthropic]'"
    )
