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

"""Providers: fakes, the BaseTriageClient template method, and conformance."""

from __future__ import annotations

import json

from pytest_triage.context import FailureContext
from pytest_triage.providers import redact_nodeid, render_sections
from pytest_triage.providers.base import BaseTriageClient
from pytest_triage.providers.fake import FakeTriageClient, OAuthFakeClient
from pytest_triage.testing import assert_conforms


def _ctx(exc_type: str | None = "AssertionError") -> FailureContext:
    return FailureContext(
        nodeid="t.py::a", phase="call", outcome="failed", exc_type=exc_type
    )


def test_fake_is_deterministic_by_exception() -> None:
    client = FakeTriageClient()
    assert client.analyze(_ctx("AssertionError")).category == "test_bug"
    assert client.analyze(_ctx("ConnectionError")).category == "env"
    assert client.analyze(_ctx("ValueError")).category == "regression"
    assert client.analyze(_ctx("AssertionError")) == client.analyze(
        _ctx("AssertionError")
    )


def test_fake_conforms() -> None:
    assert_conforms(FakeTriageClient())


def test_oauth_fake_refreshes_token_on_expiry() -> None:
    now = {"t": 0.0}
    client = OAuthFakeClient(ttl=2.0, clock=lambda: now["t"])
    client.analyze(_ctx())
    assert client.refresh_count == 1
    now["t"] = 1.0  # within TTL -> reused
    client.analyze(_ctx())
    assert client.refresh_count == 1
    now["t"] = 3.5  # past TTL -> refreshed on the fly
    client.analyze(_ctx())
    assert client.refresh_count == 2
    client.close()


def test_oauth_fake_conforms() -> None:
    assert_conforms(OAuthFakeClient(clock=lambda: 0.0))


class _EchoClient(BaseTriageClient):
    """Returns a canned response, exercising the base template + parser."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def _request(self, prompt: str) -> str:
        return self._raw


def test_base_template_parses_valid_json() -> None:
    raw = (
        '{"category": "regression", "confidence": "high", '
        '"hypothesis": "h", "suggested_fix": "f"}'
    )
    verdict = _EchoClient(raw).analyze(_ctx())
    assert verdict.category == "regression"
    assert verdict.confidence == "high"
    assert verdict.hypothesis == "h"
    assert verdict.suggested_fix == "f"


def test_base_template_tolerates_markdown_fence() -> None:
    raw = (
        "Sure!\n```json\n"
        '{"category":"flaky","confidence":"medium","hypothesis":"h"}\n'
        "```"
    )
    verdict = _EchoClient(raw).analyze(_ctx())
    assert verdict.category == "flaky"
    assert verdict.suggested_fix is None


def test_base_template_no_json_becomes_unknown() -> None:
    assert _EchoClient("not json at all").analyze(_ctx()).category == "unknown"


def test_base_template_malformed_json_becomes_unknown() -> None:
    assert _EchoClient("here: { not: valid }").analyze(_ctx()).category == "unknown"


def test_base_template_invalid_values_fall_back() -> None:
    raw = '{"category": "explosion", "confidence": "wat", "hypothesis": "h"}'
    verdict = _EchoClient(raw).analyze(_ctx())
    assert verdict.category == "unknown"
    assert verdict.confidence == "low"


def test_base_template_caps_a_runaway_model() -> None:
    raw = json.dumps(
        {
            "category": "env",
            "confidence": "low",
            "hypothesis": "h" * 5000,
            "suggested_fix": "f" * 5000,
        }
    )
    verdict = _EchoClient(raw).analyze(_ctx())
    assert len(verdict.hypothesis) < 1000
    assert verdict.suggested_fix is not None
    assert "truncated" in verdict.suggested_fix


def test_base_template_strips_control_characters_from_model_text() -> None:
    # A verdict is printed and re-printed downstream (the JSON report escapes
    # these, a consumer that prints a field back does not). Escape sequences in
    # model-authored text are never content, so they are dropped at the source.
    raw = json.dumps(
        {
            "category": "env",
            "confidence": "low",
            "hypothesis": "db down\x1b[2K\rall green\x1b[0m",
            "suggested_fix": "\x1b]0;OWNED\x07restart postgres",
        }
    )
    verdict = _EchoClient(raw).analyze(_ctx())
    assert verdict.hypothesis == "db down[2Kall green[0m"  # inert: the ESC is gone
    assert verdict.suggested_fix == "]0;OWNEDrestart postgres"
    assert "db down" in verdict.hypothesis  # the diagnostic content survives


def test_base_template_keeps_newlines_and_tabs_in_model_text() -> None:
    # Only control characters are dropped; a two-line fix stays two lines.
    raw = json.dumps(
        {"category": "env", "confidence": "low", "hypothesis": "line1\nline2\tx"}
    )
    assert _EchoClient(raw).analyze(_ctx()).hypothesis == "line1\nline2\tx"


# --- prompt helpers (public for provider authors) -------------------------


def test_render_sections_drops_empty_values() -> None:
    rendered = render_sections(
        [("a: ", "1"), ("b: ", ""), ("c:\n", "3")],
    )
    assert rendered == "a: 1\nc:\n3\n"


def test_redact_nodeid_scrubs_only_the_parametrization() -> None:
    secret = "AbCdEf0123456789abcdefXY"
    scrubbed = redact_nodeid(f"tests/test_auth.py::test_login[{secret}]")
    assert secret not in scrubbed
    assert scrubbed.startswith("tests/test_auth.py::test_login[")


def test_redact_nodeid_leaves_a_plain_nodeid_alone() -> None:
    nodeid = "tests/test_verylongmodulename.py::test_averylongfunctionname"
    assert redact_nodeid(nodeid) == nodeid


def test_base_prompt_skips_missing_context() -> None:
    class _Capturing(BaseTriageClient):
        prompt = ""

        def _request(self, prompt: str) -> str:
            type(self).prompt = prompt
            return ""

    bare = FailureContext(nodeid="t.py::a", phase="call", outcome="failed")
    _Capturing().analyze(bare)
    assert "traceback" not in _Capturing.prompt
    assert "exception" not in _Capturing.prompt
    assert "nodeid: t.py::a" in _Capturing.prompt
