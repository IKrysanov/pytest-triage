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

"""Invariants 1-2: loaded but default-off, the plugin is transparent."""

from __future__ import annotations

import re

import pytest

_SUITE = """
def test_pass():
    assert True

def test_fail_assert():
    assert 1 + 1 == 3

def test_fail_raise():
    raise ValueError("boom")

def test_error_fixture(nonexistent_fixture):
    pass
"""


def _normalize(text: str) -> str:
    # The "plugins:" header line legitimately lists every installed plugin, and
    # durations vary run to run; neither is behaviour. Everything else must match.
    lines = []
    for line in text.splitlines():
        if line.startswith("plugins:"):
            continue
        lines.append(re.sub(r"\d+\.\d+s", "<t>s", line))
    return "\n".join(lines)


def test_default_run_matches_disabled(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_SUITE)
    with_plugin = pytester.runpytest_subprocess(str(pytester.path))
    without = pytester.runpytest_subprocess(
        str(pytester.path), "-p", "no:pytest_triage"
    )
    assert with_plugin.ret == without.ret
    assert with_plugin.ret != 0  # the suite genuinely fails
    assert _normalize(with_plugin.stdout.str()) == _normalize(without.stdout.str())


def test_triage_off_matches_disabled(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_SUITE)
    off = pytester.runpytest_subprocess(str(pytester.path), "--ai-triage=off")
    without = pytester.runpytest_subprocess(
        str(pytester.path), "-p", "no:pytest_triage"
    )
    assert off.ret == without.ret
    assert _normalize(off.stdout.str()) == _normalize(without.stdout.str())
