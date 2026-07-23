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

"""Provider resolution: lazy entry points and import strings."""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from pytest_triage.providers.base import TriageClient

# Bumped on an incompatible change to the provider contract; an external
# provider can assert compatibility against it.
PROVIDER_API_VERSION = 1

_ENTRY_POINT_GROUP = "pytest_triage.providers"


def resolve_provider(spec: str) -> type[TriageClient]:
    """Resolve a provider from an entry-point name or a ``module:attr`` string.

    Entry points are loaded lazily — only the selected provider module is
    imported. Failures raise a clear configuration-time error, never a mid-run
    ImportError.
    """
    if ":" in spec:
        return _load_import_string(spec)
    return _load_entry_point(spec)


def _load_entry_point(name: str) -> type[TriageClient]:
    matches = [ep for ep in entry_points(group=_ENTRY_POINT_GROUP) if ep.name == name]
    if not matches:
        available = sorted(ep.name for ep in entry_points(group=_ENTRY_POINT_GROUP))
        raise pytest.UsageError(
            f"pytest-triage: unknown ai provider {name!r}; "
            f"registered: {available or 'none'}"
        )
    try:
        return cast("type[TriageClient]", matches[0].load())
    except Exception as exc:
        raise pytest.UsageError(
            f"pytest-triage: failed to load provider {name!r}: {exc}"
        ) from exc


def _load_import_string(spec: str) -> type[TriageClient]:
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
        return cast("type[TriageClient]", getattr(module, attr))
    except Exception as exc:
        raise pytest.UsageError(
            f"pytest-triage: failed to import provider {spec!r}: {exc}"
        ) from exc
