#!/usr/bin/env bash
# Alternate process oracle: the same locations shown with awk windows that number every line.
set -euo pipefail
SOLUTION=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
python3 "$SOLUTION/trajectory.py" awk
