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

"""GigaChatClient: LLM triage via GigaChat (optional extra), for the RU segment.

Requires ``pytest-triage[gigachat]``. The ``gigachat`` package is imported
lazily so that resolving or importing this module never fails when the extra is
absent — the clear error is raised only when a client is actually constructed.

The prompt and the verdict text are Russian on purpose: GigaChat is a Russian
model and reasons noticeably better in its own language. The `category` and
`confidence` values stay English — they are the public `Verdict` contract.

Credentials are never handled here. The SDK reads ``GIGACHAT_CREDENTIALS`` (and
the rest of the ``GIGACHAT_*`` environment) itself; anything passed explicitly
is dependency injection for tests and for callers that build their own config.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from pytest_triage.providers.base import (
    BaseTriageClient,
    redact_nodeid,
    render_sections,
)

if TYPE_CHECKING:
    from pytest_triage.context import FailureContext

# "GigaChat" is the Lite model: the cheapest one that still classifies a
# traceback reliably. Override for Pro/Max when a suite justifies the cost.
_DEFAULT_MODEL = "GigaChat"
_MODEL_ENV = "GIGACHAT_MODEL"
# A verdict is one sentence plus a fix. Cyrillic costs roughly twice the tokens
# per character of Latin, so the cap is generous but still a hard ceiling.
_MAX_TOKENS = 512
# Triage is a classification, not a creative task.
_TEMPERATURE = 0.1
# Fail fast: the plugin's budget/timeout/breaker layer owns resilience, so SDK
# retries only fight the wall-clock cap and leave abandoned threads billing.
_MAX_RETRIES = 0
_FUNCTION_NAME = "record_verdict"

_SYSTEM = """\
Ты — ассистент по разбору упавших тестов pytest. Тебе дают контекст одного
упавшего теста: исключение, трейсбек и захваченные stdout, stderr и логи.
Определи одну наиболее вероятную причину падения и вызови функцию
`record_verdict` ровно один раз. Не отвечай обычным текстом.

Категории (выбери ровно одну, значение пиши латиницей, как в списке):
  - regression: изменился код под тестом и теперь работает неверно
  - flaky:      недетерминизм — тайминги, порядок тестов, внешнее состояние
  - env:        окружение или инфраструктура — сеть, база, недоступный сервис,
                неверная конфигурация
  - test_bug:   ошибка в самом тесте — неверный assert или устаревшая фикстура
  - unknown:    данных недостаточно, чтобы решить

Захваченные логи и вывод часто прямо называют причину — например, HTTP 5xx или
ошибка соединения указывают на env. Взвешивай поведение кода и ожидание теста
вместе; если они противоречат и по контексту нельзя понять, что именно неверно,
выбирай unknown, а не догадку.

Уверенность confidence: low, medium или high (тоже латиницей).

Поля hypothesis и suggested_fix пиши по-русски. hypothesis — одно предложение
без воды. suggested_fix — конкретное действие, если оно очевидно из контекста,
иначе пустая строка. Опирайся только на переданный контекст и не выдумывай
файлы, функции и настройки, которых в нём нет.

