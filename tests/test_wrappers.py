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
from dataclasses import replace

import pytest

from pytest_triage.config import Config
from pytest_triage.context import FailureContext
from pytest_triage.verdict import Verdict
from pytest_triage.wrappers import (
    BudgetedClient,
    CachingClient,
    CircuitBreakerClient,
    TimedOutClient,
    build_triage_client,
    call_stats,
    degraded_reason,
    provider_model,
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


class _ErrorAfter:
    """Raises on every call except the ones listed in `succeed_on` (by index)."""

    def __init__(self, inner: _CountingClient, *succeed_on: int) -> None:
        self._inner = inner
        self._succeed_on = succeed_on
        self._seen = -1

    def analyze(self, ctx: FailureContext) -> Verdict:
        self._seen += 1
        verdict = self._inner.analyze(ctx)
        if self._seen in self._succeed_on:
            return verdict
        raise RuntimeError("provider exploded")

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


def test_provider_error_detail_carries_no_terminal_control_characters() -> None:
    # An SDK error stringifies the endpoint's own response body, and this text is
    # printed to the terminal. "\x1b[2K\r" erases the line and rewrites it, so a
    # hostile endpoint could delete this very warning from a CI log and forge a
    # green summary in its place.
    class _Hostile:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise RuntimeError(
                "503\x1b[2K\rpytest-triage: 0 failed, all green\x1b[0m\x1b]0;OWNED\x07"
            )

        def close(self) -> None:
            pass

    hypothesis = TimedOutClient(_Hostile(), timeout=5).analyze(_ctx()).hypothesis
    assert not any(ord(char) < 32 and char not in "\t\n" for char in hypothesis)
    assert "\x1b" not in hypothesis and "\r" not in hypothesis
    assert "503" in hypothesis  # the diagnostic content survives


def test_control_characters_do_not_defeat_provider_error_redaction() -> None:
    # Redaction ran before control characters were stripped, so a NUL wedged
    # into the keyword hid the assignment from every rule — and the strip then
    # printed the secret plainly. Order matters: clean, then redact.
    class _Sneaky:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise RuntimeError("401 token\x00=hunter2")

        def close(self) -> None:
            pass

    hypothesis = TimedOutClient(_Sneaky(), timeout=5).analyze(_ctx()).hypothesis
    assert "hunter2" not in hypothesis
    assert "401" in hypothesis  # the diagnostic part still survives


def test_provider_exception_with_a_broken_str_is_contained() -> None:
    # The guarantee is "a provider exception never escapes", full stop. Building
    # the error detail calls str(exc); when that raises, the handler itself blew
    # up, `result` stayed empty and `result[0]` raised IndexError out of analyze.
    class _Unprintable(Exception):
        def __str__(self) -> str:
            raise ValueError("broken __str__")

    class _Raises:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise _Unprintable

        def close(self) -> None:
            pass

    verdict = TimedOutClient(_Raises(), timeout=5).analyze(_ctx())
    assert verdict.category == "unknown"
    assert degraded_reason(verdict) is not None  # surfaced, not silently dropped
    assert "_Unprintable" in verdict.hypothesis  # the type still names the cause


def test_a_provider_error_handler_that_itself_dies_still_yields_a_verdict() -> None:
    # The last hole in the containment guarantee: the detail is built from
    # `type(exc).__name__`, so an exception whose *type* refuses to be named
    # kills the handler that exists to catch it, leaving nothing to return.
    class _NamelessMeta(type):
        # mypy is right that a raising, read-only `__name__` is not a
        # substitutable override — that is precisely what makes it a hostile
        # input, so the error is silenced rather than designed away.
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            raise ValueError("no name")

    class _Nameless(Exception, metaclass=_NamelessMeta):
        pass

    class _Raises:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise _Nameless

        def close(self) -> None:
            pass

    verdict = TimedOutClient(_Raises(), timeout=5).analyze(_ctx())
    assert verdict.category == "unknown"
    assert degraded_reason(verdict) is not None


def test_a_dying_error_handler_never_reaches_the_users_run(
    pytester: pytest.Pytester,
) -> None:
    # Invariant 1 at its sharpest. Returning a verdict is not enough: if the
    # worker thread lets an exception escape, pytest raises a
    # PytestUnhandledThreadExceptionWarning, and `-W error` turns a run the
    # plugin was only supposed to observe into a failing one.
    pytester.makeconftest(
        """
        from pytest_triage.providers.base import BaseTriageClient

        class _NamelessMeta(type):
            @property
            def __name__(cls):
                raise ValueError("no name")

        class _Nameless(Exception, metaclass=_NamelessMeta):
            pass

        class EvilClient(BaseTriageClient):
            model = "evil"

            def _request(self, prompt):
                raise _Nameless()
        """
    )
    pytester.makepyfile(
        test_invariant="""
        def test_fail():
            assert 1 == 2
        """
    )
    result = pytester.runpytest_subprocess(
        str(pytester.path),
        "--ai-triage=on",
        "--ai-provider=conftest:EvilClient",
        "-W",
        "error",
    )
    result.assert_outcomes(failed=1)  # the outcome the suite would have had
    assert result.ret == 1
    assert "PytestUnhandledThreadException" not in result.stdout.str()
    assert "INTERNALERROR" not in result.stdout.str()


def test_base_exception_in_a_provider_becomes_a_provider_error() -> None:
    # SystemExit/KeyboardInterrupt are not Exception. Left uncaught in the worker
    # thread they leave `result` empty, and the resulting IndexError escapes past
    # the circuit breaker — which then never trips, so every remaining failure
    # burns another call of the budget on a provider that cannot answer.
    class _Exits:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise SystemExit(3)

        def close(self) -> None:
            pass

    breaker = CircuitBreakerClient(
        BudgetedClient(TimedOutClient(_Exits(), timeout=5), budget=10)
    )
    first = breaker.analyze(_ctx())
    assert first.category == "unknown"
    assert first.hypothesis.startswith("triage provider error")
    breaker.analyze(_ctx())
    assert breaker.tripped  # two consecutive errors stop the spend


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


def test_cache_keeps_tracebackless_failures_apart() -> None:
    # Without a traceback there is nothing to dedup on; distinct failures must
    # not collapse onto one verdict just because both tracebacks are empty.
    inner = _CountingClient()
    client = CachingClient(inner)
    client.analyze(_ctx(traceback="", nodeid="t.py::a"))
    client.analyze(_ctx(traceback="", nodeid="t.py::b"))
    assert inner.calls == 2


def test_cache_distinguishes_exception_types() -> None:
    inner = _CountingClient()
    client = CachingClient(inner)
    base = _ctx(traceback="", nodeid="t.py::a")
    client.analyze(replace(base, exc_type="ValueError"))
    client.analyze(replace(base, exc_type="ConnectionError"))
    assert inner.calls == 2


# --- CircuitBreakerClient -------------------------------------------------


def test_breaker_trips_on_the_first_timeout() -> None:
    # A hung provider costs the full wall-clock cap on every remaining failure.
    client = CircuitBreakerClient(TimedOutClient(_SlowClient(), timeout=0.01))
    assert client.analyze(_ctx()).hypothesis == "triage timed out"
    assert client.tripped


def test_tripped_breaker_never_reaches_the_provider() -> None:
    inner = _CountingClient()
    client = CircuitBreakerClient(inner)
    client.tripped = True
    assert client.analyze(_ctx()).category == "unknown"
    assert inner.calls == 0


def test_breaker_trips_after_two_consecutive_provider_errors() -> None:
    inner = _CountingClient()
    client = CircuitBreakerClient(TimedOutClient(_ErrorAfter(inner), timeout=5.0))
    for _ in range(5):
        client.analyze(_ctx())
    assert client.tripped
    assert inner.calls == 2  # stopped paying after the second failure in a row


def test_breaker_resets_after_a_good_verdict() -> None:
    inner = _CountingClient()
    client = CircuitBreakerClient(TimedOutClient(_ErrorAfter(inner, 1), timeout=5.0))
    client.analyze(_ctx())  # error
    client.analyze(_ctx())  # success -> streak reset
    client.analyze(_ctx())  # error
    assert not client.tripped


def test_breaker_reason_is_surfaced_and_delegates_close() -> None:
    inner = _CountingClient()
    client = CircuitBreakerClient(inner)
    client.tripped = True
    assert degraded_reason(client.analyze(_ctx())) is not None
    client.close()
    assert inner.closed == 1


# --- call_stats -----------------------------------------------------------


def test_call_stats_reports_calls_and_cache_hits() -> None:
    inner = _CountingClient()
    client = CachingClient(CircuitBreakerClient(BudgetedClient(inner, budget=10)))
    client.analyze(_ctx(traceback="same"))
    client.analyze(_ctx(traceback="same"))
    client.analyze(_ctx(traceback="other"))
    assert call_stats(client) == (2, 1)


def test_call_stats_is_zero_for_a_bare_provider() -> None:
    assert call_stats(_CountingClient()) == (0, 0)


def test_provider_model_reads_through_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WithModel:
        model = "test-model-1"

        def analyze(self, ctx: FailureContext) -> Verdict:
            return _OK

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "pytest_triage.wrappers.resolve_provider", lambda spec: _WithModel
    )
    client = build_triage_client(Config(triage=True, provider="x"))
    assert provider_model(client) == "test-model-1"


