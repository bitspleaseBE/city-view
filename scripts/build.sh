#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m cityview build "$@"
