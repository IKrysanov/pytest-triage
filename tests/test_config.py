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

"""Config resolution: CLI overrides ini; defaults apply."""

from __future__ import annotations

import pytest

from tests.support import run_triage

_ONE_FAILURE = "def test_f():\n    assert False\n"


def test_defaults(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    spy, _ = run_triage(pytester)
    cfg = spy.triage_config
    assert cfg is not None
    assert cfg.triage is False
    assert cfg.report is None
    assert cfg.provider is None
    assert cfg.budget == 10
    assert cfg.timeout == 30.0
    assert cfg.redact == "strict"


def test_cli_overrides_ini(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    pytester.makeini(
        """
        [pytest]
        ai_budget = 5
        ai_redact = off
        ai_triage = on
        """
    )
    spy, _ = run_triage(pytester, "--ai-budget=7")
    cfg = spy.triage_config
    assert cfg is not None
    assert cfg.budget == 7  # CLI wins over ini
    assert cfg.redact == "off"  # ini used (no CLI override)
    assert cfg.triage is True  # ini used


def test_report_and_provider_from_cli(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    spy, _ = run_triage(pytester, "--ai-report=out.json", "--ai-provider=fake:Client")
    cfg = spy.triage_config
    assert cfg is not None
    assert cfg.report is not None
    assert cfg.report.name == "out.json"
    assert cfg.provider == "fake:Client"
