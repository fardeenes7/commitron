#!/bin/sh
set -eu

PYTHON=${PYTHON:-python3}
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
BIN_DIR=${COMMITRON_BIN_DIR:-"$HOME/.local/bin"}
INSTALL_DIR="$DATA_HOME/commitron"
VENV="$INSTALL_DIR/venv"
REPOSITORY=https://github.com/fardeenes7/commitron.git
SCRIPT_PATH=
SCRIPT_DIR=
TEMP_DIR=

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON is required (Python 3.10+)." >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "error: Git is required." >&2
  exit 1
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "error: Python 3.10 or newer is required." >&2
  exit 1
}

case "$0" in
  */*) SCRIPT_PATH=$0 ;;
  *) if [ -f "$0" ]; then SCRIPT_PATH="./$0"; fi ;;
esac

if [ -n "$SCRIPT_PATH" ]; then
  SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/setup.cfg" ] \
  && grep -q '^name = commitron-cli$' "$SCRIPT_DIR/setup.cfg"; then
  SOURCE_DIR=$SCRIPT_DIR
else
  TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/commitron-install.XXXXXX")
  trap 'rm -rf "$TEMP_DIR"' EXIT HUP INT TERM
  git clone --quiet --depth 1 --branch main "$REPOSITORY" "$TEMP_DIR/source"
  SOURCE_DIR="$TEMP_DIR/source"
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade "$SOURCE_DIR"
ln -sf "$VENV/bin/commitron" "$BIN_DIR/commitron"

echo "Commitron installed at $BIN_DIR/commitron"
echo "Update it later with: commitron update"
case ":${PATH}:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add it to your PATH: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
