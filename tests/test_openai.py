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

"""OpenAIClient: mocked API behaviour, error paths, and a live smoke test.

The `openai` package is not a dev/CI dependency, so the non-live tests inject a
fake `openai` module into `sys.modules` — the client imports it lazily.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any, cast

import pytest

from pytest_triage.context import FailureContext
from pytest_triage.providers.openai import OpenAIClient
from pytest_triage.testing import assert_conforms
from pytest_triage.verdict import CATEGORIES


def _completion(*, arguments: str | None = None, content: str | None = None) -> Any:
    """Build a fake chat completion carrying a tool call or plain content."""
    if arguments is not None:
        function = types.SimpleNamespace(arguments=arguments)
        message = types.SimpleNamespace(
            tool_calls=[types.SimpleNamespace(function=function)], content=None
        )
    else:
        message = types.SimpleNamespace(tool_calls=None, content=content)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch, completion: Any
) -> dict[str, Any]:
    """Inject a fake `openai` whose client returns `completion` from create()."""
    calls: dict[str, Any] = {"closed": False, "kwargs": None, "init_kwargs": {}}

    class _OpenAI:
        def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
            calls["init_kwargs"] = kwargs
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs: Any) -> Any:
            calls["kwargs"] = kwargs
            return completion

        def close(self) -> None:
            calls["closed"] = True

    fake = types.SimpleNamespace(OpenAI=_OpenAI)
    monkeypatch.setitem(sys.modules, "openai", cast("types.ModuleType", fake))
    return calls


def _verdict_args(**data: Any) -> str:
    return json.dumps(data)


def _ctx(exc_type: str = "AssertionError") -> FailureContext:
    return FailureContext(
        nodeid="tests/t.py::test_x",
        phase="call",
        outcome="failed",
        exc_type=exc_type,
        exc_message="assert 1 == 2",
        traceback="assert 1 == 2",
    )


def test_returns_verdict_from_function_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        _completion(
            arguments=_verdict_args(
                category="regression",
                confidence="high",
                hypothesis="h",
                suggested_fix="f",
            )
        ),
    )
    verdict = OpenAIClient().analyze(_ctx())
    assert verdict.category == "regression"
    assert verdict.confidence == "high"
    assert verdict.hypothesis == "h"
    assert verdict.suggested_fix == "f"
    assert calls["kwargs"]["tool_choice"]["function"]["name"] == "record_verdict"


def test_falls_back_to_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(
        monkeypatch,
        _completion(
            content='{"category": "flaky", "confidence": "medium", '
            '"hypothesis": "h", "suggested_fix": null}'
        ),
    )
    assert OpenAIClient().analyze(_ctx()).category == "flaky"


def test_prose_answer_becomes_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch, _completion(content="I cannot decide"))
    assert OpenAIClient().analyze(_ctx()).category == "unknown"


def test_empty_tool_arguments_fall_back_to_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tool call with empty arguments falls through to the message content.
    function = types.SimpleNamespace(arguments="")
    message = types.SimpleNamespace(
        tool_calls=[types.SimpleNamespace(function=function)],
        content='{"category": "env", "confidence": "low", '
        '"hypothesis": "h", "suggested_fix": null}',
    )
    completion = types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    _install_fake_openai(monkeypatch, completion)
    assert OpenAIClient().analyze(_ctx()).category == "env"


def test_empty_choices_becomes_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch, types.SimpleNamespace(choices=[]))
    assert OpenAIClient().analyze(_ctx()).category == "unknown"


def test_dict_tool_arguments_are_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    # A compatible endpoint may return already-parsed arguments (a dict) rather
    # than OpenAI's JSON string; both must yield the same verdict.
    function = types.SimpleNamespace(
        arguments={
            "category": "env",
            "confidence": "high",
            "hypothesis": "h",
            "suggested_fix": None,
        }
    )
    message = types.SimpleNamespace(
        tool_calls=[types.SimpleNamespace(function=function)], content=None
    )
    completion = types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    _install_fake_openai(monkeypatch, completion)
    assert OpenAIClient().analyze(_ctx()).category == "env"


def test_invalid_values_become_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(
        monkeypatch,
        _completion(
            arguments=_verdict_args(
                category="explosion",
                confidence="wat",
                hypothesis="h",
                suggested_fix=None,
            )
        ),
    )
    verdict = OpenAIClient().analyze(_ctx())
    assert verdict.category == "unknown"
    assert verdict.confidence == "low"


def test_api_error_propagates_from_analyze(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bad key makes the SDK raise; the TimedOutClient wrapper is what turns it
    # into a visible "unknown" verdict.
    class _OpenAI:
        def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs: Any) -> Any:
            raise RuntimeError("Error code: 401 - invalid api key")

    fake = types.SimpleNamespace(OpenAI=_OpenAI)
    monkeypatch.setitem(sys.modules, "openai", cast("types.ModuleType", fake))
    with pytest.raises(RuntimeError, match="invalid api key"):
        OpenAIClient().analyze(_ctx())


def test_sdk_configured_to_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_openai(monkeypatch, _completion(content=""))
    OpenAIClient()
    assert calls["init_kwargs"]["max_retries"] == 0


def test_close_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_openai(monkeypatch, _completion(content=""))
    client = OpenAIClient()
    client.close()
    assert calls["closed"] is True


def test_close_swallows_a_raising_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # An SDK that raises on teardown (already-closed session, dead socket) must
    # not turn a clean run into an error. close is fenced here, not just by the
    # caller.
    _install_fake_openai(monkeypatch, _completion(content=""))
    client = OpenAIClient()

    def _boom() -> None:
        raise RuntimeError("client already closed")

    client._client.close = _boom
    client.close()  # no raise
    client.close()  # idempotent


def test_model_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch, _completion(content=""))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert OpenAIClient()._model == "gpt-4o-mini"
    assert OpenAIClient().model == "gpt-4o-mini"  # public, for the report
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")  # provider-specific env
    assert OpenAIClient()._model == "gpt-4o"
    assert OpenAIClient(model="gpt-5")._model == "gpt-5"  # arg wins


def test_uses_configured_model_for_compatible_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An OpenAI-compatible endpoint (Kimi/DeepSeek/Ollama) is OPENAI_MODEL +
    # OPENAI_BASE_URL; the model we are given must reach the request verbatim.
    calls = _install_fake_openai(
        monkeypatch,
        _completion(
            arguments=_verdict_args(
                category="regression",
                confidence="low",
                hypothesis="h",
                suggested_fix=None,
            )
        ),
    )
    OpenAIClient(model="kimi-k2-0711-preview").analyze(_ctx())
    assert calls["kwargs"]["model"] == "kimi-k2-0711-preview"


def test_base_url_is_left_to_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    # OPENAI_BASE_URL (Kimi/DeepSeek/local) is read by the SDK; the provider must
    # not override it, so pointing at a compatible endpoint just works.
    calls = _install_fake_openai(monkeypatch, _completion(content=""))
    OpenAIClient()
    assert "base_url" not in calls["init_kwargs"]


def test_token_ceiling_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        _completion(
            arguments=_verdict_args(
                category="env", confidence="low", hypothesis="h", suggested_fix=None
            )
        ),
    )
    OpenAIClient().analyze(_ctx())
    assert calls["kwargs"]["max_tokens"] <= 1024


def test_conforms(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(
        monkeypatch,
        _completion(
            arguments=_verdict_args(
                category="env", confidence="medium", hypothesis="h", suggested_fix=None
            )
        ),
    )
    assert_conforms(OpenAIClient())


def test_missing_dependency_raises_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openai", cast("types.ModuleType", None))
    with pytest.raises(pytest.UsageError):
        OpenAIClient()


@pytest.mark.live
def test_live_analyze() -> None:
    import os

    pytest.importorskip("openai")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    client = OpenAIClient()
    try:
        verdict = client.analyze(_ctx())
    finally:
        client.close()
    assert verdict.category in CATEGORIES
