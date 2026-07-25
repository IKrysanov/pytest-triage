"""Minimal soft-assertion collector: gather checks, raise them joined at the end.

Mimics a 'check' framework where a test records several conditions and one
AssertionError carries all the failed messages, instead of stopping on the first.
"""

from __future__ import annotations


class SoftAssert:
    def __init__(self) -> None:
        self._errors: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self._errors.append(message)

    def assert_all(self) -> None:
        if self._errors:
            joined = "\n".join(f"- {e}" for e in self._errors)
            raise AssertionError(
                f"{len(self._errors)} soft-assert failure(s):\n{joined}"
            )
