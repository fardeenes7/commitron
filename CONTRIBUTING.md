# Contributing

Thanks for considering a contribution. Keep changes focused, use the Python standard library for runtime functionality where practical, and add tests for behavior changes.

## Local checks

```sh
python3 -m unittest discover -s tests
python3 -m commitron --help
```

For direct source imports while developing, install the project with `python3 -m pip install -e .`. Please do not include real API keys, private diffs, or generated build artifacts in pull requests.

## Pull requests

- Explain the user-facing behavior and any compatibility implications.
- Include tests and documentation updates where appropriate.
- Keep API-specific behavior compatible with OpenAI-style `/chat/completions` endpoints.
