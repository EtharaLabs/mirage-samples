#!/usr/bin/env bash
# Alternate process oracle: the same locations shown with sed line ranges located at run time.
set -euo pipefail
SOLUTION=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
python3 "$SOLUTION/trajectory.py" sed
