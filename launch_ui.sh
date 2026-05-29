#!/usr/bin/env bash
# =============================================================================
# launch_ui.sh — DMD GIF Converter UI launcher
# macOS & Linux
#
# First run : creates a Python venv and installs all dependencies.
# Next runs  : activates the venv and starts the UI directly.
#
# Usage:
#   ./launch_ui.sh
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
UI="$SCRIPT_DIR/dmd_gif_converter_ui.py"

# ── Locate a suitable Python (3.10+) ─────────────────────────────────────────
find_python() {
    # macOS: prefer Homebrew Python (ships with Tk 9.0 — system Tk 8.5 crashes on macOS 15+/26)
    # Linux: prefer the highest available version
    for candidate in \
        /opt/homebrew/opt/python@3.13/bin/python3.13 \
        /opt/homebrew/bin/python3.13 \
        /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.11 \
        /opt/homebrew/bin/python3 \
        python3.13 \
        python3.12 \
        python3.11 \
        python3.10 \
        python3
    do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# ── Check / create venv ───────────────────────────────────────────────────────
if [ ! -f "$VENV/bin/python3" ]; then
    echo "==> First run — setting up virtual environment…"

    PYTHON=$(find_python) || {
        echo ""
        echo "ERROR: Python 3.10+ not found."
        echo ""
        echo "  macOS  : brew install python@3.13"
        echo "  Ubuntu : sudo apt install python3 python3-tk python3-venv"
        echo "  Fedora : sudo dnf install python3 python3-tkinter"
        echo "  Arch   : sudo pacman -S python tk"
        exit 1
    }

    echo "    Python : $PYTHON ($("$PYTHON" --version 2>&1))"

    "$PYTHON" -m venv "$VENV" || {
        echo "ERROR: Could not create virtual environment."
        exit 1
    }

    echo "==> Installing dependencies…"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet customtkinter Pillow "darkdetect==0.7.1" || {
        echo "ERROR: pip install failed."
        exit 1
    }

    echo "==> Environment ready."
    echo ""
fi

# ── Launch the UI ─────────────────────────────────────────────────────────────
exec "$VENV/bin/python3" "$UI"

