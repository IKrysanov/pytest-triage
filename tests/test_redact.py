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

"""redact(): strict scrubbing of common secret shapes."""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import pytest

from pytest_triage.redact import redact


def test_bearer_token_redacted() -> None:
    result = redact("Authorization: Bearer abc123DEF.token-value")
    assert result == "Authorization: Bearer [REDACTED]"


def test_password_assignment_redacted() -> None:
    assert "hunter2" not in redact("db password=hunter2 connected")
    assert "[REDACTED]" in redact("db password=hunter2")


def test_base64_blob_redacted() -> None:
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="  # 20+ base64 chars
    assert "[REDACTED]" in redact(f"key={blob}")
    assert blob not in redact(blob)


def test_env_value_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SERVICE_TOKEN", "s3cr3t-value-1234")
    assert "s3cr3t-value-1234" not in redact("leaked s3cr3t-value-1234 here")


def test_short_env_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTVAL", "abc")  # below the length threshold
    assert redact("value abc stays") == "value abc stays"


def test_pathlike_env_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_DIR", "/opt/data/models")  # path-like, non-safe key
    assert "/opt/data/models" in redact("loading /opt/data/models now")


def test_url_env_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # A dev contour sets GIGACHAT_BASE_URL/GIGACHAT_AUTH_URL; both are endpoints,
    # not secrets. Scrubbing them turned "Max retries exceeded with url: ..." —
    # the one line that explains an env failure — into "[REDACTED]".
    monkeypatch.setenv("GIGACHAT_BASE_URL", "https://gigachat.dev.internal/api/v1")
    monkeypatch.setenv(
        "GIGACHAT_AUTH_URL", "https://ngw.dev.internal:9443/api/v2/oauth"
    )
    text = redact(
        "ConnectError: Max retries exceeded with url: "
        "https://gigachat.dev.internal/api/v1 (auth via "
        "https://ngw.dev.internal:9443/api/v2/oauth)"
    )
    assert "https://gigachat.dev.internal/api/v1" in text
    assert "https://ngw.dev.internal:9443/api/v2/oauth" in text


def test_signed_url_env_value_is_not_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # A query string turns a URL from an endpoint into a capability: the
    # signature *is* the credential. Only bare endpoints earn the exemption.
    monkeypatch.setenv("SIGNED_URL", "https://files.example/download?sig=z-7.f")
    assert "z-7.f" not in redact("GET https://files.example/download?sig=z-7.f failed")


def test_fragment_url_env_value_is_not_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_URL", "https://sso.example/cb#access_token=a-1.b")
    assert "a-1.b" not in redact(
        "redirect to https://sso.example/cb#access_token=a-1.b"
    )


def test_secret_named_url_env_value_is_not_exempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The shape of a capability URL is the shape of an endpoint URL — only the
    # name tells them apart. A variable that calls itself a secret is taken at
    # its word, even when the value is a bare URL.
    for name in (
        "API_SECRET_URL",
        "DOWNLOAD_TOKEN_URL",
        "SLACK_WEBHOOK_URL",
        "SESSION_URL",
    ):
        monkeypatch.setenv(name, "https://files.example/d/z-7.f")
        assert "z-7.f" not in redact("GET https://files.example/d/z-7.f failed"), name
        monkeypatch.delenv(name)


def test_auth_url_keeps_the_endpoint_exemption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `auth` must stay out of the secret-name markers: an OAuth *endpoint* is an
    # address like any other, and it is half of what the exemption exists for.
    monkeypatch.setenv("GIGACHAT_AUTH_URL", "https://ngw.dev.internal:9443/oauth")
    assert "ngw.dev.internal" in redact("POST https://ngw.dev.internal:9443/oauth 503")


def test_control_characters_do_not_defeat_redaction() -> None:
    # A NUL is not `\s`, so `token\x00=hunter2` matched no assignment rule — and
    # a later strip of control characters turned it back into a readable
    # `token=hunter2`. Redaction must see the text as it will finally be read.
    assert "hunter2" not in redact("token\x00=hunter2")
    assert "hunter2" not in redact("pass\x08word=hunter2")
    assert "hunter2" not in redact("Authorization:\x1bBearer hunter2")


def test_url_env_value_with_inline_credentials_is_not_exempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exemption covers endpoints, not connection strings that carry a secret.
    monkeypatch.setenv("DATABASE_URL", "postgres://admin:sup3rS3cret@db:5432/app")
    assert "sup3rS3cret" not in redact(
        "connecting to postgres://admin:sup3rS3cret@db:5432/app"
    )


