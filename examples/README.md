# Examples — a suite that fails on purpose

A realistic suite where **every test fails**, each for a different, believable
reason: a defect in the code under test, a wrong test expectation, or a broken
environment (including real `500` / `503` / timeout responses from `httpbin.org`).
It exists to show what `pytest-triage` produces on genuine failures — and to
compare providers on the exact same cases.

These files are **not** part of the package test suite (`testpaths = ["tests"]`),
they hit the network, and they are meant to be run by hand.

## See the output without running anything

Two real reports from this suite are committed so you can read what triage
produces before setting up any key — the same 26 failures through two providers,
diff them to compare:

- [`sample-triage-anthropic.json`](sample-triage-anthropic.json) — `claude-sonnet-5`
- [`sample-triage-gigachat.json`](sample-triage-gigachat.json) — `GigaChat-2-Max` (verdicts in Russian)

Each report opens with `ai_model` and `triage_duration`, so you can tell at a
glance which model produced it and how long it took.

## Run it

```bash
pip install -e ".[anthropic]" requests      # or ".[gigachat]"

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
pytest examples/ --ai-triage=on --ai-provider=anthropic \
       --ai-report=.triage-anthropic.json --ai-budget=40

# GigaChat (RU) — TLS trusts the Russian Trusted Root CA, verification stays on
export GIGACHAT_CREDENTIALS=...
export GIGACHAT_CA_BUNDLE_FILE=/path/to/russian_trusted_bundle.pem
pytest examples/ --ai-triage=on --ai-provider=gigachat \
       --ai-report=.triage-gigachat.json --ai-budget=40
```

The report lands in `.triage-*.json` (git-ignored). Open it to read each
verdict, or diff the two provider reports.

> The test bodies carry **no hint** of the expected category — the traceback is
> what the model sees, so labelling it in a comment would rig the evaluation.
> The intended diagnosis for each group is documented here instead.

## What each group is meant to be

| File | Intended category | Why |
|:-----|:------------------|:----|
| `test_regressions.py` | `regression` | `shop.py` functions carry a real defect (off-by-one, wrong discount formula, unguarded input, bad recursion); the expectation is correct. |
| `test_wrong_expectations.py` | `test_bug` | The API/code is correct; the test asserts a wrong value, type, or count. |
| `test_environment.py` | `env` | Unreachable hosts (DNS) and **real** upstream failures — `httpbin.org` `500` / `503` and a request that times out. |
| `test_soft_assert.py` | mixed | A soft-assert collector raises several joined failures. `test_pricing_soft` is all product bugs (`regression`); `test_profile_soft` is all wrong expectations (`test_bug`); `test_checkout_soft` mixes both — a good stress of the flat single-verdict. |

`regression` vs `test_bug` is genuinely ambiguous for some pure-logic cases
(passing bad input to a function): a good model will lean one way or honestly
answer `unknown`. That ambiguity is the point — it shows where triage is
reliable and where it is not.
