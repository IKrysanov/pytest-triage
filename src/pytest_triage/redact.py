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

"""Best-effort secret redaction for failure context (strict mode)."""

from __future__ import annotations

import os
import re

_REDACTED = "[REDACTED]"
_ENV_MIN_LEN = 8

# Env var names whose long values are almost always non-secret and pervade
# tracebacks (paths, locale). Redacting them would gut triage signal, so skip.
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "PWD",
        "OLDPWD",
        "SHELL",
        "SHLVL",
        "TERM",
        "TERM_PROGRAM",
        "USER",
        "LOGNAME",
        "HOSTNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "PYENV_ROOT",
        "MANPATH",
        "INFOPATH",
        "SSH_AUTH_SOCK",
        "_",
    }
)

_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)(\s*[=:]\s*)(\S+)"
)
# Long base64-ish runs are far more likely tokens/keys than prose.
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")


def redact(text: str) -> str:
    """Scrub obvious secrets from text. Best-effort, tuned to over-redact."""
    if not text:
        return text
    text = _redact_env_values(text)
    text = _BEARER.sub(r"\g<1>" + _REDACTED, text)
    text = _ASSIGNMENT.sub(r"\g<1>\g<2>" + _REDACTED, text)
    text = _BASE64.sub(_REDACTED, text)
    return text


def _redact_env_values(text: str) -> str:
    for key, value in os.environ.items():
        if (
            len(value) < _ENV_MIN_LEN
            or key in _SAFE_ENV_KEYS
            or _looks_like_path(value)
        ):
            continue
        if value in text:
            text = text.replace(value, _REDACTED)
    return text


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "~")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in "\\/"
