#!/usr/bin/env bash
# Process oracle: display every location the reference answer rests on with grep windows,
# then write the reference answer.
set -euo pipefail
SOLUTION=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python3 "$SOLUTION/trajectory.py" grep
