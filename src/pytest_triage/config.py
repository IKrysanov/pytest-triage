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

"""Configuration resolution: CLI flags override ini values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pytest

RedactMode = Literal["strict", "off"]


@dataclass(frozen=True)
class Config:
    """Resolved pytest-triage configuration. CLI takes precedence over ini."""

    triage: bool = False
    report: Path | None = None
    provider: str | None = None
    budget: int = 10
    timeout: float = 30.0
    redact: RedactMode = "strict"

    @classmethod
    def from_config(cls, config: pytest.Config) -> Config:
        return cls(
            triage=_resolve_str(config, "ai_triage") == "on",
            report=_as_path(_resolve_opt(config, "ai_report")),
            provider=_resolve_opt(config, "ai_provider"),
            budget=int(_resolve_str(config, "ai_budget")),
            timeout=float(_resolve_str(config, "ai_timeout")),
            redact="off" if _resolve_str(config, "ai_redact") == "off" else "strict",
        )


def _resolve_str(config: pytest.Config, name: str) -> str:
    """CLI value if given on the command line, else the ini value."""
    cli = config.getoption(name, default=None)
    if cli is not None:
        return str(cli)
    return str(config.getini(name))


def _resolve_opt(config: pytest.Config, name: str) -> str | None:
    """Like `_resolve_str`, but an empty/unset value resolves to None."""
    cli = config.getoption(name, default=None)
    if cli is not None:
        return str(cli)
    ini = config.getini(name)
    return str(ini) if ini else None


def _as_path(value: str | None) -> Path | None:
    return Path(value) if value else None
