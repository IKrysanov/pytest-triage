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

"""AnthropicClient: mocked API behaviour, error paths, and a live smoke test.

The `anthropic` package is not a dev/CI dependency, so the non-live tests inject
a fake `anthropic` module into `sys.modules` — the client imports it lazily.
"""

from __future__ import annotations

import sys
import types
from typing import Any, cast

import pytest

from pytest_triage.context import FailureContext
from pytest_triage.providers.anthropic import AnthropicClient
from pytest_triage.testing import assert_conforms
from pytest_triage.verdict import CATEGORIES


def _install_fake_anthropic(
    monkeypatch: pytest.MonkeyPatch, blocks: list[Any]
) -> dict[str, Any]:
    """Inject a fake `anthropic` whose client returns `blocks` from create()."""
    calls: dict[str, Any] = {"closed": False, "kwargs": None, "init_kwargs": {}}

    class _Anthropic:
        def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
            calls["init_kwargs"] = kwargs
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kwargs: Any) -> types.SimpleNamespace:
            calls["kwargs"] = kwargs
            return types.SimpleNamespace(content=blocks)

        def close(self) -> None:
            calls["closed"] = True

    fake = types.SimpleNamespace(Anthropic=_Anthropic)
    monkeypatch.setitem(sys.modules, "anthropic", cast("types.ModuleType", fake))
    return calls


def _tool_block(**data: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(type="tool_use", input=data)


def _ctx(exc_type: str = "AssertionError") -> FailureContext:
    return FailureContext(
        nodeid="tests/t.py::test_x",
        phase="call",
        outcome="failed",
        exc_type=exc_type,
        exc_message="assert 1 == 2",
        traceback="assert 1 == 2",
    )


def test_returns_verdict_from_tool_use(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_anthropic(
        monkeypatch,
        [
            _tool_block(
                category="regression",
                confidence="high",
                hypothesis="h",
                suggested_fix="f",
            )
        ],
    )
    verdict = AnthropicClient().analyze(_ctx())
    assert verdict.category == "regression"
    assert verdict.confidence == "high"
    assert verdict.hypothesis == "h"
    assert verdict.suggested_fix == "f"
    assert calls["kwargs"]["tool_choice"]["name"] == "record_verdict"


def test_no_tool_use_becomes_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_anthropic(
        monkeypatch, [types.SimpleNamespace(type="text", text="cannot decide")]
    )
    assert AnthropicClient().analyze(_ctx()).category == "unknown"


def test_invalid_values_become_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_anthropic(
        monkeypatch,
        [
            _tool_block(
                category="explosion",
                confidence="wat",
                hypothesis="h",
                suggested_fix=None,
            )
        ],
    )
    verdict = AnthropicClient().analyze(_ctx())
    assert verdict.category == "unknown"
    assert verdict.confidence == "low"


def test_api_error_propagates_from_analyze(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bad key makes the SDK raise (a 401). The provider propagates it; the
    # TimedOutClient wrapper is what turns it into a visible "unknown" verdict.
    class _Anthropic:
        def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kwargs: Any) -> Any:
            raise RuntimeError("Error code: 401 - invalid x-api-key")

    fake = types.SimpleNamespace(Anthropic=_Anthropic)
    monkeypatch.setitem(sys.modules, "anthropic", cast("types.ModuleType", fake))
    with pytest.raises(RuntimeError, match="invalid x-api-key"):
        AnthropicClient().analyze(_ctx())


def test_sdk_configured_to_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retries are disabled so a rate-limited call fails fast (surfaced as a clear
    # unknown) instead of retrying past the wall-clock cap.
    calls = _install_fake_anthropic(monkeypatch, [])
    AnthropicClient()
    assert calls["init_kwargs"]["max_retries"] == 0


def test_close_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_anthropic(monkeypatch, [])
    client = AnthropicClient()
    client.close()
    assert calls["closed"] is True


def test_model_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_anthropic(monkeypatch, [])
    monkeypatch.delenv("PYTEST_TRIAGE_MODEL", raising=False)
    assert AnthropicClient()._model == "claude-sonnet-5"
    monkeypatch.setenv("PYTEST_TRIAGE_MODEL", "claude-haiku-4-5")
    assert AnthropicClient()._model == "claude-haiku-4-5"
    assert AnthropicClient(model="claude-opus-4-8")._model == "claude-opus-4-8"


def test_conforms(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_anthropic(
        monkeypatch,
        [
            _tool_block(
                category="env",
                confidence="medium",
                hypothesis="h",
                suggested_fix=None,
            )
        ],
    )
    assert_conforms(AnthropicClient())


def test_missing_dependency_raises_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", cast("types.ModuleType", None))
    with pytest.raises(pytest.UsageError):
        AnthropicClient()


@pytest.mark.live
def test_live_analyze() -> None:
    import os

    pytest.importorskip("anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    client = AnthropicClient()
    try:
        verdict = client.analyze(_ctx())
    finally:
        client.close()
    assert verdict.category in CATEGORIES
