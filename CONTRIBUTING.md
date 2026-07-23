# Contributing to pytest-triage

Thanks for your interest in improving pytest-triage. This document covers the
local setup, the checks CI enforces, and the Developer Certificate of Origin
sign-off that every commit must carry.

## Development setup

The only runtime dependency is pytest; everything else is dev tooling.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

CI runs exactly these — run them locally before opening a PR:

```bash
ruff check .
ruff format --check .   # drop --check to auto-format in place
mypy
pytest
```

`pytest` excludes network-backed tests by default (`-m "not live"`). Coverage on
the sibling projects targets ~99%; keep new code covered.

## Dependency locks

CI installs a hash-pinned toolchain from `requirements/` so the OpenSSF
Scorecard Pinned-Dependencies check stays green. Regenerate the locks with
[uv](https://docs.astral.sh/uv/) after changing `pyproject.toml`'s `dev` extra
or `requirements/build.in`:

```bash
# dev toolchain (ruff, mypy, pytest, pytest-cov + transitive)
uv pip compile pyproject.toml --extra dev --universal --generate-hashes \
  --python-version 3.10 --no-annotate --no-header -o requirements/dev.txt

# build toolchain (build, twine + transitive)
uv pip compile requirements/build.in --universal --generate-hashes \
  --python-version 3.10 --no-annotate --no-header -o requirements/build.txt
```

Dependabot bumps both locks weekly.

## Developer Certificate of Origin (DCO)

Every commit must carry a `Signed-off-by:` trailer certifying that you wrote the
change or otherwise have the right to submit it under the project's license (see
the [DCO](https://developercertificate.org/)). Add it automatically:

```bash
git commit -s
```

The DCO workflow rejects a pull request if any commit is missing the trailer.
Fix an existing branch with:

```bash
git rebase --signoff origin/main
git push --force-with-lease
```

## Pull requests

- One focused change per PR.
- Update `CHANGELOG.md` under `[Unreleased]`. Do not bump the version — that
  happens at tagging time.
- Do not add runtime dependencies without maintainer sign-off.
