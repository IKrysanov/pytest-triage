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

"""Provider registry: import strings, entry points, and clear errors."""

from __future__ import annotations

import pytest

from pytest_triage import registry
from pytest_triage.providers import PROVIDER_API_VERSION
from pytest_triage.providers.fake import FakeTriageClient, OAuthFakeClient


def test_provider_api_version_exported() -> None:
    assert PROVIDER_API_VERSION == registry.PROVIDER_API_VERSION == 1


def test_resolve_import_string() -> None:
    cls = registry.resolve_provider("pytest_triage.providers.fake:FakeTriageClient")
    assert cls is FakeTriageClient


def test_resolve_import_string_failure() -> None:
    with pytest.raises(pytest.UsageError):
        registry.resolve_provider("nonexistent.module.here:Whatever")


def test_resolve_entry_point() -> None:
    assert registry.resolve_provider("fake") is FakeTriageClient
    assert registry.resolve_provider("oauth-fake") is OAuthFakeClient


def test_resolve_unknown_entry_point() -> None:
    with pytest.raises(pytest.UsageError):
        registry.resolve_provider("no-such-provider")


def test_resolve_entry_point_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadEntryPoint:
        name = "bad"

        def load(self) -> object:
            raise ImportError("boom")

    monkeypatch.setattr(registry, "entry_points", lambda group: [_BadEntryPoint()])
    with pytest.raises(pytest.UsageError):
        registry.resolve_provider("bad")