def test_provider_model_none_for_bare_or_modelless() -> None:
    assert provider_model(None) is None
    assert provider_model(_CountingClient()) is None  # no `model` attribute


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


def test_breaker_caps_a_dead_provider_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Load contract through the real factory: a provider that always fails burns
    # only enough budget to trip the breaker, not the whole cap.
    class _Dead:
        def analyze(self, ctx: FailureContext) -> Verdict:
            raise RuntimeError("upstream 500")

        def close(self) -> None:
            pass

    monkeypatch.setattr("pytest_triage.wrappers.resolve_provider", lambda spec: _Dead)
    client = build_triage_client(Config(triage=True, provider="dead", budget=10))
    assert client is not None
    for i in range(20):
        client.analyze(_ctx(traceback=f"tb{i}", nodeid=f"t::{i}"))
    calls, _ = call_stats(client)
    assert calls == 2  # tripped after two consecutive errors, not the full budget


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


def test_broken_provider_is_called_at_most_twice(pytester: pytest.Pytester) -> None:
    # Money: a provider that is down stays down. Ten failures must not become
    # ten billed calls, whatever the budget says.
    pytester.syspathinsert()
    counter = pytester.path / "calls.txt"
    pytester.makepyfile(
        _prov_breaker=f"""
        import pathlib

        COUNTER = pathlib.Path({str(counter)!r})

        class BrokenClient:
            def analyze(self, ctx):
                with COUNTER.open("a") as handle:
                    handle.write("x")
                raise RuntimeError("upstream is down")

            def close(self):
                pass
        """
    )
    pytester.makepyfile(
        test_many="\n".join(
            f"def test_{index}():\n    assert {index} == -1\n" for index in range(10)
        )
    )
    spy, result = run_triage(
        pytester,
        "--ai-triage=on",
        "--ai-provider=_prov_breaker:BrokenClient",
        "--ai-budget=10",
    )
    result.assert_outcomes(failed=10)
    assert len(spy.verdicts) == 10
    assert counter.read_text() == "xx"


def test_terminal_summary_reports_cost(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_cost="""
        def test_a():
            assert 1 == 2

        def test_b():
            raise ConnectionError("nope")
        """
    )
    result = pytester.runpytest_inprocess(
        str(pytester.path), "--ai-triage=on", "--ai-provider=fake"
    )
    result.assert_outcomes(failed=2)
    result.stdout.fnmatch_lines(["*pytest-triage: 2 provider call(s), 0 from cache*"])


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