Если вызов функций недоступен, верни ровно один JSON-объект с ключами
category, confidence, hypothesis, suggested_fix и ничего кроме него.
"""

# Flat by design: weak models produce invalid JSON on nested schemas. There is
# no null type in the GigaChat function schema, hence "empty string" for a
# missing fix — the tolerant BaseTriageClient parser maps it back to None.
_VERDICT_FUNCTION: dict[str, Any] = {
    "name": _FUNCTION_NAME,
    "description": "Записать вердикт по упавшему тесту.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Категория причины падения.",
                "enum": ["regression", "flaky", "env", "test_bug", "unknown"],
            },
            "confidence": {
                "type": "string",
                "description": "Насколько уверен вывод.",
                "enum": ["low", "medium", "high"],
            },
            "hypothesis": {
                "type": "string",
                "description": "Одно предложение по-русски: почему тест упал.",
            },
            "suggested_fix": {
                "type": "string",
                "description": "Что сделать, по-русски. Пустая строка, если неясно.",
            },
        },
        "required": ["category", "confidence", "hypothesis"],
    },
}


class GigaChatClient(BaseTriageClient):
    """Triage via GigaChat function calling. Requires ``pytest-triage[gigachat]``.

    The model defaults to ``GigaChat`` (Lite) and can be overridden with the
    SDK's own ``GIGACHAT_MODEL`` environment variable or the ``model`` argument.
    Authorization, scope, endpoints and TLS come from the ``GIGACHAT_*``
    environment unless passed explicitly.

    The constructor arguments are dependency injection for tests and for callers
    that build their own config; they are not the documented path and cover only
    what a caller plausibly computes at runtime. Every other SDK setting
    (``profanity_check``, ``flags``, ``max_connections``, basic auth, the token
    refresh buffer) is read by the SDK from ``GIGACHAT_*`` and needs nothing
    here. ``max_retries`` is the one setting this provider pins.
    """

    def __init__(
        self,
        model: str | None = None,
        credentials: str | None = None,
        *,
        scope: str | None = None,
        base_url: str | None = None,
        auth_url: str | None = None,
        verify_ssl_certs: bool | None = None,
        ca_bundle_file: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        key_file_password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        try:
            import gigachat
        except ImportError as exc:
            raise _missing_dependency_error() from exc
        self._model = model or os.environ.get(_MODEL_ENV) or _DEFAULT_MODEL
        options: dict[str, Any] = {"max_retries": _MAX_RETRIES}
        # Only override what the caller actually set; everything else stays with
        # the SDK so GIGACHAT_* keeps working.
        for name, value in (
            ("credentials", credentials),
            ("scope", scope),
            ("base_url", base_url),
            ("auth_url", auth_url),
            ("verify_ssl_certs", verify_ssl_certs),
            ("ca_bundle_file", ca_bundle_file),
            ("cert_file", cert_file),
            ("key_file", key_file),
            ("key_file_password", key_file_password),
            ("timeout", timeout),
        ):
            if value is not None:
                options[name] = value
        # Typed Any: the SDK is untyped in CI (not installed); keep the chat()
        # call consistent whether or not gigachat is present locally.
        self._client: Any = gigachat.GigaChat(**options)

    @property
    def model(self) -> str:
        """The model queried for triage (surfaced as `ai_model` in the report)."""
        return self._model

    def _render_prompt(self, ctx: FailureContext) -> str:
        return render_sections(
            [
                ("тест: ", redact_nodeid(ctx.nodeid)),
                ("фаза: ", ctx.phase),
                ("исключение: ", f"{ctx.exc_type}: {ctx.exc_message}"),
                ("трейсбек:\n", ctx.traceback),
                ("хвост stdout:\n", ctx.stdout_tail),
                ("хвост stderr:\n", ctx.stderr_tail),
                ("хвост логов:\n", ctx.log_tail),
            ]
        )

    def _request(self, prompt: str) -> str:
        completion = self._client.chat(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "functions": [_VERDICT_FUNCTION],
                "function_call": {"name": _FUNCTION_NAME},
                "temperature": _TEMPERATURE,
                "max_tokens": _MAX_TOKENS,
            }
        )
        return _extract_verdict_json(completion)

    def close(self) -> None:
        # Self-protecting and idempotent (the conformance kit calls it twice): a
        # second close, or an SDK that raises on teardown, must never surface.
        with contextlib.suppress(Exception):
            self._client.close()


def _extract_verdict_json(completion: Any) -> str:
    """Prefer the function-call arguments; fall back to the message text.

    Not every GigaChat deployment honours a forced function call, so a model
    that answers in prose still yields a verdict via the tolerant parser.
    An unrecognisable response yields "" -> category="unknown", never an error.
    """
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    call = getattr(message, "function_call", None)
    arguments = getattr(call, "arguments", None)
    if arguments:
        # The SDK hands back a parsed object; tolerate a raw JSON string too.
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments, ensure_ascii=False)
    return str(getattr(message, "content", "") or "")


def _missing_dependency_error() -> Exception:
    return pytest.UsageError(
        "pytest-triage: the 'gigachat' provider requires the gigachat package; "
        "install it with: pip install 'pytest-triage[gigachat]'"
    )
