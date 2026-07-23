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

# Env var names that signal a secret; their values are redacted even when short.
_SECRET_ENV_NAME = re.compile(
    r"(?i)(secret|token|password|passwd|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|auth|session)"
)

# --- Structured secret shapes. Every pattern is linear (no catastrophic
# backtracking / ReDoS). ---
# PEM private-key blocks (multi-line).
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
# JWTs: three base64url segments joined by dots (the eyJ header is base64 '{"').
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
# Credentials embedded in a URL: scheme://user:PASSWORD@host. Quantifiers are
# bounded so a long non-URL run cannot trigger quadratic scanning.
_URL_CRED = re.compile(
    r"([a-zA-Z][\w+.\-]{0,39}://[^\s:/@]{1,256}:)([^\s@/]{1,256})(@)"
)
# HTTP auth header (any scheme) and inline bearer/basic tokens.
_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*[A-Za-z]+\s+)\S+")
_BEARER = re.compile(r"(?i)((?:bearer|basic)\s+)\S+")
# Secret-ish assignments incl. shell (TOKEN=..) and JSON ("api_key": "..").
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|private[_-]?key|auth|credential)s?[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s\"',]+)"
)
# AWS access key id.
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
# Long base64/hex-ish runs are far more likely a key/token than prose.
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")


def redact(text: str) -> str:
    """Scrub obvious secrets from text. Best-effort, deliberately over-redacts."""
    if not text:
        return text
    text = _redact_env_values(text)
    text = _PEM.sub(_REDACTED, text)
    text = _JWT.sub(_REDACTED, text)
    text = _URL_CRED.sub(r"\g<1>" + _REDACTED + r"\g<3>", text)
    text = _AUTH_HEADER.sub(r"\g<1>" + _REDACTED, text)
    text = _BEARER.sub(r"\g<1>" + _REDACTED, text)
    text = _ASSIGNMENT.sub(r"\g<1>" + _REDACTED, text)
    text = _AWS_KEY.sub(_REDACTED, text)
    text = _BASE64.sub(_REDACTED, text)
    return text


def _redact_env_values(text: str) -> str:
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS or _looks_like_path(value):
            continue
        min_len = 4 if _SECRET_ENV_NAME.search(key) else _ENV_MIN_LEN
        if len(value) < min_len or value not in text:
            continue
        text = text.replace(value, _REDACTED)
    return text


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "~")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in "\\/"
