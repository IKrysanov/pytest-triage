# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `GigaChatClient` (optional `[gigachat]` extra): triage via GigaChat for the RU
  segment. The system prompt is Russian and `hypothesis` / `suggested_fix` come
  back in Russian; `category` and `confidence` stay English, as the `Verdict`
  contract requires. Forces the `record_verdict` function call and falls back to
  parsing a plain-text JSON answer for deployments that ignore a forced call.
  Lazily imported, retries disabled, model via `PYTEST_TRIAGE_MODEL` (default
  `GigaChat` Lite); credentials, scope and TLS trust are read by the SDK from the
  `GIGACHAT_*` environment and never handled by the plugin.
- `CircuitBreakerClient`: triage stops for the rest of the run after the first
  timeout or two consecutive provider errors. A provider that is down can no
  longer spend the whole budget, and a hung one can no longer turn
  `budget × timeout` into a five-minute suite.
- Terminal cost line — `pytest-triage: 2 provider call(s), 1 from cache` — so a
  run's spend is visible without instrumenting the provider.
- `redact_nodeid` and `render_sections` are public at `pytest_triage.providers`,
  so a third-party provider inherits nodeid scrubbing and empty-section trimming.

### Fixed

- **Invariant 1**: an exception while collecting a failure's context, or a
  third-party `pytest_triage_report` implementer that raises, escaped
  `pytest_exception_interact` / `pytest_sessionfinish` and could change the run's
  exit code. Both are now fenced and reported on stderr.
- **Secret leak**: a parametrized `nodeid` (`test_login[sk-live-...]`) was sent to
  the provider verbatim. The `[...]` section is now redacted in the prompt; the
  report keeps the raw nodeid, which is the rerun selector.
- **Secret leak**: `Authorization` headers were only redacted in raw header form,
  not in the `Headers({'authorization': '...'})` repr that SDK errors carry, and
  the JWT pattern missed five-segment JWEs (GigaChat access tokens).
- **Wasted spend**: xdist workers built their own provider client in
  `pytest_configure` and collected failures nobody read — one extra
  authentication per worker. Workers now return early.
- **Wasted spend**: prompts always carried `stdout tail:` / `stderr tail:`
  sections even when empty, billing tokens for nothing on every call.
- Cache key: failures without a traceback all collapsed onto a single verdict.
  The key now includes the exception type and falls back to the nodeid.
- A model returning an unbounded `hypothesis` or `suggested_fix` wrote it
  straight into the report; verdict text is now truncated by bytes with a marker.

## [0.1.0] - 2026-07-23

First public release. Fully opt-in: installing the plugin changes no existing suite.

### Added

- Failure collection: opt-in `--ai-*` options (CLI over ini) building a frozen
  `FailureContext` per failure, with byte-budgeted truncation (explicit marker)
  and strict, linear-time secret redaction; controller-only under xdist.
- Versioned JSON report (`--ai-report=PATH`, `schema_version: 1`) with per-failure
  context, verdict, and `pytest_args` to rerun exactly the failures. Written
  atomically and owner-only (`0o600`); a write failure never affects the run.
- Provider contract: frozen `Verdict`, `TriageClient` protocol, `BaseTriageClient`
  template method, `FakeTriageClient` / `OAuthFakeClient`, a lazy registry (entry
  points + import strings, `PROVIDER_API_VERSION`), and the `assert_conforms` kit.
- `AnthropicClient` (optional `[anthropic]` extra): strict tool use, lazily
  imported, model via `PYTEST_TRIAGE_MODEL`, retries disabled to fail fast.
- Triage execution: `CachingClient` / `BudgetedClient` / `TimedOutClient` composed
  by one factory. `--ai-triage=on` analyzes each failure, writes verdicts to the
  report (default `.triage.json`), and prints a summary. A provider that raises,
  times out, or is misconfigured degrades to `unknown` with the cause surfaced,
  never changing the run's exit code (invariant 1).
- Packaging and workflows: `src`-layout, hatchling, ruff, strict mypy, CI matrix
  (3.10–3.13), CodeQL, Scorecard, DCO, Dependabot, Codecov, and a Trusted-Publishing
  release with Sigstore attestations.

[Unreleased]: https://github.com/IKrysanov/pytest-triage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/IKrysanov/pytest-triage/releases/tag/v0.1.0
