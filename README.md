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
| [![Downloads/month](https://static.pepy.tech/badge/pytest-triage/month)](https://pepy.tech/projects/pytest-triage) | Downloads from PyPI in the last month (via pepy) |
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

> 🚧 **Early scaffolding.** The plugin is under active development and everything
> is opt-in; installing it changes no existing suite. APIs may shift until 0.1.0.
> See [CHANGELOG.md](CHANGELOG.md) for progress.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
