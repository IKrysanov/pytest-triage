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

"""Wrapper decorators (budget/cache/timeout), the factory, and invariant 1.

The invariant test is the load-bearing one: a provider that raises on every call
must leave the run byte-identical to a run without triage.
"""

from __future__ import annotations

import time

import pytest

from pytest_triage.config import Config
from pytest_triage.context import FailureContext
from pytest_triage.verdict import Verdict
from pytest_triage.wrappers import (
    BudgetedClient,
    CachingClient,
    TimedOutClient,
    build_triage_client,
    degraded_reason,
)
from tests.support import run_triage

_OK = Verdict(category="regression", hypothesis="h", confidence="high")


def _ctx(traceback: str = "tb", nodeid: str = "t.py::a") -> FailureContext:
    return FailureContext(
        nodeid=nodeid, phase="call", outcome="failed", traceback=traceback
    )


class _CountingClient:
    """Records calls; returns a fixed verdict. `close` failure is observable."""

    def __init__(self, verdict: Verdict = _OK) -> None:
        self.calls = 0
        self.closed = 0
        self._verdict = verdict

    def analyze(self, ctx: FailureContext) -> Verdict:
        self.calls += 1
        return self._verdict

    def close(self) -> None:
        self.closed += 1


class _RaisingClient:
    def analyze(self, ctx: FailureContext) -> Verdict:
        raise RuntimeError("provider exploded")

    def close(self) -> None:
        raise RuntimeError("close exploded")


class _SlowClient:
    def analyze(self, ctx: FailureContext) -> Verdict:
        time.sleep(5)  # far beyond the test timeout; the daemon thread is abandoned
        return _OK

    def close(self) -> None:
        pass


# --- TimedOutClient -------------------------------------------------------


def test_timed_out_passes_through_fast_result() -> None:
    inner = _CountingClient()
    assert TimedOutClient(inner, timeout=5).analyze(_ctx()) is _OK
    assert inner.calls == 1


def test_timed_out_returns_unknown_on_timeout() -> None:
    verdict = TimedOutClient(_SlowClient(), timeout=0.05).analyze(_ctx())
    assert verdict.category == "unknown"
    assert "timed out" in verdict.hypothesis


def test_timed_out_surfaces_provider_error_cause() -> None:
    verdict = TimedOutClient(_RaisingClient(), timeout=5).analyze(_ctx())
    assert verdict.category == "unknown"
    # The real cause reaches the verdict, not a silent generic unknown.
    assert verdict.hypothesis.startswith("triage provider error")
    assert "provider exploded" in verdict.hypothesis


def test_provider_error_detail_is_capped() -> None:
    class _Boom:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise RuntimeError("boom " * 120)  # long, but not a redactable token

        def close(self) -> None:
            pass

    verdict = TimedOutClient(_Boom(), timeout=5).analyze(_ctx())
    assert verdict.hypothesis.endswith("...")
    assert len(verdict.hypothesis) < 260


def test_degraded_reason_flags_errors_and_timeouts_not_budget() -> None:
    errored = TimedOutClient(_RaisingClient(), timeout=5).analyze(_ctx())
    assert degraded_reason(errored) is not None
    timed_out = TimedOutClient(_SlowClient(), timeout=0.05).analyze(_ctx())
    assert degraded_reason(timed_out) == "triage timed out"
    exhausted = BudgetedClient(_CountingClient(), budget=0).analyze(_ctx())
    assert degraded_reason(exhausted) is None  # a configured limit, not an error
    assert degraded_reason(_OK) is None  # a real verdict


def test_timed_out_delegates_close() -> None:
    inner = _CountingClient()
    TimedOutClient(inner, timeout=5).close()
    assert inner.closed == 1


# --- BudgetedClient -------------------------------------------------------


def test_budget_allows_up_to_n_calls_then_stops() -> None:
    inner = _CountingClient()
    client = BudgetedClient(inner, budget=2)
    assert client.analyze(_ctx()) is _OK
    assert client.analyze(_ctx()) is _OK
    exhausted = client.analyze(_ctx())
    assert exhausted.category == "unknown"
    assert "budget" in exhausted.hypothesis
    assert inner.calls == 2  # the third call never reached the provider


def test_budget_delegates_close() -> None:
    inner = _CountingClient()
    BudgetedClient(inner, budget=1).close()
    assert inner.closed == 1


# --- CachingClient --------------------------------------------------------


def test_cache_reuses_verdict_for_identical_traceback() -> None:
    inner = _CountingClient()
    client = CachingClient(inner)
    client.analyze(_ctx(traceback="same"))
    client.analyze(_ctx(traceback="same"))
    assert inner.calls == 1  # second failure served from cache