def test_opaque_secret_inside_an_exempt_url_is_still_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defence in depth for a name that raises no suspicion at all: the exemption
    # only skips the whole-value env rule, and every other rule still runs, so a
    # long opaque path segment is caught by the base64 rule anyway. (Under a
    # name like SLACK_WEBHOOK_URL the value never reaches this point — the
    # secret-name check redacts it whole.)
    secret = "XCq3sVn8kL2mPz9wR4tYuI7o"
    url = f"https://hooks.slack.com/services/T00000000/B00000000/{secret}"
    monkeypatch.setenv("SLACK_NOTIFY_URL", url)
    text = redact(f"POST failed: {url}")
    assert secret not in text
    sanitized_url = text.removeprefix("POST failed: ")
    assert urlsplit(sanitized_url).hostname == "hooks.slack.com"


def test_compound_secret_assignment_redacted() -> None:
    # An underscore is a word character, so a `\b` prefix never matched the
    # compound names real settings use. These arrive via a settings repr or a
    # ValidationError in a traceback, and a short value misses the base64 rule
    # too, so nothing else would have caught them.
    for shape in (
        "key_file_password='Sup3rKeyPassphrase'",
        "db_password=hunter2",
        "refresh_token: abc123XYZ",
        "my_api_key=shortval",
    ):
        assert "[REDACTED]" in redact(f"ValidationError: {shape}"), shape
    assert "Sup3rKeyPassphrase" not in redact("key_file_password='Sup3rKeyPassphrase'")


def test_a_letter_before_the_keyword_still_blocks_the_match() -> None:
    # The guard only relaxes the underscore/hyphen case; an alphanumeric prefix
    # must not start matching, or "oauth=" would redact an ordinary value.
    assert redact("oauth=flow-name") == "oauth=flow-name"
    assert redact("nopwd=plain") == "nopwd=plain"


def test_empty_text_is_noop() -> None:
    assert redact("") == ""


def test_jwt_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4h-abc"
    result = redact(f"decoded from {jwt} ok")
    assert jwt not in result
    assert "[REDACTED]" in result


def test_url_credentials_redacted() -> None:
    result = redact("dsn=postgres://admin:s3cr3tPass@db.internal:5432/app")
    assert "s3cr3tPass" not in result
    assert "postgres://admin:[REDACTED]@db.internal" in result


def test_pem_private_key_redacted() -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdefGHIJ\n"
        "-----END RSA PRIVATE KEY-----"
    )
    result = redact(f"key material:\n{pem}\ndone")
    assert "MIIEpAIBAAKCAQEA1234567890abcdefGHIJ" not in result
    assert "[REDACTED]" in result


def test_json_style_api_key_redacted() -> None:
    result = redact('config {"api_key": "abcDEF123456", "url": "http://x"}')
    assert "abcDEF123456" not in result


def test_basic_auth_redacted() -> None:
    assert "dXNlcjpwYXNz" not in redact("Authorization: Basic dXNlcjpwYXNz")


def test_aws_access_key_redacted() -> None:
    assert "AKIAIOSFODNN7EXAMPLE" not in redact("aws AKIAIOSFODNN7EXAMPLE used")


def test_short_secret_named_env_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "x1y2z")  # short, but the name signals a secret
    assert "x1y2z" not in redact("leaked x1y2z here")


def test_quoted_authorization_header_redacted() -> None:
    # An SDK error message usually carries a repr of the header mapping rather
    # than a raw header line.
    text = "401 https://api.example/v1: Headers({'authorization': 'Token abc123xyz'})"
    assert "abc123xyz" not in redact(text)


def test_authorization_header_without_a_scheme_redacted() -> None:
    assert "sk-live-9f2" not in redact("authorization: sk-live-9f2")


def test_jwe_with_five_segments_redacted() -> None:
    # GigaChat access tokens are JWE: five segments, and some may be empty.
    jwe = "eyJjdHkiOiJqd3QiLCJhbGciOiJSU0EtT0FFUCJ9..dGVzdA.cGF5bG9hZA.dGFn"
    result = redact(f"token={jwe} expired")
    assert "cGF5bG9hZA" not in result
    assert "[REDACTED]" in result


