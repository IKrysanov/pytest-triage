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
