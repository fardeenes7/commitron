# Contributing

Thanks for considering a contribution. Keep changes focused, use the Python standard library for runtime functionality where practical, and add tests for behavior changes.

## Local checks

```sh
python3 -m unittest discover -s tests
ruff check .
python3 -m commitron --help
```

Install the linter with `python3 -m pip install ruff` if `ruff` is not already on your PATH. CI runs `ruff check .` with a pinned version, so run it before opening a pull request.

For direct source imports while developing, install the project with `python3 -m pip install -e .`. Please do not include real API keys, private diffs, or generated build artifacts in pull requests.

## Pull requests

- Explain the user-facing behavior and any compatibility implications.
- Include tests and documentation updates where appropriate.
- Keep API-specific behavior compatible with OpenAI-style `/chat/completions` endpoints.

## Releasing

The version lives in `src/commitron/__init__.py` (`__version__`) and is read from there by packaging and the updater, so it is the only place to edit. When a change on `main` updates `__version__`, the `Release` workflow creates a matching `vX.Y.Z` tag and GitHub release automatically. Bump the version in the same pull request that introduces the user-facing change.
