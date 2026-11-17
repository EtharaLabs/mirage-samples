"""Process oracle: display every location the reference answer rests on, then answer.

    python3 trajectory.py {grep|sed|awk|cat}

Runs real display commands in the checkout, records each command with its output as one
agent step in /logs/agent/trajectory.json, and writes the reference answer to
/workspace/answer.md and /logs/agent/answer.md. The modes show the same locations with
different tools, so the deterministic checks are exercised by four independent command
shapes. Anchors are located at run time, so line shifts from comment stripping do not
matter. Standard library only.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path("/workspace/pandas-dev__pandas")
SOLUTION = pathlib.Path(__file__).resolve().parent
SEARCH = 'grep -rn "tuples_to_object_array" pandas/'
COMPARE = 'grep -n "_inplace_method" pandas/core/generic.py'

MI = "pandas/core/indexes/multi.py"
BASE = "pandas/core/indexes/base.py"
GEN = "pandas/core/generic.py"
# (file, literal anchor or None for the whole file, lines before, lines after)
DISPLAYS = [
    ("pandas/_libs/lib.pyx", "def tuples_to_object_array(ndarray[object] tuples):", 0, 16),
    ("pandas/_libs/lib.pyx", "def to_object_array_tuples(rows: object) -> np.ndarray:", 0, 45),
    (MI, "def from_tuples(", 0, 90),
    (BASE, "def _maybe_downcast_for_indexing(self, other: Index) -> tuple[Index, Index]:", 0, 60),
    (BASE, "def get_indexer(", 0, 130),
    (BASE, "tgt_values = engine._extract_level_codes(", 15, 10),
    (MI, "def _recode_for_new_levels(", 0, 15),
    ("pandas/_libs/index.pyx", "def _extract_level_codes(self, target) -> np.ndarray:", 0, 25),
    (MI, "def _wrap_reindex_result(self, target, indexer, preserve_names: bool):", 0, 16),
    (BASE, "if new_values.size and isinstance(new_values[0], tuple):", 8, 8),
    (MI, "def isin(self, values, level=None) -> npt.NDArray[np.bool_]:", 0, 95),
    (GEN, "def _inplace_method(self, other, op) -> Self:", 0, 75),
    ("pandas/core/ops/array_ops.py", "def logical_op(left: ArrayLike, right: Any, op) -> ArrayLike:", 0, 45),
    ("pandas/core/series.py", "def _logical_method(self, other, op) -> Series:", 0, 15),
    (GEN, "def compare(", 0, 160),
    ("pandas/core/frame.py", "def compare(", 0, 60),
    ("pandas/core/frame.py", "return super().compare(", 6, 8),
    ("pandas/core/series.py", "return super().compare(", 6, 8),
    ("pandas/core/reshape/pivot.py", "def pivot(", 0, 240),
    ("pandas/core/frame.py", "return pivot(self, index=index, columns=columns, values=values)", 6, 2),
]
EXTRA = [
    'grep -n "where(mask)" pandas/core/generic.py',
    'grep -n "_values" pandas/core/reshape/pivot.py',
    'grep -n "_maybe_downcast_for_indexing(" pandas/core/indexes/base.py',
]


def _anchor_line(path: str, literal: str) -> int:
    for number, line in enumerate((REPO / path).read_text(encoding="utf-8").splitlines(), start=1):
        if literal in line:
            return number
    raise SystemExit(f"anchor {literal!r} not found in {path}")


def _length(path: str) -> int:
    return len((REPO / path).read_text(encoding="utf-8").splitlines())


def _command(mode: str, path: str, literal: str | None, before: int, after: int) -> str:
    if mode == "cat" or literal is None:
        return f"cat -n {path}"
    if mode == "grep":
        return f"grep -n -F -B {before} -A {after} '{literal}' {path}"
    line = _anchor_line(path, literal)
    start, end = max(1, line - before), min(_length(path), line + after)
    if mode == "sed":
        return f"sed -n '{start},{end}p' {path}"
    if mode == "awk":
        return f"awk 'NR>={start} && NR<={end} {{print NR\": \"$0}}' {path}"
    raise SystemExit(f"unknown mode {mode!r}")


def main(mode: str) -> int:
    commands = [SEARCH, COMPARE]
    for path, literal, before, after in DISPLAYS:
        command = _command(mode, path, literal, before, after)
        if command not in commands:
            commands.append(command)
    commands += EXTRA
    steps = []
    for number, command in enumerate(commands, start=1):
        proc = subprocess.run(["bash", "-lc", command], cwd=REPO, capture_output=True, text=True)
        steps.append({
            "step_id": number,
            "source": "agent",
            "message": "",
            "tool_calls": [{"tool_call_id": f"call_{number}", "name": "bash", "arguments": {"command": command}}],
            "observation": {"content": (proc.stdout or "") + (proc.stderr or "")},
        })
    answer = (SOLUTION / "answer.md").read_text(encoding="utf-8")
    steps.append({"step_id": len(steps) + 1, "source": "agent", "message": answer})
    logs = pathlib.Path("/logs/agent")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "trajectory.json").write_text(json.dumps({"steps": steps}, indent=1), encoding="utf-8")
    (logs / "answer.md").write_text(answer, encoding="utf-8")
    pathlib.Path("/workspace/answer.md").write_text(answer, encoding="utf-8")
    print(f"[oracle:{mode}] {len(commands)} commands executed, trajectory and answer written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "grep"))
