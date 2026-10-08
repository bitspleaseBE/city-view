#!/bin/zsh
set -euo pipefail

BLENDER="${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}"
ADDON_SRC="${BLENDER_MCP_ADDON:-$HOME/blender_mcp/addon/blender_mcp_addon}"
WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$(mktemp -d)"

cleanup() { rm -rf "$BUILD_DIR"; }
trap cleanup EXIT

if [[ ! -x "$BLENDER" ]]; then
  echo "Blender not found at $BLENDER" >&2
  exit 1
fi

version="$("$BLENDER" --version | head -n 1)"
echo "$version"
if ! "$BLENDER" --version | head -n 1 | grep -Eq 'Blender (5\.[1-9]|[6-9]\.)'; then
  echo "Blender MCP needs 5.1 or newer. Upgrade with: brew install --cask --force blender" >&2
  exit 1
fi

echo "Building MCP add-on from $ADDON_SRC"
"$BLENDER" --command extension build --source-dir "$ADDON_SRC" --output-dir "$BUILD_DIR"
zipfile="$(ls "$BUILD_DIR"/*.zip)"
echo "Installing $zipfile"
"$BLENDER" --command extension install-file -r user_default -e "$zipfile"
"$BLENDER" --background --online-mode --python "$WORKDIR/scripts/enable_blender_mcp_prefs.py"
echo "MCP add-on installed. Restart the Blender GUI so it listens on localhost:9876."
