# Contributing

This is intended as a reusable community extension. Keep application-specific business logic, account identifiers, and deployment state out of the library. The shared retail scenario is only an example.

## Develop

Install Python 3.14 and uv. Python 3.12 and 3.13 remain in the compatibility test matrix. Clone the repository, then run:

```sh
uv sync --all-extras --group dev
uv run ruff format .
uv run ruff check .
uv run pytest
uv build
```

Tests use local fixtures by default and do not require AWS/provider credentials or make paid API calls. The end-to-end fixtures run the real Strands tool loop and actual WebSocket connections; AWS/model responses are simulated. OpenAI transport tests use the real official SDK against a local server.

## Changes

Open an issue for substantial API changes. Submit a focused pull request with the behavior change, relevant checks, and any live-test limitations. Add behavioral tests for new protocol handling, providers, or persistence failure paths. Do not claim live provider/Connect acceptance from mocks.

Follow Strands' public extension patterns: ordinary `@tool` tools and `HookProvider` hooks for `BidiAgent`. Keep provider SDK quirks in their own provider modules. Never accept contact IDs from model-selected parameters or hide failed persistence behind a successful business result.

The pinned SDK has experimental bidirectional APIs. An upgrade needs review of the OpenAI/Gemini compatibility seams, optional dependency resolution, full protocol tests, and fresh live acceptance before changing advertised support.

## Releases

Version in `pyproject.toml`; changelog in `CHANGELOG.md`. CI builds a wheel and source distribution. PyPI publishing is not yet configured; Git installation is the supported initial distribution. A maintainer should establish trusted publishing and release credentials before publishing to PyPI.

Contributions are licensed under Apache 2.0.
