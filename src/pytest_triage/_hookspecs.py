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

"""Private hook specifications for pytest-triage (internal seam)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_triage.config import Config
    from pytest_triage.context import FailureContext
    from pytest_triage.verdict import Verdict


def pytest_triage_report(
    failures: list[FailureContext],
    verdicts: list[Verdict | None],
    triage_config: Config,
) -> None:
    """Fire once on the controller after collection.

    `verdicts` is aligned with `failures` (one entry each); an entry is None when
    triage is disabled. Notification hook: every implementer runs. The JSON
    report writer and downstream consumers implement this. By default nothing
    does, so a run stays byte-identical to one without the plugin (invariant 2).
    """
