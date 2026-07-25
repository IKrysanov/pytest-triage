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

"""GigaChatClient: mocked API behaviour, error paths, and a live smoke test.

The `gigachat` package is not a dev/CI dependency, so the non-live tests inject
a fake `gigachat` module into `sys.modules` — the client imports it lazily.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any, cast

import pytest

from pytest_triage.context import FailureContext
from pytest_triage.providers.gigachat import GigaChatClient
from pytest_triage.testing import assert_conforms
from pytest_triage.verdict import CATEGORIES
from pytest_triage.wrappers import TimedOutClient, degraded_reason
from tests.support import run_triage


def _install_fake_gigachat(
    monkeypatch: pytest.MonkeyPatch, completion: Any
) -> dict[str, Any]:
    """Inject a fake `gigachat` whose client returns `completion` from chat()."""
    calls: dict[str, Any] = {"closed": False, "payload": None, "init_kwargs": {}}

    class _GigaChat:
        def __init__(self, **kwargs: Any) -> None:
            calls["init_kwargs"] = kwargs

        def chat(self, payload: Any) -> Any:
            calls["payload"] = payload
            if isinstance(completion, Exception):
                raise completion
            return completion

        def close(self) -> None:
            calls["closed"] = True

    fake = types.SimpleNamespace(GigaChat=_GigaChat)
    monkeypatch.setitem(sys.modules, "gigachat", cast("types.ModuleType", fake))
    return calls


def _completion(
    *, function_call: Any = None, content: str = ""
) -> types.SimpleNamespace:
    message = types.SimpleNamespace(function_call=function_call, content=content)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _function_call(**arguments: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(name="record_verdict", arguments=arguments)


def _ctx(**overrides: Any) -> FailureContext:
    fields: dict[str, Any] = {
        "nodeid": "tests/t.py::test_x",
        "phase": "call",
        "outcome": "failed",
        "exc_type": "AssertionError",
        "exc_message": "assert 1 == 2",
        "traceback": "assert 1 == 2",
    }
    fields.update(overrides)
    return FailureContext(**fields)


# --- happy path -----------------------------------------------------------


def test_returns_verdict_from_function_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="regression",
                confidence="high",
                hypothesis="Изменилась логика проверки статуса ответа.",
                suggested_fix="Сверить ожидаемый код ответа с новым контрактом.",
            )
        ),
    )
    verdict = GigaChatClient().analyze(_ctx())
    assert verdict.category == "regression"
    assert verdict.confidence == "high"
    assert verdict.hypothesis == "Изменилась логика проверки статуса ответа."
    assert verdict.suggested_fix == "Сверить ожидаемый код ответа с новым контрактом."
    assert calls["payload"]["function_call"] == {"name": "record_verdict"}


def test_verdict_text_is_russian_and_categories_stay_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The RU segment is the point of this provider: the prompt and the free-text
    # fields are Russian, while category/confidence remain the public contract.
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="env",
                confidence="medium",
                hypothesis="База данных недоступна во время прогона.",
                suggested_fix="Проверить доступность сервиса в CI.",
            )
        ),
    )
    verdict = GigaChatClient().analyze(_ctx())
    assert verdict.category in CATEGORIES
    assert any("а" <= char <= "я" for char in verdict.hypothesis.lower())


def test_prompt_is_russian_and_carries_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient().analyze(_ctx(traceback="E   assert 1 == 2"))
    messages = calls["payload"]["messages"]
    assert messages[0]["role"] == "system"
    assert "record_verdict" in messages[0]["content"]
    assert "Категории" in messages[0]["content"]
    user = messages[1]["content"]
    assert "тест: tests/t.py::test_x" in user
    assert "трейсбек:\nE   assert 1 == 2" in user


def test_prompt_omits_empty_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every byte of an empty "хвост stdout:" section is billed on every call.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient().analyze(_ctx(stdout_tail="", stderr_tail=""))
    user = calls["payload"]["messages"][1]["content"]
    assert "stdout" not in user
    assert "stderr" not in user


def test_prompt_scrubs_secrets_from_a_parametrized_nodeid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    secret = "AbCdEf0123456789abcdefXY"
    GigaChatClient().analyze(_ctx(nodeid=f"tests/t.py::test_login[{secret}]"))
    user = calls["payload"]["messages"][1]["content"]
    assert secret not in user
    assert "test_login" in user  # the signal survives; only the value is gone


# --- fallbacks and malformed responses ------------------------------------


def test_falls_back_to_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not every GigaChat deployment honours a forced function call.
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            content=json.dumps(
                {
                    "category": "flaky",
                    "confidence": "low",
                    "hypothesis": "Гонка при параллельном доступе.",
                    "suggested_fix": None,
                },
                ensure_ascii=False,
            )
        ),
    )
    verdict = GigaChatClient().analyze(_ctx())
    assert verdict.category == "flaky"
    assert verdict.suggested_fix is None


def test_prose_answer_becomes_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(
        monkeypatch, _completion(content="Не могу определить причину.")
    )
    assert GigaChatClient().analyze(_ctx()).category == "unknown"


def test_empty_choices_becomes_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(monkeypatch, types.SimpleNamespace(choices=[]))
    assert GigaChatClient().analyze(_ctx()).category == "unknown"


def test_invalid_values_become_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="взрыв", confidence="очень", hypothesis="h"
            )
        ),
    )
    verdict = GigaChatClient().analyze(_ctx())
    assert verdict.category == "unknown"
    assert verdict.confidence == "low"


def test_empty_suggested_fix_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # The GigaChat function schema has no null type, so "no fix" is "".
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="test_bug", confidence="high", hypothesis="h", suggested_fix=""
            )
        ),
    )
    assert GigaChatClient().analyze(_ctx()).suggested_fix is None


def test_oversized_hypothesis_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    # A runaway model must not push a novel into the report and into alerts.
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="env", confidence="low", hypothesis="я" * 5000
            )
        ),
    )
    hypothesis = GigaChatClient().analyze(_ctx()).hypothesis
    assert len(hypothesis.encode("utf-8")) < 1000
    assert "truncated" in hypothesis


# --- error paths ----------------------------------------------------------


def test_api_error_propagates_from_analyze(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(monkeypatch, RuntimeError("401 Unauthorized"))
    with pytest.raises(RuntimeError, match="401"):
        GigaChatClient().analyze(_ctx())


def test_auth_error_is_surfaced_without_leaking_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # gigachat's ResponseError stringifies url, body and headers. Whatever ends
    # up in the verdict must not carry the credential.
    token = "eyJjdHkiOiJqd3QiLCJhbGciOiJSU0EtT0FFUCJ9..AbCdEf0123456789.xyz"
    error = RuntimeError(
        "401 https://gigachat.example/api/v1/chat/completions: "
        f"Headers({{'authorization': 'Bearer {token}'}})"
    )
    _install_fake_gigachat(monkeypatch, error)
    verdict = TimedOutClient(GigaChatClient(), timeout=5.0).analyze(_ctx())
    assert verdict.category == "unknown"
    assert token not in verdict.hypothesis
    assert degraded_reason(verdict) is not None


def test_missing_dependency_raises_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gigachat", cast("types.ModuleType", None))
    with pytest.raises(pytest.UsageError, match=r"pytest-triage\[gigachat\]"):
        GigaChatClient()


def test_missing_extra_disables_triage_without_failing_the_run(
    monkeypatch: pytest.MonkeyPatch, pytester: pytest.Pytester
) -> None:
    # Selecting a provider whose extra is not installed must be a clear
    # configuration-time warning, never a mid-run ImportError and never a
    # different exit code.
    monkeypatch.setitem(sys.modules, "gigachat", cast("types.ModuleType", None))
    pytester.makepyfile(
        test_missing_extra="""
        def test_fail():
            assert 1 == 2
        """
    )
    spy, result = run_triage(pytester, "--ai-triage=on", "--ai-provider=gigachat")
    result.assert_outcomes(failed=1)
    assert spy.verdicts == [None]  # triage disabled, the run is untouched
    result.stdout.fnmatch_lines(["*pytest-triage: triage disabled:*gigachat*"])


# --- construction ---------------------------------------------------------


def test_sdk_configured_to_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient()
    assert calls["init_kwargs"]["max_retries"] == 0


def test_credentials_are_left_to_the_sdk_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The plugin never touches the secret: GIGACHAT_CREDENTIALS is the SDK's job.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient()
    assert "credentials" not in calls["init_kwargs"]
    assert "scope" not in calls["init_kwargs"]


def test_explicit_transport_options_are_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient(
        credentials="c",
        scope="GIGACHAT_API_CORP",
        verify_ssl_certs=True,
        ca_bundle_file="/etc/ssl/certs/ca-bundle.crt",
        timeout=12.0,
    )
    assert calls["init_kwargs"]["scope"] == "GIGACHAT_API_CORP"
    assert calls["init_kwargs"]["verify_ssl_certs"] is True
    assert calls["init_kwargs"]["timeout"] == 12.0


def test_tls_verification_is_never_disabled_implicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient()
    assert "verify_ssl_certs" not in calls["init_kwargs"]


def test_model_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(monkeypatch, _completion())
    monkeypatch.delenv("GIGACHAT_MODEL", raising=False)
    assert GigaChatClient()._model == "GigaChat"
    assert GigaChatClient().model == "GigaChat"  # public, for the report
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat-2")  # provider-specific env
    assert GigaChatClient()._model == "GigaChat-2"
    assert GigaChatClient(model="GigaChat-Pro")._model == "GigaChat-Pro"  # arg wins


def test_token_ceiling_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient().analyze(_ctx())
    assert 0 < calls["payload"]["max_tokens"] <= 1024


def test_close_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_gigachat(monkeypatch, _completion())
    client = GigaChatClient()
    client.close()
    assert calls["closed"] is True


def test_conforms(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_gigachat(
        monkeypatch,
        _completion(
            function_call=_function_call(
                category="env", confidence="medium", hypothesis="Сервис недоступен."
            )
        ),
    )
    assert_conforms(GigaChatClient())


@pytest.mark.live
def test_live_analyze() -> None:
    import os

    pytest.importorskip("gigachat")
    if not os.environ.get("GIGACHAT_CREDENTIALS"):
        pytest.skip("GIGACHAT_CREDENTIALS not set")
    client = GigaChatClient()
    try:
        verdict = client.analyze(_ctx())
    finally:
        client.close()
    print(f"\ncategory={verdict.category} confidence={verdict.confidence}")
    print(f"hypothesis={verdict.hypothesis}")
    print(f"suggested_fix={verdict.suggested_fix}")
    assert verdict.category in CATEGORIES
