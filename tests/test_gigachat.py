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
import os
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


def test_string_function_arguments_are_handled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Robustness: tolerate a deployment that returns arguments as a raw JSON
    # string instead of a parsed object.
    call = types.SimpleNamespace(
        name="record_verdict",
        arguments='{"category": "env", "confidence": "low", '
        '"hypothesis": "сервис недоступен", "suggested_fix": null}',
    )
    _install_fake_gigachat(monkeypatch, _completion(function_call=call))
    assert GigaChatClient().analyze(_ctx()).category == "env"


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
    GigaChatClient().analyze(_ctx(stdout_tail="", stderr_tail="", log_tail=""))
    user = calls["payload"]["messages"][1]["content"]
    assert "stdout" not in user
    assert "stderr" not in user
    assert "логов" not in user


def test_prompt_carries_the_log_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    # Logs captured via the `logging` module must reach the model, labelled.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient().analyze(_ctx(log_tail="ERROR srv: DB_UNREACHABLE"))
    user = calls["payload"]["messages"][1]["content"]
    assert "хвост логов:\nERROR srv: DB_UNREACHABLE" in user


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
        base_url="https://gigachat.dev.internal/api/v1",
        auth_url="https://ngw.dev.internal:9443/api/v2/oauth",
        verify_ssl_certs=True,
        ca_bundle_file="/etc/ssl/certs/ca-bundle.crt",
        timeout=12.0,
    )
    assert calls["init_kwargs"]["scope"] == "GIGACHAT_API_CORP"
    assert calls["init_kwargs"]["base_url"] == "https://gigachat.dev.internal/api/v1"
    assert (
        calls["init_kwargs"]["auth_url"] == "https://ngw.dev.internal:9443/api/v2/oauth"
    )
    assert calls["init_kwargs"]["verify_ssl_certs"] is True
    assert calls["init_kwargs"]["timeout"] == 12.0


def test_mutual_tls_options_are_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # A corporate contour (GIGACHAT_API_CORP/B2B) can require a client
    # certificate. Trusting the server was already expressible via
    # ca_bundle_file; presenting our own certificate is the other half.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient(
        cert_file="/etc/ssl/certs/client.crt",
        key_file="/etc/ssl/private/client.key",
        key_file_password="passphrase",
    )
    assert calls["init_kwargs"]["cert_file"] == "/etc/ssl/certs/client.crt"
    assert calls["init_kwargs"]["key_file"] == "/etc/ssl/private/client.key"
    assert calls["init_kwargs"]["key_file_password"] == "passphrase"


def test_mutual_tls_is_left_to_the_sdk_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unset means unset: passing cert_file=None would override GIGACHAT_CERT_FILE.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient()
    assert "cert_file" not in calls["init_kwargs"]
    assert "key_file" not in calls["init_kwargs"]
    assert "key_file_password" not in calls["init_kwargs"]


def test_endpoints_are_left_to_the_sdk_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A dev contour overrides the endpoints through the SDK's own
    # GIGACHAT_BASE_URL / GIGACHAT_AUTH_URL; the plugin must not pin either one,
    # or the environment would stop working.
    calls = _install_fake_gigachat(monkeypatch, _completion())
    GigaChatClient()
    assert "base_url" not in calls["init_kwargs"]
    assert "auth_url" not in calls["init_kwargs"]


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


def test_close_swallows_a_raising_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # An SDK that raises on teardown (already-closed session, dead socket) must
    # not turn a clean run into an error. close is fenced here, not just by the
    # caller.
    _install_fake_gigachat(monkeypatch, _completion())
    client = GigaChatClient()

    def _boom() -> None:
        raise RuntimeError("session already closed")

    client._client.close = _boom
    client.close()  # no raise
    client.close()  # idempotent


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


# --- the documented environment, against the real SDK ---------------------

