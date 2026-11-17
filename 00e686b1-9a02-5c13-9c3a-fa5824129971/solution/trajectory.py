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
SEARCH = 'grep -rn "use_na_sentinel=False" pandas/core/'
COMPARE = 'grep -n "is_1d_only_ea_dtype" pandas/core/frame.py pandas/core/internals/managers.py'

MI = "pandas/core/indexes/multi.py"
GB = "pandas/_libs/groupby.pyx"
FR = "pandas/core/frame.py"
MG = "pandas/core/internals/managers.py"
# (file, literal anchor or None for the whole file, lines before, lines after)
DISPLAYS = [
    (MI, "def is_monotonic_increasing(self) -> bool:", 0, 60),
    (MI, "def is_monotonic_decreasing(self) -> bool:", 0, 25),
    (MI, "def _is_lexsorted(self) -> bool:", 0, 55),
    (MI, "def _sort_levels_monotonic(self, raise_if_incomparable: bool = False) -> MultiIndex:", 0, 75),
    (MI, "def _get_codes_for_sorting(self) -> list[Categorical]:", 0, 20),
    (MI, "def sortlevel(", 0, 125),
    ("pandas/core/sorting.py", "def get_indexer_indexer(", 0, 70),
    ("pandas/core/generic.py", "indexer = get_indexer_indexer(", 25, 20),
    ("pandas/core/reshape/reshape.py", "def stack_v3(frame: DataFrame, level: list[int]) -> Series | DataFrame:", 0, 100),
    (FR, "result = stack_v3(self, level)", 30, 3),
    (MI, "def _validate_codes(self, level: Index, code: np.ndarray) -> np.ndarray:", 0, 22),
    (MI, "result_codes.append(self._validate_codes(levels[i], codes[i]))", 30, 6),
    (MI, "def _get_loc_single_level_index(self, level_index: Index, key: Hashable) -> int:", 0, 22),
    (MI, "return self._engine.get_loc(key)", 20, 6),
    (MI, "def _get_level_indexer(", 0, 110),
    (MI, "def isin(self, values, level=None) -> npt.NDArray[np.bool_]:", 0, 95),
    ("pandas/_libs/index.pyx", "codes += multiindex_nulls_shift", 20, 5),
    ("pandas/_libs/index.pyx", "def _extract_level_codes(self, target) -> np.ndarray:", 0, 25),
    ("pandas/_libs/index.pyx", "def get_loc(self, object key):", 0, 15),
    (GB, "cdef bint _treat_as_na(numeric_object_complex_t val,", 0, 20),
    (GB, "cdef numeric_object_t _get_min_or_max(", 0, 15),
    (GB, "cdef inline void _check_below_mincount(", 0, 55),
    (GB, "cdef group_min_max(", 0, 120),
    (GB, "def group_max(", 0, 25),
    (GB, "def group_min(", 0, 25),
    (GB, "cdef group_cummin_max(", 0, 115),
    (GB, "def group_cummin(", 0, 25),
    (GB, "def group_cummax(", 0, 25),
    ("pandas/core/groupby/groupby.py", "def _cython_agg_general(", 0, 50),
    ("pandas/core/groupby/ops.py", "def cython_operation(", 0, 45),
    ("pandas/core/groupby/ops.py", "def _call_cython_op(", 0, 120),
    ("pandas/core/arrays/masked.py", "def _groupby_op(", 0, 45),
    ("pandas/core/arrays/arrow/array.py", "def _to_masked(self):", 0, 14),
    ("pandas/core/arrays/arrow/array.py", "def _groupby_op(", 0, 60),
    ("pandas/core/array_algos/masked_reductions.py", "def _minmax(", 0, 45),
    ("pandas/_libs/window/aggregations.pyx", "def roll_max(", 0, 30),
    (FR, "and 1 < len(self.columns.get_indexer_for([key])) == len(value)", 25, 8),
    (FR, "def _iset_item_mgr(", 0, 30),
    (FR, "def _set_item(self, key, value) -> None:", 0, 45),
    (FR, "def _sanitize_column(self, value) -> tuple[ArrayLike, BlockValuesRefs | None]:", 0, 30),
    (FR, "def _reindex_for_setitem(", 0, 22),
    (MG, "def iset(", 0, 175),
    (MG, "def column_setitem(", 0, 35),
    (MG, "def _has_no_reference(self, i: int) -> bool:", 0, 25),
    ("pandas/core/internals/blocks.py", "def new_block_2d(", 0, 12),
    ("pandas/_libs/internals.pyx", "self.refs = BlockValuesRefs(self)", 12, 8),
    ("pandas/core/indexing.py", "self.obj._mgr.column_setitem(loc, plane_indexer, value)", 25, 3),
]
EXTRA = [
    'grep -rn "stack_v3(" pandas/core/',
    'grep -n "def group_min_max\\|def group_cummin_max\\|group_min_max(\\|group_cummin_max(" pandas/_libs/groupby.pyx',
    'grep -n "is_monotonic_increasing" pandas/core/sorting.py pandas/core/indexes/multi.py',
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
