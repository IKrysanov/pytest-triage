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

"""In-process unit tests for the pure collection logic and the collector hook."""

from __future__ import annotations

from typing import cast

import pytest

from pytest_triage.config import Config, _as_path
from pytest_triage.context import (
    FailureContext,
    _truncate_head,
    _truncate_tail,
    build_context,
    safe_message,
)
from pytest_triage.plugin import _TriagePlugin


def test_truncate_tail_keeps_end_with_marker() -> None:
    out = _truncate_tail("A" * 100, 40)
    assert out.startswith("...[truncated 60 bytes]...")
    assert out.endswith("A" * 40)


def test_truncate_tail_short_text_unchanged() -> None:
    assert _truncate_tail("short", 40) == "short"


def test_truncate_head_keeps_start_with_marker() -> None:
    out = _truncate_head("B" * 100, 30)
    assert out.startswith("B" * 30)
    assert out.endswith("...[truncated 70 bytes]...")


def test_truncate_is_byte_based_not_char() -> None:
    # "é" is two UTF-8 bytes: 100 chars -> 200 bytes.
    out = _truncate_tail("é" * 100, 50)
    assert "[truncated 150 bytes]" in out


def test_safe_message_normal() -> None:
    assert safe_message(ValueError("boom")) == "boom"


def test_safe_message_broken_str() -> None:
    class Bad(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no str")

    assert safe_message(Bad()) == "<unprintable Bad>"


def _make_report(longrepr: str) -> pytest.TestReport:
    return pytest.TestReport(
        nodeid="tests/x.py::test_y",
        location=("tests/x.py", 1, "test_y"),
        keywords={},
        outcome="failed",
        longrepr=longrepr,
        when="call",
        sections=[
            ("Captured stdout call", "OUT-LINE\n"),
            ("Captured stderr call", "ERR-LINE\n"),
        ],
        duration=0.25,
    )


def test_build_context_maps_fields_without_redaction() -> None:
    ctx = build_context(
        _make_report("E   AssertionError: nope"),
        exc_type="AssertionError",
        exc_message="nope",
        redact_mode="off",
    )
    assert isinstance(ctx, FailureContext)
    assert ctx.nodeid == "tests/x.py::test_y"
    assert ctx.phase == "call"
    assert ctx.outcome == "failed"
    assert ctx.exc_type == "AssertionError"
    assert ctx.exc_message == "nope"
    assert "AssertionError" in ctx.traceback
    assert ctx.stdout_tail == "OUT-LINE\n"
    assert ctx.stderr_tail == "ERR-LINE\n"
    assert ctx.duration == 0.25


def test_build_context_strict_redacts_secrets() -> None:
    ctx = build_context(
        _make_report("leaked: Bearer abc123DEF.token-value here"),
        exc_type="ValueError",
        exc_message="Bearer abc123DEF.token",
        redact_mode="strict",
    )
    assert "abc123DEF.token-value" not in ctx.traceback
    assert "[REDACTED]" in ctx.traceback
    assert "[REDACTED]" in (ctx.exc_message or "")


def test_as_path_helper() -> None:
    assert _as_path(None) is None
    assert _as_path("") is None
    resolved = _as_path("/tmp/report.json")
    assert resolved is not None
    assert str(resolved) == "/tmp/report.json"


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.triage is False
    assert cfg.report is None
    assert cfg.budget == 10
    assert cfg.timeout == 30.0
    assert cfg.redact == "strict"


def test_collector_records_failure_via_exception_interact() -> None:
    plugin = _TriagePlugin(Config(redact="off"))

    def boom() -> None:
        raise ValueError("kaboom")

    call = cast("pytest.CallInfo[object]", pytest.CallInfo.from_call(boom, when="call"))
    plugin.pytest_exception_interact(
        call=call, report=_make_report("E   ValueError: kaboom")
    )
    assert len(plugin._failures) == 1
    assert plugin._failures[0].exc_type == "ValueError"
    assert plugin._failures[0].exc_message == "kaboom"


def test_collector_ignores_passed_reports() -> None:
    plugin = _TriagePlugin(Config())
    report = _make_report("irrelevant")
    report.outcome = "passed"
    call = cast(
        "pytest.CallInfo[object]",
        pytest.CallInfo.from_call(lambda: None, when="call"),
    )
    plugin.pytest_exception_interact(call=call, report=report)
    assert plugin._failures == []


def test_build_context_without_message() -> None:
    ctx = build_context(
        _make_report("plain traceback"),
        exc_type=None,
        exc_message=None,
        redact_mode="strict",
    )
    assert ctx.exc_type is None
    assert ctx.exc_message is None


def test_sessionfinish_skips_on_xdist_worker() -> None:
    plugin = _TriagePlugin(Config())

    class _WorkerConfig:
        workerinput = "gw0"  # only presence matters (the hasattr guard)

    class _Session:
        config = _WorkerConfig()

    # workerinput present -> the controller guard returns before touching the
    # hook relay, so a config with no `.hook` must not raise.
    plugin.pytest_sessionfinish(cast("pytest.Session", _Session()))
