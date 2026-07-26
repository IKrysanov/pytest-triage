# pytest-triage

Structured failure triage for pytest. It collects a machine-readable report of
every failed test and — optionally — enriches each failure with an LLM verdict
(**regression / flaky / environment / test bug**), so an on-call engineer gets a
hypothesis and a ready-to-run rerun command instead of a wall of tracebacks.

Built to feed
[`airflow-pytest-operator`](https://github.com/IKrysanov/airflow-pytest-operator):
a nightly DAG that fails at 3 a.m. can alert with a diagnosis instead of two
thousand lines of traceback.

**Package**

| Badge | What it tells you |
|:------|:------------------|
| [![PyPI version](https://img.shields.io/pypi/v/pytest-triage.svg)](https://pypi.org/project/pytest-triage/) | Latest release on PyPI — `pip install pytest-triage` |
| [![Python versions](https://img.shields.io/pypi/pyversions/pytest-triage.svg)](https://pypi.org/project/pytest-triage/) | Supported Python versions (3.10+) |
| [![pytest](https://img.shields.io/badge/pytest-7.0%2B-0A9EDC.svg?logo=pytest&logoColor=white)](https://docs.pytest.org/) | A pytest plugin — requires pytest 7.0+ |
| [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) | Distributed under the Apache-2.0 licence |

**Quality & build**

| Badge | What it tells you |
|:------|:------------------|
| [![CI](https://github.com/IKrysanov/pytest-triage/actions/workflows/ci.yml/badge.svg)](https://github.com/IKrysanov/pytest-triage/actions/workflows/ci.yml) | Lint, types and the unit matrix (Python 3.10–3.13) on `main` |
| [![codecov](https://codecov.io/gh/IKrysanov/pytest-triage/branch/main/graph/badge.svg)](https://codecov.io/gh/IKrysanov/pytest-triage) | Test coverage of the package |
| [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) | Fully type-checked with mypy `--strict` |
| [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) | Linted & formatted with Ruff |
| [![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/IKrysanov/pytest-triage/badge)](https://scorecard.dev/viewer/?uri=github.com/IKrysanov/pytest-triage) | OpenSSF supply-chain security score |

**AI providers** — bring your own key; each is an optional extra:

[![Anthropic Claude](https://img.shields.io/badge/Anthropic-Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![OpenAI GPT](https://img.shields.io/badge/OpenAI-GPT-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
[![GigaChat](https://img.shields.io/badge/GigaChat-Sber-21A038?style=for-the-badge&logo=sberbank&logoColor=white)](https://giga.chat/)

> **Everything is opt-in.** Installing `pytest-triage` changes the behaviour of
> zero existing suites. Nothing runs, no report is written, and no network is
> touched until you pass an explicit `--ai-*` flag. See
> [CHANGELOG.md](CHANGELOG.md).

---

## Table of contents

- [Why](#why)
- [Install](#install)
- [Quick start](#quick-start)
- [The report](#the-report)
- [Configuration](#configuration)
- [Providers](#providers)
  - [Anthropic](#anthropic)
  - [OpenAI](#openai)
    - [OpenAI-compatible endpoints](#openai-compatible-endpoints)
  - [GigaChat (for the RU segment)](#gigachat-for-the-ru-segment)
- [What a run costs](#what-a-run-costs)
- [Write your own provider](#write-your-own-provider)
- [How it works](#how-it-works)
- [Safety: the four invariants](#safety-the-four-invariants)
- [Using it from Airflow](#using-it-from-airflow)
- [Development](#development)
- [Scope of 0.1.x](#scope-of-01x)
- [License](#license)

## Why

A failed test in CI or a nightly DAG gives you a traceback. Somebody still has to
read it and answer the only question that matters: **is this my fault, the
test's fault, or the environment's fault?**

`pytest-triage` turns that judgement into structured data:

- a **machine-readable JSON report** of every failure — stable, versioned schema,
  with a ready-to-run rerun command;
- an optional **LLM verdict** per failure — one of `regression`, `flaky`, `env`,
  `test_bug`, or `unknown`, plus a one-line hypothesis and a suggested fix;
- **secret redaction** before anything leaves the process, so tracebacks with
  tokens or passwords don't end up in an artifact or a prompt.

It is deliberately narrow. It does **not** generate tests and it is **not** an
LLM-evaluation framework — those niches are already well served.

## Install

```bash
pip install pytest-triage
```

The core package depends only on `pytest`. LLM providers are optional extras:

```bash
pip install "pytest-triage[anthropic]"   # adds the Anthropic provider
```

```bash
pip install "pytest-triage[openai]"      # adds the OpenAI provider
```

```bash
pip install "pytest-triage[gigachat]"    # adds the GigaChat provider (RU)
```

## Quick start

Everything is off until you ask for it. Three levels of opt-in:

**1. Just the report — no AI, no network:**

```bash
pytest --ai-report=failures.json
```

Runs your suite exactly as before, and additionally writes `failures.json`
describing each failure. Every `verdict` is `null` — no provider is involved.

**2. Add an LLM verdict per failure:**

```bash
pip install "pytest-triage[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
pytest --ai-triage=on --ai-provider=anthropic
```

Turning triage on writes the report to `.triage.json` automatically (override the
path with `--ai-report=PATH`).

…or, for a Russian-language verdict from GigaChat:

```bash
pip install "pytest-triage[gigachat]"
export GIGACHAT_CREDENTIALS=...
pytest --ai-triage=on --ai-provider=gigachat
```

**3. Try it with zero setup using the built-in deterministic fake:**

```bash
pytest --ai-triage=on --ai-provider=fake
```

The `fake` provider hits no network and returns a deterministic verdict keyed off
the exception type — ideal for wiring up your pipeline before committing to a
real model. After any triaged run you also get a one-line terminal summary:

```
pytest-triage: 1 env, 2 test_bug
```

**New here? Try it on failures that fail on purpose.** [`examples/`](examples/) is
a small suite where every test breaks for a *different, believable* reason — a
real server `500`, a wrong assertion, a product bug, a DNS timeout — so you can
see what each verdict looks like before pointing it at your own suite:

```bash
pip install requests            # the examples make real HTTP calls
pytest examples/ --ai-triage=on --ai-provider=fake --ai-report=.triage.json
```

Swap `fake` for `anthropic` or `gigachat` (with a key) to compare real verdicts.

## The report

The report is a single JSON object with a **versioned schema** (`schema_version`)
that only ever grows. One failure looks like this:

```json
{
  "schema_version": 1,
  "created_at": "2026-07-23T15:03:30Z",
  "ai_model": "claude-sonnet-5",
  "triage_duration": 4.12,
  "pytest_args": [
    "tests/test_shop.py::test_checkout_total",
    "tests/test_shop.py::test_db_connection"
  ],
  "failures": [
    {
      "nodeid": "tests/test_shop.py::test_db_connection",
      "pytest_args": ["tests/test_shop.py::test_db_connection"],
      "phase": "call",
      "outcome": "failed",
      "exc_type": "ConnectionError",
      "exc_message": "could not connect to db at 10.0.0.5:5432",
      "traceback": "def test_db_connection():\n>       raise ConnectionError(...)\n...",
      "duration": 0.00004,
      "stdout_tail": "",
      "stderr_tail": "",
      "log_tail": "",
      "verdict": {
        "category": "env",
        "hypothesis": "ConnectionError in tests/test_shop.py::test_db_connection",
        "confidence": "low",
        "suggested_fix": null
      }
    }
  ],
  "total_failures": 2,
  "total_verdicts": 1
}
```

Key fields:

| Field | Meaning |
|:------|:--------|
| `pytest_args` (top level) | De-duplicated selectors that **rerun exactly the failures** in one command: `pytest $(jq -r '.pytest_args[]' .triage.json)` |
| `ai_model` / `triage_duration` / `total_failures` / `total_verdicts` (top level) | Roll-up you can read without walking `failures`: which model produced the verdicts and how long the pass took (both `null` when triage was off), how many tests failed, and how many got an AI verdict |
| `failures[].verdict` | `null` when triage is off; otherwise a flat object with `category`, `hypothesis`, `confidence` (`low`/`medium`/`high`), and `suggested_fix` (string or `null`) |
| `traceback` / `stdout_tail` / `stderr_tail` / `log_tail` | Captured traceback, stdout, stderr, and `logging`-module output; byte-truncated with an explicit `...[truncated N bytes]...` marker, and secret-redacted in `strict` mode |

The report is written **atomically** (temp file + rename) and **owner-only**
(`0o600`) — even after redaction it may hold residual sensitive output and must
not be world-readable on a shared CI host. A write failure prints a warning and
**never changes the run's outcome**.

## Configuration

Every option has a CLI flag and a matching `ini` key. **CLI overrides `ini`.**
All names are namespaced `--ai-` / `ai_`.

| CLI flag | `ini` key | Default | Purpose |
|:---------|:----------|:--------|:--------|
| `--ai-triage=on\|off` | `ai_triage` | `off` | Enable LLM triage of failures |
| `--ai-report=PATH` | `ai_report` | `.triage.json` when triage on, else off | Report path override |
| `--ai-provider=NAME` | `ai_provider` | *(unset)* | Provider name or `module:attr` import string |
| `--ai-budget=N` | `ai_budget` | `10` | Max provider calls per run |
| `--ai-timeout=SEC` | `ai_timeout` | `30` | Wall-clock cap per triage call |
| `--ai-redact=strict\|off` | `ai_redact` | `strict` | Secret redaction mode |

Triage runs only when `--ai-triage=on` **and** a provider is set — the two are
deliberately separate, so you can configure `ai_provider` centrally in `ini` yet
keep triage (and its cost) off until a specific run turns it on. A half-set
combination (`--ai-triage=on` with no provider, or a provider with triage off)
emits a config-time **warning** rather than silently doing nothing.

When triage is on, the report is written to `.triage.json` automatically — pass
`--ai-report=PATH` to choose another path. Without triage, `--ai-report=PATH`
still writes a report on its own, with every `verdict` set to `null`.

Set defaults for a project in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
ai_triage = "on"
ai_provider = "anthropic"
ai_report = ".triage.json"
ai_budget = "20"
```

…or `pytest.ini` / `tox.ini`:

```ini
[pytest]
ai_triage = on
ai_provider = anthropic
ai_report = .triage.json
```

Triage runs only when `--ai-triage=on` **and** a provider is set. `--ai-report`
works on its own (verdicts stay `null`).

## Providers

A provider is the thin transport that turns a failure into a verdict. Two are
built in and require no extra dependency:

| Name | What it does |
|:-----|:-------------|
| `fake` | Deterministic verdict from the exception type (`AssertionError → test_bug`, `ConnectionError`/`TimeoutError`/`OSError → env`, else `regression`). No network. |
| `oauth-fake` | Same, but exercises a lazy token-refresh lifecycle — a reference for OAuth-style transports. |

Three more ship as optional extras: [`anthropic`](#anthropic),
[`openai`](#openai), and [`gigachat`](#gigachat-for-the-ru-segment).

### Anthropic

The `anthropic` provider ships in the `[anthropic]` extra and talks to the
Anthropic Messages API through the official
[`anthropic`](https://pypi.org/project/anthropic/) SDK:

```bash
pip install "pytest-triage[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
pytest --ai-triage=on --ai-provider=anthropic
```

It calls the API with **strict tool use** (`record_verdict`) so the model returns
a structured verdict directly. Deployments or answers that don't fit are handled
gracefully: a non-conforming response is parsed by the tolerant base parser, and
anything unrecognisable becomes `category="unknown"` rather than an error. Retries
are disabled so a rate-limited call fails fast instead of retrying past the
wall-clock cap.

`pytest-triage` never touches your credentials. Everything below is read straight
from the environment:

| Environment variable | What it is |
|:---------------------|:-----------|
| `ANTHROPIC_API_KEY` | API key. Read by the SDK unless passed explicitly |
| `ANTHROPIC_AUTH_TOKEN` | Bearer token, as an alternative to the API key |
| `ANTHROPIC_MODEL` | Model name. Default `claude-sonnet-5`. Anthropic-specific — read only by this provider |
| `ANTHROPIC_BASE_URL` | Override the API endpoint (a gateway or proxy) |

The model defaults to `claude-sonnet-5`. Override it with the provider's own env
var — it is Anthropic-specific, so there is nothing shared to clash:

```bash
export ANTHROPIC_MODEL=claude-haiku-4-5
```

The `anthropic` SDK is imported **lazily**: if the extra isn't installed you get a
clear configuration-time error — never a surprise `ImportError` mid-run.

### OpenAI

The `openai` provider ships in the `[openai]` extra and talks to the OpenAI Chat
Completions API through the official
[`openai`](https://pypi.org/project/openai/) SDK:

```bash
pip install "pytest-triage[openai]"
export OPENAI_API_KEY=sk-...
pytest --ai-triage=on --ai-provider=openai
```

It forces a **function call** (`record_verdict`, strict schema) so the model
returns a structured verdict directly. A non-conforming answer is parsed by the
tolerant base parser, and anything unrecognisable becomes `category="unknown"`
rather than an error. Retries are disabled so a rate-limited call fails fast
instead of retrying past the wall-clock cap.

`pytest-triage` never touches your credentials. Everything below is read straight
from the environment:

| Environment variable | What it is |
|:---------------------|:-----------|
| `OPENAI_API_KEY` | API key. Read by the SDK unless passed explicitly |
| `OPENAI_MODEL` | Model name. Default `gpt-4o-mini`. OpenAI-specific — read only by this provider |
| `OPENAI_BASE_URL` | Override the API endpoint (a gateway, proxy, or compatible host) |
| `OPENAI_ORG_ID` | Organization id, when your key belongs to several |

The model defaults to `gpt-4o-mini` (cheap and reliable for classifying a
traceback). Override it with the provider's own env var:

```bash
export OPENAI_MODEL=gpt-4o
```

The `openai` SDK is imported **lazily**: if the extra isn't installed you get a
clear configuration-time error — never a surprise `ImportError` mid-run.

#### OpenAI-compatible endpoints

The `openai` provider is **not** tied to OpenAI's own servers. A growing number of
APIs speak the same protocol, so you can point it at any of them with
`OPENAI_BASE_URL` and a model — **no new provider, no new code**:

[![Kimi](https://img.shields.io/badge/Kimi-Moonshot-16151A?style=flat-square&logo=moonshot&logoColor=white)](https://www.moonshot.ai/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-4D6BFE?style=flat-square&logo=deepseek&logoColor=white)](https://www.deepseek.com/)
[![Groq](https://img.shields.io/badge/Groq-F55036?style=flat-square&logo=groq&logoColor=white)](https://groq.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.com/)
[![vLLM](https://img.shields.io/badge/vLLM-self--hosted-30A2FF?style=flat-square)](https://docs.vllm.ai/)

| Endpoint | `OPENAI_BASE_URL` | Example `OPENAI_MODEL` |
|:---------|:------------------|:-----------------------|
| **Kimi** (Moonshot) | `https://api.moonshot.ai/v1` | `kimi-k2-0711-preview` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| **Ollama** (local) | `http://localhost:11434/v1` | any pulled model, e.g. `qwen2.5` |
| **vLLM** / **LM Studio** (self-hosted) | `http://your-host:8000/v1` | your served model |

```bash
# Kimi (Moonshot) — same provider, different endpoint
export OPENAI_API_KEY=<moonshot-key>
export OPENAI_BASE_URL=https://api.moonshot.ai/v1
export OPENAI_MODEL=kimi-k2-0711-preview
pytest --ai-triage=on --ai-provider=openai
```

For a **local** model the key can be any non-empty placeholder
(`OPENAI_API_KEY=ollama`). Function-calling support varies by endpoint; where a
model doesn't honour the forced call, the tolerant parser reads its plain-text
answer and falls back to `category="unknown"` — the run is never affected.

> **Azure OpenAI** is *not* a plain base-url swap — it needs the SDK's
> `AzureOpenAI` client (api-version, deployment names). Wrap it in a small custom
> provider (see [Write your own provider](#write-your-own-provider)) rather than
> `OPENAI_BASE_URL`.

### GigaChat (for the RU segment)

The `gigachat` provider ships in the `[gigachat]` extra and talks to GigaChat
through the official [`gigachat`](https://pypi.org/project/gigachat/) SDK:

```bash
pip install "pytest-triage[gigachat]"
export GIGACHAT_CREDENTIALS=...          # your GigaChat authorization key
pytest --ai-triage=on --ai-provider=gigachat
```

**The prompt and the verdict text are Russian.** GigaChat is a Russian model and
reasons noticeably better in its own language, so `hypothesis` and
`suggested_fix` come back in Russian:

```json
{
  "category": "env",
  "hypothesis": "Тест не смог подключиться к базе: сервис недоступен в CI.",
  "confidence": "high",
  "suggested_fix": "Проверить, что контейнер postgres поднят до старта прогона."
}
```

`category` and `confidence` stay in English — they are the machine-readable part
of the frozen `Verdict` contract, and downstream consumers match on them.

The provider forces a **function call** (`record_verdict`) so the model returns a
structured verdict. Deployments that don't honour a forced call still work: a
plain-text JSON answer is parsed by the tolerant base parser, and anything
unrecognisable becomes `category="unknown"` rather than an error.

`pytest-triage` never touches your credentials. Everything below is read by the
SDK straight from the environment:

| Environment variable | What it is |
|:---------------------|:-----------|
| `GIGACHAT_CREDENTIALS` | Authorization key (base64 `client_id:client_secret`) |
| `GIGACHAT_SCOPE` | `GIGACHAT_API_PERS` (default), `GIGACHAT_API_B2B`, `GIGACHAT_API_CORP` |
| `GIGACHAT_MODEL` | Model name. Default `GigaChat` (Lite). GigaChat-specific — read only by this provider |
| `GIGACHAT_CA_BUNDLE_FILE` | Path to a CA bundle for verifying the endpoint |
| `GIGACHAT_ACCESS_TOKEN` | A pre-issued token, instead of credentials |

The model defaults to `GigaChat` (Lite — the cheapest one that still classifies a
traceback reliably). Override it with the SDK's own env var — each provider has
its own, so there is nothing shared to clash:

```bash
export GIGACHAT_MODEL=GigaChat-2-Max
```

**Certificate trust.** The root CA that signs the GigaChat endpoints does not
ship in `certifi`, so out of the box you will see `CERTIFICATE_VERIFY_FAILED`,
surfaced as a `triage provider error` (the run itself still passes or fails
exactly as before). Point the SDK at a bundle that contains it:

```bash
export GIGACHAT_CA_BUNDLE_FILE=/path/to/ca-bundle.crt
```

Keep such a bundle in a git-ignored `certs/` folder. For GigaChat, fetch the
official Russian Trusted Root CA — verification stays **on**:

```bash
curl -fsSL -o certs/root.crt https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
curl -fsSL -o certs/sub.crt  https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt
awk 1 certs/root.crt certs/sub.crt > certs/russian_trusted_bundle.pem
export GIGACHAT_CA_BUNDLE_FILE="$PWD/certs/russian_trusted_bundle.pem"
```

Disabling verification is possible via the SDK's own `GIGACHAT_VERIFY_SSL_CERTS`,
but `pytest-triage` will never turn it off for you.

## What a run costs

Triage is billed per call, so the plugin is built to keep the number of calls
small and visible. Every triaged run prints what it actually spent:

```
pytest-triage: 1 env, 2 test_bug
pytest-triage: 2 provider call(s), 1 from cache
```

Four things bound the bill:

- **`--ai-budget=N` (default 10)** — a hard cap on provider calls per run. A
  suite with 300 failures still makes at most 10 calls; the rest come back as
  `unknown` with the reason `triage budget exhausted`.
- **Caching** — identical failures (normalized traceback + exception type) are
  analyzed once. One broken fixture that fails 40 tests is one call.
- **A circuit breaker** — the first timeout, or two consecutive provider errors,
  stops triage for the rest of the run. A provider that is down cannot burn the
  whole budget, and a hung one cannot turn `budget × timeout` into a five-minute
  suite.
- **Bounded prompts** — the context is truncated by bytes before it is sent (4 KB
  of traceback, 2 KB of each output tail, 1 KB of the exception message), and
  empty sections are dropped rather than sent as empty labels. A worst-case
  prompt is roughly 8 KB; a typical one is well under 2 KB.

So a default run costs **at most 10 calls of ≤ ~8 KB prompt and ≤ 512–1024
response tokens each**, and usually far less. Set `--ai-budget=0` to keep the
report while spending nothing.

## Write your own provider

Most teams have a private model (an internal gateway, a self-hosted GigaChat, a
local model). Implement ~80 lines of transport and you inherit prompt rendering,
tolerant JSON parsing, budget, caching, timeout, and the circuit breaker for free.

```python
# myco/testing/triage.py
from pytest_triage.providers import BaseTriageClient


class MyClient(BaseTriageClient):
    def __init__(self) -> None:
        self._session = ...  # your HTTP client / SDK

    def _request(self, prompt: str) -> str:
        # Send `prompt` to your model and return its raw text reply.
        # BaseTriageClient parses the JSON out of it tolerantly; an
        # unparseable reply becomes category="unknown", never an exception.
        return self._session.complete(prompt)

    def close(self) -> None:
        self._session.close()
```

If you write your own `_render_prompt`, use the two public helpers so your
provider keeps the same cost and safety properties:

```python
from pytest_triage.providers import redact_nodeid, render_sections


def _render_prompt(self, ctx):
    return render_sections(
        [
            # Parametrized ids embed argument values (test_login[sk-live-...]);
            # redact_nodeid scrubs the [...] part before it leaves the machine.
            ("nodeid: ", redact_nodeid(ctx.nodeid)),
            # render_sections drops empty sections — an empty stdout tail still
            # costs prompt tokens on every single call.
            ("traceback:\n", ctx.traceback),
            ("stdout tail:\n", ctx.stdout_tail),
        ]
    )
```

Register it either way (both are supported):

```toml
# Entry point — for teams that package their provider.
[project.entry-points."pytest_triage.providers"]
myco = "myco.testing.triage:MyClient"
```

```bash
# Import string — for teams without private package infrastructure.
pytest --ai-triage=on --ai-provider=myco.testing.triage:MyClient
```

Verify it against the public conformance kit:

```python
from pytest_triage.testing import assert_conforms
from myco.testing.triage import MyClient


def test_my_provider_conforms() -> None:
    assert_conforms(MyClient())
```

The public contract lives at `pytest_triage.providers`
(`TriageClient`, `BaseTriageClient`, `Verdict`, `PROVIDER_API_VERSION`,
`redact_nodeid`, `render_sections`) and
`pytest_triage.context.FailureContext`. `Verdict` is deliberately **flat** — weak
models produce invalid JSON on nested schemas, so keep it flat.

## How it works

```
      test fails
          │
          ▼
pytest_exception_interact ──►  FailureContext          (context.py)
  (controller only)            · truncate by bytes + marker
                               · redact secrets (strict)
          │
          ▼
pytest_sessionfinish  ──────►  triage each failure      (wrappers.py)
                               CachingClient
                                └─ CircuitBreakerClient
                                    └─ BudgetedClient
                                        └─ TimedOutClient
                                            └─ your provider
          │                    every call fenced: raise/timeout → "unknown"
          ▼
pytest_triage_report  ──────►  write .triage.json        (report.py)
pytest_terminal_summary ────►  "pytest-triage: 1 env, 2 test_bug"
                               "pytest-triage: 2 provider call(s), 1 from cache"
```

- **Collection** happens in `pytest_exception_interact`, where both the report and
  the live exception are available (`pytest_runtest_logreport` fires too early to
  see the exception type).
- **Triage** is composed in a single factory, `build_triage_client`. Cross-cutting
  concerns are decorators over the provider, never logic inside it:
  `CachingClient` (dedupes identical failures) wraps `CircuitBreakerClient`
  (stops after a timeout or two errors in a row) wraps `BudgetedClient` (caps
  provider calls) wraps `TimedOutClient` (hard wall-clock cap). Cache is
  outermost, so a cache hit costs neither budget nor time; the breaker sits above
  the budget, so a tripped breaker spends nothing at all.
- **Every provider call is fenced.** A provider that raises, hangs, or returns
  garbage yields a `category="unknown"` verdict — the exception never escapes.
  So does a failure whose context cannot be collected, and a downstream
  `pytest_triage_report` implementer that raises.
- **Under xdist**, triage and reporting run on the controller only; workers return
  from `pytest_configure` before a provider is ever built. Worker-failure
  aggregation is out of scope for 0.1.x, and a report run under `-n` warns and
  stays empty.

## Safety: the four invariants

These are enforced by tests, not just documented:

1. **AI never affects the test verdict.** The plugin lives strictly in the
   reporting layer. A provider raising, timing out, or returning garbage leaves
   the run **byte-identical** to a run without the plugin — same exit code, same
   outcome, same collection.
2. **Disabled by default.** Installing the plugin changes the behaviour of zero
   existing suites. Everything is opt-in.
3. **The report schema is versioned from day one** and evolves additively only.
4. **`FailureContext` and `Verdict` are frozen public contracts.** New fields get
   defaults; nothing is renamed or removed.

Secret redaction (`--ai-redact=strict`, the default) scrubs JWTs and JWEs,
URL-embedded credentials, PEM private keys, AWS access keys, `Authorization`
headers (raw or inside an SDK error's header repr), bearer/basic tokens,
secret-named assignments, and known-secret environment values before a failure is
written or sent to a provider. It is best-effort and deliberately over-redacts;
every pattern is linear (no ReDoS). Set `--ai-redact=off` only for local
debugging.

Two things to know about what redaction does **not** cover:

- **A test's `nodeid` stays verbatim in the report.** It is the rerun selector,
  and pytest already prints it to the terminal and to JUnit XML, so scrubbing it
  in the artifact would buy nothing. The copy that goes **to a provider** is
  scrubbed: `redact_nodeid` cleans the `[...]` parametrization section, where
  argument values actually live.
- **Model output is not a trusted channel.** A verdict is capped in length and
  written as-is; treat `hypothesis` and `suggested_fix` as text a model wrote
  after reading your traceback, not as a fact.

## Using it from Airflow

The intended downstream consumer is
[`airflow-pytest-operator`](https://github.com/IKrysanov/airflow-pytest-operator):
a nightly DAG runs your suite with `--ai-report=.triage.json`, the operator reads
the report and pushes the verdicts to XCom, and the alert carries a diagnosis and
a rerun command instead of a raw traceback. Because the schema is versioned and
the contracts are frozen, the operator can rely on the shape of the report across
plugin upgrades.

## Development

```bash
python -m pip install -e ".[dev]"
```

Run the suite, lint, and types the way CI does:

```bash
pytest                 # unit matrix; the `live` marker is excluded by default
ruff check . && ruff format --check .
mypy
```

Notes:

- **Coverage** must be measured with `coverage run -m pytest`, **not**
  `pytest --cov`. `pytest-triage` is a startup-loaded `pytest11` plugin, so
  `pytest-cov` starts tracing too late and reports import-time lines as
  uncovered.
- **The `live` marker** hits a real provider endpoint and is excluded from the
  default run via `addopts = -m "not live"`. Run it explicitly with an API key:
  `pytest -m live`.
- Behavioural tests use pytest's own `pytester` fixture and
  `runpytest_subprocess()` where exit-code fidelity matters.

## Scope of 0.1.x

Intentionally **not** in this release: flaky-run detection, a persistent cache,
git blame/context, an OpenAI provider, an MCP server, parallel triage, and xdist
support beyond the controller guard.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
