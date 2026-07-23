# Security Policy

## Supported versions

`pytest-triage` is pre-1.0. Only the latest released version receives security
fixes.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's private
vulnerability reporting ("Report a vulnerability" under the repository's Security
tab). Do not open a public issue for a security report.

We aim to acknowledge a report within five business days.

## Handling of test data

The optional LLM-triage layer sends failure context (tracebacks, captured
output) to a third-party provider. Secret redaction is enabled by default
(`--ai-redact=strict`). Do not disable it on suites whose failures may embed
credentials.

Redaction is best-effort and applies to the traceback and captured output, but
**not** to test identifiers. A parametrized test id (for example
`test_login[SECRET]`) is written verbatim to the report because it is the
selector used to rerun the test — so **do not parametrize tests with real
secrets**.

The report file is written owner-only (`0o600` on POSIX). Still treat it as
potentially sensitive and store it accordingly.
