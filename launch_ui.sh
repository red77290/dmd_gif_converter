#!/usr/bin/env bash
# =============================================================================
# launch_ui.sh — DMD GIF Converter UI launcher
# macOS & Linux
#
# First run : creates a Python venv and installs all dependencies.
# Next runs  : activates the venv and starts the UI directly.
#              If requirements_ui.txt changed since last install, re-runs pip.
#
# Usage:
#   ./launch_ui.sh
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
UI="-m src.ui.launcher"
REQ="$SCRIPT_DIR/requirements_ui.txt"
REQ_HASH_FILE="$VENV/.requirements_hash"

# ── Locate a suitable Python (3.10+) ─────────────────────────────────────────
is_safe_python() {
    candidate="$1"
    if [ "$(uname -s)" != "Darwin" ]; then
        return 0
    fi

    # Reject Apple CLT Python + Tk 8.5 (known hard crash with Tk UI on recent macOS).
    tk_ver="$($candidate - <<'PY' 2>/dev/null
import tkinter as tk
print(tk.TkVersion)
PY
)"

    if [ -z "$tk_ver" ]; then
        return 1
    fi

    awk -v v="$tk_ver" 'BEGIN { exit !(v >= 8.6) }'
}

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
            if is_safe_python "$candidate"; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

# ── Compute a checksum of requirements_ui.txt (portable: md5 or sha256) ──────
req_checksum() {
    if command -v md5sum >/dev/null 2>&1; then
        md5sum "$REQ" | awk '{print $1}'
    elif command -v md5 >/dev/null 2>&1; then
        md5 -q "$REQ"
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$REQ" | awk '{print $1}'
    else
        # Fallback: use file modification time
        stat -c '%Y' "$REQ" 2>/dev/null || stat -f '%m' "$REQ" 2>/dev/null || echo "unknown"
    fi
}

# ── Install / upgrade dependencies if needed ─────────────────────────────────
install_deps() {
    echo "==> Installing / updating dependencies…"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REQ" || {
        echo "ERROR: pip install failed."
        exit 1
    }
    # Save current checksum so we skip this next time
    req_checksum > "$REQ_HASH_FILE"
    echo "==> Dependencies up to date."
    echo ""
}

# ── Check / create venv ───────────────────────────────────────────────────────
if [ -f "$VENV/bin/python3" ] && ! is_safe_python "$VENV/bin/python3"; then
    echo "==> Existing .venv uses an incompatible Python/Tk runtime. Recreating…"
    rm -rf "$VENV"
fi

if [ ! -f "$VENV/bin/python3" ]; then
    echo "==> First run — setting up virtual environment…"

    PYTHON=$(find_python) || {
        echo ""
        echo "ERROR: No compatible Python found."
        echo ""
        echo "  macOS  : brew install python@3.13"
        echo "           (Apple CommandLineTools Python uses Tk 8.5 and will crash this UI)"
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

    install_deps

    echo "==> Environment ready."
    echo ""
else
    # Venv already exists — check if customtkinter works and if requirements_ui.txt changed
    if ! "$VENV/bin/python3" -c "import customtkinter" >/dev/null 2>&1; then
        echo "==> Missing dependencies detected in .venv — installing..."
        install_deps
    else
        CURRENT_HASH="$(req_checksum)"
        SAVED_HASH="$(cat "$REQ_HASH_FILE" 2>/dev/null || echo "")"

        if [ "$CURRENT_HASH" != "$SAVED_HASH" ]; then
            echo "==> requirements_ui.txt changed — updating dependencies…"
            install_deps
        fi
    fi
fi

# ── Launch the UI ─────────────────────────────────────────────────────────────
# Suppress [mp3float @ ...] / Header missing messages from OpenCV's internal
# FFmpeg backend (VideoCapture). Must be set before Python starts.
export OPENCV_FFMPEG_CAPTURE_OPTIONS="loglevel;quiet"
export OPENCV_LOG_LEVEL="SILENT"
exec "$VENV/bin/python3" $UI "$@"

