![Commitron banner](https://raw.githubusercontent.com/fardeenes7/commitron/main/assets/commitron.png)

# Commitron

**I create commit messages so you don't have to.** Commitron sends the working-tree diff to an OpenAI-compatible chat API, asks it to group related files, shows you the proposed titles, and commits only after you approve. Use `-y` for non-interactive/automatic commits.

```text
$ commitron
› Found 5 changed file(s) in /work/project.
! The Git diff will be sent to the configured API provider for commit planning.

Commit plan
  1. Add account profile validation
     • src/profile.py
     • tests/test_profile.py
  2. Document profile setup
     • README.md
Create these commits? [y/N] y
✓ a1b2c3d Add account profile validation
✓ d4e5f6a Document profile setup
✓ Created 2 commit(s).
```

## Install

Install directly from GitHub with one command:

```sh
curl -fsSL https://raw.githubusercontent.com/fardeenes7/commitron/main/install.sh | sh
```

Or, from a checkout, run the included installer:

```sh
./install.sh
```

The installer creates an isolated virtual environment under `~/.local/share/commitron` and puts the `commitron` command in `~/.local/bin`. Add that directory to `PATH` if needed:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Optional: add a short `commit` alias to your `~/.bashrc` or `~/.zshrc` (only if you don't already use that alias):

```sh
alias commit='commitron'
```

For development, `python3 -m pip install -e .` installs the command in the active Python environment. Python 3.10+ and Git are required. There are no runtime dependencies.

## Quick start

Run `commitron` anywhere inside a Git repository that has at least one commit. The default is preview + confirmation. Use `--dry-run` to inspect the AI plan without committing, or `-y` / `--yes` to commit without the confirmation prompt.

```sh
commitron
commitron --dry-run
commitron -y
commitron --description
```

By default, the tool asks for **single-line commit titles only**. `--description` (alias `--with-description`) also asks for a short commit body. Each changed file is assigned to exactly one commit; multiple commits in a pass are supported.

## API configuration

The default endpoint is OpenRouter's OpenAI-compatible API (`https://openrouter.ai/api/v1`) with model `openrouter/free`. Set an OpenRouter key, or let the app request one securely (input is hidden):

```sh
export OPENROUTER_API_KEY="your-key"
commitron
```

`OPENAI_API_KEY` is also detected. When it is the selected credential and no endpoint override is given, the app uses `https://api.openai.com/v1`. OpenRouter is preferred if both standard key variables are set. No key is saved to disk.

```sh
# Choose an OpenAI-compatible provider and model
commitron --base-url https://api.openai.com/v1 --model gpt-4o-mini

# Read a key from a custom environment variable
export MY_LLM_SECRET="your-key"
commitron --api-key-env MY_LLM_SECRET

# Persist endpoint/model defaults in your shell environment
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export COMMITRON_MODEL="openrouter/free"
```

Options:

| Option | Description |
| --- | --- |
| `-y`, `--yes` | Skip confirmation and create the proposed commits automatically. |
| `--dry-run` | Ask the API for a plan and display it; do not commit. |
| `--description`, `--with-description` | Generate a title and short commit body instead of title-only messages. |
| `--base-url URL` | OpenAI-compatible API base URL; `/chat/completions` is appended. |
| `--model NAME` | Override the model (default: `openrouter/free`). |
| `--api-key-env NAME` | Use a custom environment variable for the API key. |
| `--timeout SECONDS` | API timeout (default: 90 seconds). |
| `--max-diff-bytes N` | Maximum diff sent to the API (default: 500,000 bytes). |
| `--no-color` | Disable terminal colors. `NO_COLOR` is also respected. |

## Safety and privacy

- The full Git diff, including untracked non-ignored files, is sent to your configured API provider. **Review your changes for credentials, private data, and proprietary code before running the tool.** A size limit prevents accidentally sending very large diffs.
- The model response is treated as untrusted. Before any commit, `commitron` rejects plans that omit, invent, or assign a changed path more than once.
- Commit construction uses a temporary Git index and the exact snapshot shown to the model. The user's index is not changed during planning. After successful commits, the real index is synchronized to the new `HEAD`; any edits made later remain visible as unstaged worktree changes.
- Existing changes are not reset or discarded. A hook or Git failure may leave earlier commits from the same run in place; the error reports which commits succeeded, and the tool does not attempt a destructive rollback.
- `--dry-run` never invokes `git commit` or changes the real index.

## Development

```sh
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m commitron --help
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and [SECURITY.md](SECURITY.md) to report a vulnerability.
