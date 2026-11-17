#!/usr/bin/env bash
# Alternate process oracle: the same locations shown with whole-file cat -n of every file the answer rests on.
set -euo pipefail
SOLUTION=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
python3 "$SOLUTION/trajectory.py" cat
