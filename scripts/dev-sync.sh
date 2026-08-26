#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

if [ -e .venv ] && [ ! -L .venv ]; then
    if [ -e venv ]; then
        echo "Both .venv and venv exist; refusing to overwrite either." >&2
        exit 1
    fi
    mv .venv venv
fi

if [ -L .venv ]; then
    if [ "$(readlink .venv)" != "venv" ]; then
        echo ".venv points somewhere other than venv; refusing to replace it." >&2
        exit 1
    fi
elif [ -e .venv ]; then
    echo ".venv exists but is not a directory or symlink." >&2
    exit 1
else
    ln -s venv .venv
fi

UV_PROJECT_ENVIRONMENT=venv uv sync --extra dev

if command -v chflags >/dev/null 2>&1; then
    chflags -R nohidden venv
fi

venv/bin/python -c "import memtranslator.cli"
echo "Development environment ready. Run: uv run memtranslator start"