def test_gigachat_credentials_env_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "ZmFrZS1jbGllbnQ6ZmFrZS1zZWNyZXQ=")
    leaked = redact("auth failed for ZmFrZS1jbGllbnQ6ZmFrZS1zZWNyZXQ= at startup")
    assert "ZmFrZS1jbGllbnQ" not in leaked


def test_openai_style_key_redacted() -> None:
    # sk- keys of OpenAI and Anthropic — this plugin's own providers.
    for key in ("sk-proj-abcDEF123456ghiJKL789", "sk-ant-api03-XyZ_abc123-DEF456ghi"):
        result = redact(f"OPENAI failed with {key} today")
        assert key not in result
        assert "[REDACTED]" in result


def test_github_tokens_redacted() -> None:
    # Fragmented by nothing here, but the prefix must go too, not just the tail.
    assert "ghp_" not in redact("token ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
    assert "github_pat_" not in redact(
        "token github_pat_11ABCDEFG0abcdefghijklmno_pqrstuvwxyz0123456789"
    )


def test_gitlab_token_redacted() -> None:
    assert "glpat-" not in redact("job used glpat-abcDEF1234567890wxyz here")


def test_slack_token_redacted() -> None:
    # Hyphens fragment the base64 rule; a dedicated Slack pattern still redacts.
    token = "xoxb-2413-2413-abcd1234EFGH5678"
    assert token not in redact(f"alert delivery failed: {token}")


def test_stripe_key_redacted() -> None:
    assert "sk_live_" not in redact("charge failed sk_live_abcDEF1234567890XYZ done")


def test_google_api_key_redacted() -> None:
    key = "AIzaSyA1234567890abcdefghijklmnopqrstuv"
    assert key not in redact(f"maps call {key} rejected")


def test_google_oauth_tokens_redacted() -> None:
    secret = "GOCSPX-abcDEF1234567890_wxyzABCD"
    access = "ya29.a0AfH6SMBexample_token-1234567890abcdefGHIJKL"
    assert secret not in redact(f"oauth client {secret} invalid")
    assert access not in redact(f"refresh returned {access} expired")


def test_telegram_bot_token_redacted() -> None:
    token = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw12x"
    result = redact(f"sendMessage failed for bot {token}")
    assert token not in result
    assert "[REDACTED]" in result


def test_sendgrid_key_redacted() -> None:
    key = "SG.aBcDeFgHiJkLmNoPqRsTuv.aBcDeFgHiJkLmNoPqRsTuvWxYz0123456789abcd"
    assert "SG." not in redact(f"mail send rejected {key} today")


def test_npm_token_redacted() -> None:
    assert "npm_" not in redact("publish npm_abcDEF1234567890ghiJKL7890mnopQRST0123 ok")


# --- stress / robustness --------------------------------------------------

_ADVERSARIAL = [
    "sk-" + "a" * 400_000,  # vendor prefix, unbounded tail
    "SG." + "a" * 200_000 + "." + "b" * 200_000,  # two-segment SendGrid
    "123456789:AA" + "a" * 400_000,  # Telegram secret tail
    "M" + "a" * 23 + "." + "b" * 6 + "." + "c" * 400_000,  # Discord third segment
    "access_token$production$" + "a" * 400_000,  # Braintree tail
    "A" * 800_000,  # base64 worst case
    "-" * 400_000,  # pure churn, nothing matches
]


@pytest.mark.parametrize("payload", _ADVERSARIAL)
def test_redaction_stays_linear_on_adversarial_input(payload: str) -> None:
    # No rule may backtrack catastrophically: each is a literal prefix plus
    # non-overlapping character classes. The bound is generous but still
    # separates linear (~ms) from quadratic (seconds+).
    start = time.perf_counter()
    redact(payload)
    assert time.perf_counter() - start < 1.0


def test_many_secret_shapes_in_one_blob_are_all_redacted() -> None:
    blob = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "app/client.py", line 88, in _auth',
            "openai.AuthenticationError: key sk-proj-AbCdEf0123456789ghIJkl rejected",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sIGnature123",
            "github ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "slack xoxb-111-222-abcDEF1234ghiJKL",
            "aws AKIAIOSFODNN7EXAMPLE",
            "dsn postgres://admin:s3cr3tPass@db.internal:5432/app",
        ]
    )
    out = redact(blob)
    for secret in (
        "sk-proj-AbCdEf0123456789ghIJkl",
        "sIGnature123",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "xoxb-111-222-abcDEF1234ghiJKL",
        "AKIAIOSFODNN7EXAMPLE",
        "s3cr3tPass",
    ):
        assert secret not in out, secret
    # the triage signal survives: file path and exception type are not secrets
    assert "app/client.py" in out
    assert "AuthenticationError" in out