def test_cache_distinguishes_different_tracebacks() -> None:
    inner = _CountingClient()
    client = CachingClient(inner)
    client.analyze(_ctx(traceback="one"))
    client.analyze(_ctx(traceback="two"))
    assert inner.calls == 2


def test_cache_normalizes_addresses_and_whitespace() -> None:
    inner = _CountingClient()
    client = CachingClient(inner)
    client.analyze(_ctx(traceback="<obj at 0xdeadbeef>\n  line"))
    client.analyze(_ctx(traceback="<obj at 0x00ff1234>   line"))
    assert inner.calls == 1  # volatile address + spacing normalized away


def test_cache_delegates_close() -> None:
    inner = _CountingClient()
    CachingClient(inner).close()
    assert inner.closed == 1


# --- build_triage_client --------------------------------------------------


def test_factory_returns_none_when_triage_off() -> None:
    assert build_triage_client(Config(triage=False, provider="fake")) is None


def test_factory_returns_none_without_provider() -> None:
    assert build_triage_client(Config(triage=True, provider=None)) is None


def test_factory_builds_working_client() -> None:
    client = build_triage_client(Config(triage=True, provider="fake"))
    assert client is not None
    verdict = client.analyze(
        FailureContext(
            nodeid="t.py::a",
            phase="call",
            outcome="failed",
            exc_type="AssertionError",
        )
    )
    client.close()
    assert verdict.category == "test_bug"  # FakeTriageClient rule


def test_factory_budget_is_enforced_end_to_end() -> None:
    client = build_triage_client(Config(triage=True, provider="fake", budget=1))
    assert client is not None
    first = client.analyze(_ctx(traceback="a", nodeid="t.py::a"))
    second = client.analyze(_ctx(traceback="b", nodeid="t.py::b"))
    assert first.category != "unknown"
    assert second.category == "unknown"  # budget of 1 spent on the first failure


# --- Invariant 1: triage never affects the run ----------------------------


def _write_sample(pytester: pytest.Pytester) -> str:
    pytester.makepyfile(
        test_sample="""
        def test_pass():
            assert True

        def test_fail():
            assert 1 == 2
        """
    )
    return str(pytester.path / "test_sample.py")


def test_raising_provider_leaves_exit_code_unchanged(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        _prov="""
        class RaisingClient:
            def analyze(self, ctx):
                raise RuntimeError("boom")

            def close(self):
                raise RuntimeError("close boom")
        """
    )
    sample = _write_sample(pytester)
    baseline = pytester.runpytest_subprocess(sample)
    triaged = pytester.runpytest_subprocess(
        sample, "--ai-triage=on", "--ai-provider=_prov:RaisingClient"
    )
    assert triaged.ret == baseline.ret  # invariant 1: byte-identical outcome
    baseline.assert_outcomes(passed=1, failed=1)
    triaged.assert_outcomes(passed=1, failed=1)


def test_raising_provider_yields_unknown_inprocess(
    pytester: pytest.Pytester,
) -> None:
    # In-process so the raising analyze + raising close paths count for coverage.
    pytester.syspathinsert()
    pytester.makepyfile(
        _prov_ip="""
        class RaisingClient:
            def analyze(self, ctx):
                raise RuntimeError("boom")

            def close(self):
                raise RuntimeError("close boom")
        """
    )
    pytester.makepyfile(
        test_one="""
        def test_fail():
            assert 1 == 2
        """
    )
    spy, result = run_triage(
        pytester, "--ai-triage=on", "--ai-provider=_prov_ip:RaisingClient"
    )
    result.assert_outcomes(failed=1)
    (verdict,) = spy.verdicts
    assert verdict is not None
    assert verdict.category == "unknown"
    assert "boom" in verdict.hypothesis  # real cause, not a silent unknown
    # ...and it is surfaced loudly in the terminal, not just buried in the report.
    result.stdout.fnmatch_lines(["*pytest-triage: triage provider error*boom*"])


def test_terminal_summary_reports_verdict_counts(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_two="""
        def test_fail():
            assert 1 == 2
        """
    )
    result = pytester.runpytest_inprocess(
        str(pytester.path), "--ai-triage=on", "--ai-provider=fake"
    )
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*pytest-triage: 1 test_bug*"])


def test_unknown_provider_disables_triage_without_failing(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_three="""
        def test_fail():
            assert 1 == 2
        """
    )
    spy, result = run_triage(
        pytester, "--ai-triage=on", "--ai-provider=nonexistent-provider"
    )
    result.assert_outcomes(failed=1)  # bad config never changes the outcome
    assert spy.verdicts == [None]  # triage disabled -> no verdict
