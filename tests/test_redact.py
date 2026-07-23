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

"""redact(): strict scrubbing of common secret shapes."""

from __future__ import annotations

import pytest

from pytest_triage.redact import redact


def test_bearer_token_redacted() -> None:
    result = redact("Authorization: Bearer abc123DEF.token-value")
    assert result == "Authorization: Bearer [REDACTED]"


def test_password_assignment_redacted() -> None:
    assert "hunter2" not in redact("db password=hunter2 connected")
    assert "[REDACTED]" in redact("db password=hunter2")


def test_base64_blob_redacted() -> None:
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="  # 20+ base64 chars
    assert "[REDACTED]" in redact(f"key={blob}")
    assert blob not in redact(blob)


def test_env_value_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SERVICE_TOKEN", "s3cr3t-value-1234")
    assert "s3cr3t-value-1234" not in redact("leaked s3cr3t-value-1234 here")


def test_short_env_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTVAL", "abc")  # below the length threshold
    assert redact("value abc stays") == "value abc stays"


def test_pathlike_env_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_DIR", "/opt/data/models")  # path-like, non-safe key
    assert "/opt/data/models" in redact("loading /opt/data/models now")


def test_empty_text_is_noop() -> None:
    assert redact("") == ""


def test_jwt_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4h-abc"
    result = redact(f"decoded from {jwt} ok")
    assert jwt not in result
    assert "[REDACTED]" in result


def test_url_credentials_redacted() -> None:
    result = redact("dsn=postgres://admin:s3cr3tPass@db.internal:5432/app")
    assert "s3cr3tPass" not in result
    assert "postgres://admin:[REDACTED]@db.internal" in result


def test_pem_private_key_redacted() -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdefGHIJ\n"
        "-----END RSA PRIVATE KEY-----"
    )
    result = redact(f"key material:\n{pem}\ndone")
    assert "MIIEpAIBAAKCAQEA1234567890abcdefGHIJ" not in result
    assert "[REDACTED]" in result


def test_json_style_api_key_redacted() -> None:
    result = redact('config {"api_key": "abcDEF123456", "url": "http://x"}')
    assert "abcDEF123456" not in result


def test_basic_auth_redacted() -> None:
    assert "dXNlcjpwYXNz" not in redact("Authorization: Basic dXNlcjpwYXNz")


def test_aws_access_key_redacted() -> None:
    assert "AKIAIOSFODNN7EXAMPLE" not in redact("aws AKIAIOSFODNN7EXAMPLE used")


def test_short_secret_named_env_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "x1y2z")  # short, but the name signals a secret
    assert "x1y2z" not in redact("leaked x1y2z here")
