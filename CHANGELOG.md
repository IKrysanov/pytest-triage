# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project scaffolding: `src`-layout package, `pyproject.toml` (hatchling), ruff,
  mypy strict, pytest configuration, GitHub Actions CI matrix (Python
  3.10–3.13), Apache-2.0 license, and a security policy.
- Supply-chain and release workflows: CodeQL (SAST), OpenSSF Scorecard, DCO
  sign-off check, Dependabot, and a PyPI/TestPyPI publish pipeline via Trusted
  Publishing with Sigstore attestations. CI installs a hash-pinned toolchain
  from `requirements/` and uploads coverage and JUnit results to Codecov
  (coverage + Test Analytics). Added `CONTRIBUTING.md` and issue templates.
- Plugin skeleton and failure-context collection: opt-in `--ai-*` options
  resolved CLI-over-ini, the frozen `FailureContext` public contract,
  byte-budgeted truncation with an explicit marker, strict secret redaction, and
  an xdist-guarded controller-only collection pass. Loaded by default but fully
  transparent unless enabled (invariants 1-2).
- JSON failure-report artifact (`--ai-report=PATH`): versioned
  `schema_version: 1`, per-failure context with `verdict: null`, and
  `pytest_args` (argv-style selectors) that rerun exactly the failed tests.
  Written atomically and owner-only (`0o600`); a write failure never changes
  the run's outcome.
- Hardened secret redaction: JWTs, URL-embedded credentials, PEM private-key
  blocks, AWS access keys, JSON/shell secret assignments, and short
  secret-named env values. All redaction patterns are linear (no ReDoS).
