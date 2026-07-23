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

from pytest_triage.context import FailureContext
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
