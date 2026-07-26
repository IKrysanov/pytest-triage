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

"""OpenAIClient: LLM triage via the OpenAI Chat Completions API (optional extra).

Requires ``pytest-triage[openai]``. The ``openai`` package is imported lazily so
that resolving or importing this module never fails when the extra is absent —
the clear error is raised only when a client is actually constructed.
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

_DEFAULT_MODEL = "gpt-4o-mini"
_MODEL_ENV = "OPENAI_MODEL"
_MAX_TOKENS = 1024
# Fail fast: the plugin's budget/timeout layer owns resilience, so SDK retries
# only fight the wall-clock cap and leave abandoned threads hitting the API.
_MAX_RETRIES = 0
_FUNCTION_NAME = "record_verdict"

# Strict function calling makes the model return a structured verdict directly;
# the schema mirrors Verdict. The tolerant BaseTriageClient parser still guards
# against an unexpected value (-> category="unknown").
_VERDICT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": _FUNCTION_NAME,
        "description": "Record the triage verdict for the failed test.",
        "strict": True,
        "parameters": {
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
    },
}


class OpenAIClient(BaseTriageClient):
    """Triage via OpenAI function calling. Requires ``pytest-triage[openai]``.

    The model defaults to ``gpt-4o-mini`` and can be overridden with the
    ``OPENAI_MODEL`` environment variable or the ``model`` argument. The API key
    is read from ``OPENAI_API_KEY`` by the SDK unless passed here.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            import openai
        except ImportError as exc:
            raise _missing_dependency_error() from exc
        self._model = model or os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)
        # Typed Any: the SDK is untyped in CI (not installed); keep the create()
        # call consistent whether or not openai is present locally.
        self._client: Any = openai.OpenAI(api_key=api_key, max_retries=_MAX_RETRIES)

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
        completion = self._client.chat.completions.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "function", "function": {"name": _FUNCTION_NAME}},
        )
        return _extract_verdict_json(completion)

    def close(self) -> None:
        # Self-protecting and idempotent (the conformance kit calls it twice): a
        # second close, or an SDK that raises on teardown, must never surface.
        with contextlib.suppress(Exception):
            self._client.close()


def _extract_verdict_json(completion: Any) -> str:
    """Prefer the tool-call arguments; fall back to the message text.

    The forced function call returns its arguments as a JSON string. A model that
    answers in prose instead still yields a verdict via the tolerant parser, and
    an unrecognisable response yields "" -> category="unknown", never an error.
    """
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        arguments = getattr(getattr(tool_calls[0], "function", None), "arguments", None)
        if arguments:
            # OpenAI returns a JSON string; some compatible endpoints hand back
            # the parsed object — normalise both to JSON for the tolerant parser.
            return arguments if isinstance(arguments, str) else json.dumps(arguments)
    return str(getattr(message, "content", "") or "")


def _missing_dependency_error() -> Exception:
    return pytest.UsageError(
        "pytest-triage: the 'openai' provider requires the openai package; "
        "install it with: pip install 'pytest-triage[openai]'"
    )
