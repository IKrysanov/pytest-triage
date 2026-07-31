# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-08-01

### Added

- `GigaChatClient` now supports custom API/auth endpoints and mutual TLS options;
  unset values continue to come from `GIGACHAT_*`.
- Documented GigaChat environment settings, dev endpoints, TLS, and retry behavior.

### Security

- Strip terminal control characters from provider errors and model verdicts, and
  do it *before* redaction rather than after. A NUL is not `\s`, so
  `token\x00=hunter2` matched no rule and then read back as `token=hunter2`
  wherever control characters are dropped. Every caller is covered, so the secret
  no longer reaches the traceback, the report, or the prompt either.
- Redact compound secret assignments such as `key_file_password`,
  `db_password`, and `refresh_token`.
- Exempt only genuine endpoints from environment redaction. A URL carrying a
  query or fragment, or one under a name that claims to hold a secret
  (`API_SECRET_URL`, `*_WEBHOOK_URL`), is a capability rather than an address and
  is redacted whole; `GIGACHAT_AUTH_URL` and friends stay readable.

### Fixed

- Preserve endpoint URLs in redacted tracebacks while still hiding inline
  credentials and recognized tokens.
- Convert provider `SystemExit` and `KeyboardInterrupt` failures into normal
  error verdicts so the circuit breaker can stop further calls.
- Never let an exception escape the triage worker thread. A provider exception
  whose `__str__` or type name raises killed the handler meant to contain it;
  pytest reported that as a `PytestUnhandledThreadExceptionWarning`, which
  `-W error` turns into a failure of a run the plugin only observes.

## [0.1.2] - 2026-07-26

### Added

- Captured `logging`-module output is now collected (`FailureContext.log_tail`,
  additive, `schema_version` stays `1`) and passed to the model as a `log tail:`
  section. pytest keeps logger output in a section separate from stdout/stderr,
  so server/app logs emitted through a logger reached neither the prompt nor the
  report before; now triage sees them, byte-truncated and redacted like the
  other tails. The report gains a matching `log_tail` field per failure.
- `OpenAIClient` (optional `[openai]` extra): triage via the OpenAI Chat
  Completions API with strict function calling (`record_verdict`). Lazily
  imported, retries disabled, model via `OPENAI_MODEL` (default `gpt-4o-mini`);
  the API key and endpoint are read by the SDK from the `OPENAI_*` environment
  and never handled by the plugin. The same provider drives any OpenAI-compatible
  endpoint (Kimi/Moonshot, DeepSeek, Groq, local Ollama/vLLM) via `OPENAI_BASE_URL`
  — no per-vendor client.

### Changed

- The triage system prompt now tells the model that captured stdout, stderr and
  log output are part of the evidence and often name the cause (an HTTP 5xx or a
  connection error points to `env`), asks it to weigh code behavior against the
  test's expectation and prefer `unknown` when the context cannot say which is
  wrong, and forbids inventing files, functions or settings not in the context.
  Applies to the Anthropic and OpenAI providers, which now share one prompt
  module; the GigaChat prompt already forbade fabrication and gains the same
  output-is-evidence guidance.

### Security

- Redaction now covers vendor-prefixed API tokens that the generic base64 rule
  fragmented on `-`/`_` or skipped when short:
  - AI / VCS / packages: OpenAI/Anthropic `sk-`, GitHub (`ghp_`/`github_pat_`),
    GitLab (`glpat-`), PyPI (`pypi-`), Hugging Face (`hf_`), Docker Hub
    (`dckr_pat_`), npm (`npm_`).
  - Cloud: DigitalOcean (`do*_v1_`), Databricks (`dapi…`). (GCP service-account
    keys are PEM, already covered.)
  - Messengers / payments: Slack (`xox…`), Discord bot tokens, Telegram bot
    tokens, Stripe (`sk_live_`/`rk_test_`), Square (`sq0atp-`/`sq0csp-`),
    Twilio (`AC…`/`SK…`), Braintree/PayPal, Mailgun (`key-…`).
  - Google: API keys (`AIza…`) and OAuth (`GOCSPX-`/`ya29.`); SendGrid (`SG.…`).

  Each rule is a literal prefix plus character classes with no nested
  quantifiers, so redaction stays linear-time (no ReDoS).

### Fixed

- **Redaction destroyed file paths**: `/` was a base64 run character, so an
  absolute path in a traceback (`/Users/.../src/pytest_triage/plugin.py`) was one
  long run and got redacted whole to `[REDACTED].py` in `strict` mode — gutting
  the single most useful triage signal, the failing file. `/` is now excluded
  from the base64 run; secrets are still covered by the env, vendor, JWT, URL and
  assignment rules.
- **Redaction mangled the traceback from a short env value**: a secret-named env
  var with a common placeholder value (`API_TOKEN=test`) redacted that word
  everywhere it appeared as a substring — `test_login` → `[REDACTED]_login`,
  `pytest` → `py[REDACTED]`. Environment values are now redacted only as whole
  tokens.
- A non-finite `--ai-timeout` (`inf`/`nan`) parsed past the `> 0` check; `inf`
  would defeat the wall-clock cap. It is now a clear configuration error.
- Provider `close()` is now self-protecting: the Anthropic, OpenAI and GigaChat
  clients fence the underlying SDK teardown, so a second close or an SDK that
  raises on close (already-closed session, dead socket) can no longer surface an
  exception. `assert_conforms` now calls `close()` twice to enforce idempotency.
- Tool-call arguments are accepted as a raw JSON string or an already-parsed
  object in the OpenAI and GigaChat providers, so an OpenAI-compatible endpoint
  that returns the parsed form yields a verdict instead of degrading to
  `unknown`.

## [0.1.1] - 2026-07-25

### Added

- `GigaChatClient` (optional `[gigachat]` extra): triage via GigaChat for the RU
  segment. The system prompt is Russian and `hypothesis` / `suggested_fix` come
  back in Russian; `category` and `confidence` stay English, as the `Verdict`
  contract requires. Forces the `record_verdict` function call and falls back to
  parsing a plain-text JSON answer for deployments that ignore a forced call.
  Lazily imported, retries disabled, model via `GIGACHAT_MODEL` (default
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
- Report roll-up (additive, `schema_version` stays `1`): `ai_model`,
  `triage_duration`, `total_failures` and `total_verdicts` at the top level, so a
  consumer can tell which model produced the verdicts and what the pass cost
  without walking `failures`. All are `null`/`0` when triage did not run.
- `examples/` — a suite where every test fails for a different, believable
  reason, plus two committed sample reports (`claude-sonnet-5` and
  `GigaChat-2-Max`) for comparing providers on identical failures.

### Changed

- The Anthropic model is now selected with `ANTHROPIC_MODEL` instead of
  `PYTEST_TRIAGE_MODEL`. Each provider reads its own model variable
  (`ANTHROPIC_MODEL`, `GIGACHAT_MODEL`), so there is no cross-provider model
  environment variable left to clash.

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

[Unreleased]: https://github.com/IKrysanov/pytest-triage/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/IKrysanov/pytest-triage/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/IKrysanov/pytest-triage/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/IKrysanov/pytest-triage/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/IKrysanov/pytest-triage/releases/tag/v0.1.0