def test_absolute_paths_are_not_swallowed_by_the_base64_rule() -> None:
    # Regression: `/` used to be a base64 run char, so a long absolute path was
    # redacted whole ("[REDACTED].py") — gutting the single most useful triage
    # signal, the failing file. Paths must survive; only real secrets go.
    line = (
        'File "/Users/dev/Projects/PythonProject/pytest-triage/src/'
        'pytest_triage/plugin.py", line 100, in pytest_configure'
    )
    out = redact(line)
    assert "[REDACTED]" not in out
    assert "plugin.py" in out
    assert "/Users/dev/Projects/PythonProject" in out


def test_ordinary_traceback_is_left_intact() -> None:
    # Over-redaction gutting a normal traceback would kill the triage signal.
    tb = (
        'File "app/services/checkout.py", line 42, in process\n'
        "    raise ValueError('order 12345 not found')\n"
        "ValueError: order 12345 not found"
    )
    assert redact(tb) == tb


def test_common_word_env_value_does_not_mangle_the_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A secret-named env var with a short, common placeholder value ("test")
    # must not redact that word everywhere it appears as a substring — that would
    # gut a pytest traceback ("test_login", "pytest", "latest").
    monkeypatch.setenv("API_TOKEN", "test")
    out = redact("def test_login(): pass  # pytest ran the latest suite")
    assert "test_login" in out
    assert "pytest" in out
    assert "latest" in out


def test_env_value_still_redacted_as_a_whole_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The token-bounded fix must not stop redacting a genuine standalone secret.
    monkeypatch.setenv("API_TOKEN", "test")
    assert redact("the token is test here").count("[REDACTED]") == 1
    monkeypatch.setenv("SVC_SECRET", "s3cr3t-value-1234")
    assert "s3cr3t-value-1234" not in redact("leaked s3cr3t-value-1234 here")


def test_truncation_marker_survives_redaction() -> None:
    # Losing the truncation marker silently is a known failure mode; a redaction
    # rule must never eat it while still scrubbing the secret beside it.
    text = "...[truncated 4000 bytes]...\nAKIAIOSFODNN7EXAMPLE trailing"
    out = redact(text)
    assert "[truncated 4000 bytes]" in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_ci_and_registry_tokens_redacted() -> None:
    pypi = "pypi-AgEIcHlwaS5vcmcabc1234567890DEFghij_klmno-pqrstuvwxyz"
    hf = "hf_abcDEF1234567890ghiJKL7890mnop"
    docker = "dckr_pat_abcDEF1234567890_wxyzABCD"
    assert "pypi-" not in redact(f"upload rejected {pypi} here")
    assert "hf_" not in redact(f"model pull {hf} denied")
    assert "dckr_pat_" not in redact(f"push failed {docker} now")


def test_cloud_tokens_redacted() -> None:
    do_token = "dop_v1_" + "0123456789abcdef" * 4  # 64 hex
    databricks = "dapi1234567890abcdef1234567890abcd"
    assert "dop_v1_" not in redact(f"droplet create {do_token} error")
    assert "dapi" not in redact(f"job submit {databricks} unauthorized")


def test_discord_bot_token_redacted() -> None:
    token = "MTk4NjIyNDgzNDcxOTI1MjQ4.Cl2FMQ.wr8kQd0j7d1f2g3h4i5j6k7l8m9nOP"
    result = redact(f"gateway auth failed {token} closed")
    assert token not in result
    assert "[REDACTED]" in result


def test_payment_tokens_redacted() -> None:
    twilio = "AC1234567890abcdef1234567890abcdef"
    square = "sq0atp-abcDEF1234567890_wxyzABCD1"
    braintree = "access_token$production$abc123def456ghi7"
    mailgun = "key-0123456789abcdef0123456789abcdef"
    assert twilio not in redact(f"sms send {twilio} failed")
    assert "sq0atp-" not in redact(f"charge {square} declined")
    assert "access_token$production$" not in redact(f"vault {braintree} bad")
    assert mailgun not in redact(f"email {mailgun} bounced")
