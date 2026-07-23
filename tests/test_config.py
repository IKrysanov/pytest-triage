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


def test_triage_on_defaults_report_path(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    spy, _ = run_triage(pytester, "--ai-triage=on", "--ai-provider=fake")
    cfg = spy.triage_config
    assert cfg is not None
    assert cfg.report is not None
    assert cfg.report.name == ".triage.json"  # default applied by triage-on


def test_explicit_report_overrides_default(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    spy, _ = run_triage(
        pytester, "--ai-triage=on", "--ai-provider=fake", "--ai-report=custom.json"
    )
    cfg = spy.triage_config
    assert cfg is not None
    assert cfg.report is not None
    assert cfg.report.name == "custom.json"


def test_non_numeric_budget_ini_is_a_clear_error(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    pytester.makeini("[pytest]\nai_budget = abc\n")  # ini values bypass argparse
    result = pytester.runpytest_inprocess(str(pytester.path))
    result.stderr.fnmatch_lines(["*ai_budget must be an integer*"])


def test_negative_budget_is_rejected(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    result = pytester.runpytest_inprocess(str(pytester.path), "--ai-budget=-3")
    result.stderr.fnmatch_lines(["*ai_budget must be >= 0*"])


def test_non_numeric_timeout_ini_is_a_clear_error(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    pytester.makeini("[pytest]\nai_timeout = soon\n")
    result = pytester.runpytest_inprocess(str(pytester.path))
    result.stderr.fnmatch_lines(["*ai_timeout must be a number*"])


def test_non_positive_timeout_is_rejected(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    result = pytester.runpytest_inprocess(str(pytester.path), "--ai-timeout=0")
    result.stderr.fnmatch_lines(["*ai_timeout must be > 0*"])


def test_warns_when_triage_on_without_provider(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    _, result = run_triage(pytester, "--ai-triage=on")
    result.stdout.fnmatch_lines(["*no --ai-provider is set*"])


def test_warns_when_provider_set_without_triage(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_ONE_FAILURE)
    _, result = run_triage(pytester, "--ai-provider=fake")
    result.stdout.fnmatch_lines(["*triage is off*"])
