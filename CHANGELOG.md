# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