# The README documents these as "read by the SDK; the plugin pins none of them".
# That is a promise about someone else's package, so it is checked against the
# real one rather than the fake: a GigaChat release that renames a setting or
# changes how it parses would otherwise silently turn the documentation into a
# lie. No network — the SDK authenticates lazily, on the first request.
# (env var, settings field, env value, parsed value)
_DOCUMENTED_ENV: tuple[tuple[str, str, str, object], ...] = (
    ("GIGACHAT_BASE_URL", "base_url", "https://gc.dev/api/v1", "https://gc.dev/api/v1"),
    (
        "GIGACHAT_AUTH_URL",
        "auth_url",
        "https://ngw.dev:9443/oauth",
        "https://ngw.dev:9443/oauth",
    ),
    ("GIGACHAT_SCOPE", "scope", "GIGACHAT_API_CORP", "GIGACHAT_API_CORP"),
    ("GIGACHAT_VERIFY_SSL_CERTS", "verify_ssl_certs", "false", False),
    ("GIGACHAT_CA_BUNDLE_FILE", "ca_bundle_file", "/etc/ca.pem", "/etc/ca.pem"),
    ("GIGACHAT_CERT_FILE", "cert_file", "/etc/client.crt", "/etc/client.crt"),
    ("GIGACHAT_KEY_FILE", "key_file", "/etc/client.key", "/etc/client.key"),
    ("GIGACHAT_TIMEOUT", "timeout", "7.5", 7.5),
    # Documented but deliberately not constructor arguments.
    ("GIGACHAT_PROFANITY_CHECK", "profanity_check", "false", False),
    ("GIGACHAT_USER", "user", "svc-ci", "svc-ci"),
    ("GIGACHAT_MAX_CONNECTIONS", "max_connections", "4", 4),
    ("GIGACHAT_TOKEN_EXPIRY_BUFFER_MS", "token_expiry_buffer_ms", "90000", 90000),
    ("GIGACHAT_FLAGS", "flags", '["nostream"]', ["nostream"]),
)


def _clear_gigachat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the developer's own GIGACHAT_* so the assertions mean something."""
    for name in [key for key in os.environ if key.startswith("GIGACHAT_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(("env", "field", "value", "expected"), _DOCUMENTED_ENV)
def test_documented_env_var_reaches_the_sdk(
    monkeypatch: pytest.MonkeyPatch, env: str, field: str, value: str, expected: object
) -> None:
    pytest.importorskip("gigachat")
    _clear_gigachat_env(monkeypatch)
    monkeypatch.setenv(env, value)
    client = GigaChatClient()
    try:
        # `_settings` is SDK-private; this test is the seam that would catch it
        # being renamed, which is exactly what it is here to do.
        assert getattr(client._client._settings, field) == expected
    finally:
        client.close()


def test_documented_env_defaults_are_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With an empty environment every documented setting must still hold the
    # SDK's own default — the plugin adds no opinion of its own.
    pytest.importorskip("gigachat")
    from gigachat.settings import Settings

    _clear_gigachat_env(monkeypatch)
    client = GigaChatClient()
    try:
        settings, default = client._client._settings, Settings()
        for _, field, _, _ in _DOCUMENTED_ENV:
            assert getattr(settings, field) == getattr(default, field), field
    finally:
        client.close()


def test_max_retries_env_is_deliberately_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The one GIGACHAT_* the plugin overrides, and the README says so: SDK
    # retries only fight the wall-clock cap and leave abandoned threads billing.
    # GIGACHAT_RETRY_BACKOFF_FACTOR / _ON_STATUS_CODES are inert as a
    # consequence — the SDK gates both on max_retries > 0.
    pytest.importorskip("gigachat")
    _clear_gigachat_env(monkeypatch)
    monkeypatch.setenv("GIGACHAT_MAX_RETRIES", "5")
    client = GigaChatClient()
    try:
        assert client._client._settings.max_retries == 0
    finally:
        client.close()


@pytest.mark.live
def test_live_analyze() -> None:
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
