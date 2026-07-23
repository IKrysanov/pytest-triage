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

"""Verdict: the flat, frozen triage result (public contract)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal["regression", "flaky", "env", "test_bug", "unknown"]
Confidence = Literal["low", "medium", "high"]

CATEGORIES: tuple[Category, ...] = ("regression", "flaky", "env", "test_bug", "unknown")
CONFIDENCES: tuple[Confidence, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class Verdict:
    """Public contract. Deliberately flat — weak models fail on nested JSON.

    Frozen; new fields must be added with defaults only.
    """

    category: Category
    hypothesis: str
    confidence: Confidence
    suggested_fix: str | None = None
