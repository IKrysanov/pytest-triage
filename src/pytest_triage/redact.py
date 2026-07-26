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
# JWT/JWE: base64url segments joined by dots (the eyJ header is base64 '{"').
# 3 segments is a signed JWT, 5 an encrypted JWE (GigaChat access tokens are
# JWE, and its middle segments may be empty).
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*){2,4}")
# Credentials embedded in a URL: scheme://user:PASSWORD@host. Quantifiers are
# bounded so a long non-URL run cannot trigger quadratic scanning.
_URL_CRED = re.compile(
    r"([a-zA-Z][\w+.\-]{0,39}://[^\s:/@]{1,256}:)([^\s@/]{1,256})(@)"
)
# HTTP auth header (any scheme, scheme optional) and inline bearer/basic tokens.
# The quotes matter: an SDK error often carries a repr of the header mapping
# ({'authorization': 'Bearer ey...'}), which the unquoted pattern missed.
_AUTH_HEADER = re.compile(
    r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?(?:[A-Za-z]+\s+)?)\S+"
)
_BEARER = re.compile(r"(?i)((?:bearer|basic)\s+)\S+")
# Secret-ish assignments incl. shell (TOKEN=..) and JSON ("api_key": "..").
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|private[_-]?key|auth|credential)s?[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s\"',]+)"
)
# AWS access key id.
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# --- Vendor-prefixed API tokens. Each carries an unambiguous prefix, so a
# dedicated rule redacts the whole token (prefix included) and catches shapes
# the generic base64 rule fragments on ('-' / '_') or skips when short. Every
# pattern is a literal prefix plus a single character class: strictly linear. ---
_PREFIXED_TOKENS = (
    # OpenAI / Anthropic keys: sk-, sk-proj-..., sk-ant-... (this plugin's own
    # providers — the most likely key to end up in a client's traceback).
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    # GitHub personal / OAuth / app / refresh tokens, and fine-grained PATs.
    re.compile(r"\bgh[opsur]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    # GitLab personal access token.
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    # Slack bot / user / app / refresh tokens.
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    # Stripe secret / restricted keys.
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"),
    # Google API key.
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}"),
    # Google OAuth: client secret (GOCSPX-) and ya29. access tokens.
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),
    # Telegram bot token: <bot-id>:AA<secret>. The `AA` marker keeps a bare
    # `digits:text` from matching.
    re.compile(r"\b\d{6,}:AA[A-Za-z0-9_-]{30,}"),
    # SendGrid API key: SG.<id>.<secret>. Each segment is its own char class,
    # separated by a literal dot, so there is no backtracking across segments.
    re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{30,}"),
    # npm access token.
    re.compile(r"\bnpm_[A-Za-z0-9]{36}"),
    # --- CI / VCS / package registries. ---
    # PyPI upload token.
    re.compile(r"\bpypi-[A-Za-z0-9_-]{40,}"),
    # Hugging Face access token.
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    # Docker Hub personal access token.
    re.compile(r"\bdckr_pat_[A-Za-z0-9_-]{20,}"),
    # --- Cloud providers. (GCP service-account keys are PEM, already covered.) ---
    # DigitalOcean personal / OAuth / refresh tokens.
    re.compile(r"\bdo[opr]_v1_[a-f0-9]{64}"),
    # Databricks personal access token.
    re.compile(r"\bdapi[0-9a-f]{32,}"),
    # --- Messengers / payments. ---
    # Discord bot token: <id>.<timestamp>.<hmac>, three dot-separated segments,
    # each its own char class so there is no cross-segment backtracking.
    re.compile(r"\b[MNO][A-Za-z0-9_-]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"),
    # Twilio Account / API key SID.
    re.compile(r"\b(?:AC|SK)[0-9a-f]{32}\b"),
    # Square access token / OAuth secret.
    re.compile(r"\bsq0(?:atp|csp)-[A-Za-z0-9_-]{20,}"),
    # Braintree / PayPal access token.
    re.compile(r"\baccess_token\$(?:production|sandbox)\$[0-9a-z]{16,}"),
    # Mailgun API key.
    re.compile(r"\bkey-[0-9a-f]{32}\b"),
)

# Long base64/hex-ish runs are far more likely a key/token than prose. `/` is
# deliberately excluded from the run: a filesystem path in a traceback
# ("/app/services/checkout") is otherwise one long [A-Za-z0-9/] run and gets
# swallowed whole, destroying the triage signal. A standard-base64 blob that
# happens to contain `/` is still caught in its `/`-delimited parts, and real
# credentials are covered by the env, vendor, JWT, URL and assignment rules.
_BASE64 = re.compile(r"(?<![A-Za-z0-9+])[A-Za-z0-9+]{20,}={0,2}(?![A-Za-z0-9+=])")


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
    for pattern in _PREFIXED_TOKENS:
        text = pattern.sub(_REDACTED, text)
    text = _BASE64.sub(_REDACTED, text)
    return text


def _redact_env_values(text: str) -> str:
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS or _looks_like_path(value):
            continue
        min_len = 4 if _SECRET_ENV_NAME.search(key) else _ENV_MIN_LEN
        if len(value) < min_len or value not in text:
            continue
        # Replace only whole-token occurrences. A short placeholder value
        # (TOKEN=test) must not gut every "test" inside "test_login"/"pytest";
        # a substring replace would mangle the traceback it is meant to clarify.
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])"
        text = re.sub(pattern, _REDACTED, text)
    return text


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "~")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in "\\/"
