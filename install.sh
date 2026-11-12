#!/usr/bin/env bash
# Stage 1: interactive plan only. Does not install or change the system.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -B "$SCRIPT_DIR/installer/wizard.py" "$@"
