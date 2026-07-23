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

import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from pytest_triage.providers.base import BaseTriageClient

if TYPE_CHECKING:
    from pytest_triage.context import FailureContext

_DEFAULT_MODEL = "claude-sonnet-5"
_MODEL_ENV = "PYTEST_TRIAGE_MODEL"
_MAX_TOKENS = 1024
# Fail fast: the plugin's budget/timeout layer owns resilience, so SDK retries
# only fight the wall-clock cap and leave abandoned threads hitting the API.
_MAX_RETRIES = 0

_SYSTEM = """\
You are a test-failure triage assistant. You are given the context of a single
failed pytest test. Decide the single most likely cause, then call the
`record_verdict` tool exactly once. Never reply in prose.

Categories (choose one):
  - regression: the code under test changed and now misbehaves
  - flaky:      nondeterministic — timing, ordering, or external state
  - env:        environment or infrastructure — network, database, a missing
                service, or bad configuration
  - test_bug:   the test itself is wrong — bad assertion or stale fixture
  - unknown:    the evidence is insufficient to decide

Keep the hypothesis to one sentence. Suggest a concrete fix when one is clear,
otherwise leave it null. Judge only from the provided context.
"""

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
    ``PYTEST_TRIAGE_MODEL`` environment variable or the ``model`` argument. The
    API key is read from ``ANTHROPIC_API_KEY`` by the SDK unless passed here.
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

    def _render_prompt(self, ctx: FailureContext) -> str:
        return (
            f"nodeid: {ctx.nodeid}\n"
            f"phase: {ctx.phase}\n"
            f"exception: {ctx.exc_type}: {ctx.exc_message}\n"
            f"traceback:\n{ctx.traceback}\n"
            f"stdout tail:\n{ctx.stdout_tail}\n"
            f"stderr tail:\n{ctx.stderr_tail}\n"
        )

    def _request(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "record_verdict"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return json.dumps(block.input)
        return ""  # no tool_use block -> parser yields category="unknown"

    def close(self) -> None:
        self._client.close()


def _missing_dependency_error() -> Exception:
    return pytest.UsageError(
        "pytest-triage: the 'anthropic' provider requires the anthropic package; "
        "install it with: pip install 'pytest-triage[anthropic]'"
    )
