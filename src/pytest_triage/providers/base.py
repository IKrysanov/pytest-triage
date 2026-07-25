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

"""TriageClient protocol, the BaseTriageClient template method, prompt helpers."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pytest_triage.redact import redact
from pytest_triage.verdict import (
    CATEGORIES,
    CONFIDENCES,
    Category,
    Confidence,
    Verdict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_triage.context import FailureContext

# A model is free to return a novel; the verdict ends up in the report and in
# alerts, so cap it. Bytes, with an explicit marker, per the truncation rule.
_MAX_VERDICT_BYTES = 600

# Parametrized ids embed argument values (test_login[sk-live-...]). The nodeid
# stays verbatim in the report — it is the rerun selector and pytest prints it
# anyway — but the copy that leaves the machine gets scrubbed.
_PARAMS = re.compile(r"\[.*\]")


@runtime_checkable
class TriageClient(Protocol):
    """The provider contract: analyze one failure, then close."""

    def analyze(self, ctx: FailureContext) -> Verdict:
        """Analyze one failure and return a Verdict."""

    def close(self) -> None:
        """Release any resources the client holds (sessions, tokens)."""


class BaseTriageClient:
    """Template method. A provider implements `_request` (the ~80 lines of
    transport); prompt rendering and tolerant parsing are inherited.

    `_render_prompt` here is a provisional structural default; the tuned,
    weak-model prompt wording is proposed with the first real provider (PR5).
    """

    def analyze(self, ctx: FailureContext) -> Verdict:
        return self._parse(self._request(self._render_prompt(ctx)), ctx)

    def close(self) -> None:
        return None

    def _render_prompt(self, ctx: FailureContext) -> str:
        return (
            "A pytest test failed. Reply with ONE JSON object with keys: "
            f"category (one of {', '.join(CATEGORIES)}), "
            f"confidence (one of {', '.join(CONFIDENCES)}), "
            "hypothesis (string), suggested_fix (string or null).\n\n"
        ) + render_sections(
            [
                ("nodeid: ", redact_nodeid(ctx.nodeid)),
                ("exception: ", _exception_line(ctx)),
                ("traceback:\n", ctx.traceback),
            ]
        )

    def _request(self, prompt: str) -> str:
        raise NotImplementedError  # provider-specific transport

    def _parse(self, raw: str, ctx: FailureContext) -> Verdict:
        data = _extract_json_object(raw)
        if data is None:
            return Verdict(
                category="unknown",
                hypothesis="Could not parse a verdict from the provider response.",
                confidence="low",
            )
        fix = data.get("suggested_fix")
        return Verdict(
            category=_coerce_category(data.get("category")),
            hypothesis=_cap(str(data.get("hypothesis") or "")),
            confidence=_coerce_confidence(data.get("confidence")),
            suggested_fix=_cap(str(fix)) if fix else None,
        )


def render_sections(sections: Sequence[tuple[str, str]]) -> str:
    """Join ``label + value`` sections, dropping the ones whose value is empty.

    Public for provider authors. Empty sections are dropped deliberately: an
    empty stdout tail still costs prompt tokens on every single call.
    """
    return "".join(f"{label}{value}\n" for label, value in sections if value)


def redact_nodeid(nodeid: str) -> str:
    """Scrub the parametrization part of a nodeid before it leaves the machine.

    Public for provider authors: call it on every nodeid you put in a prompt.
    Only the ``[...]`` section is scrubbed — module and function names carry the
    triage signal and are not secrets.
    """
    return _PARAMS.sub(lambda match: redact(match.group(0)), nodeid)


def _exception_line(ctx: FailureContext) -> str:
    if not ctx.exc_type and not ctx.exc_message:
        return ""
    return f"{ctx.exc_type}: {ctx.exc_message}"


def _cap(text: str) -> str:
    """Truncate model-authored text by bytes, leaving an explicit marker."""
    raw = text.encode("utf-8", "replace")
    if len(raw) <= _MAX_VERDICT_BYTES:
        return text
    dropped = len(raw) - _MAX_VERDICT_BYTES
    kept = raw[:_MAX_VERDICT_BYTES].decode("utf-8", "ignore")
    return f"{kept}...[truncated {dropped} bytes]..."


def _coerce_category(value: object) -> Category:
    for candidate in CATEGORIES:
        if value == candidate:
            return candidate
    return "unknown"


def _coerce_confidence(value: object) -> Confidence:
    for candidate in CONFIDENCES:
        if value == candidate:
            return candidate
    return "low"


def _extract_json_object(raw: str) -> dict[str, object] | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):  # pragma: no cover - a {..} slice is a dict
        return None
    return parsed
