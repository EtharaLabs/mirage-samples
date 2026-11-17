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

REPO = pathlib.Path("/workspace/pola-rs__polars")
SOLUTION = pathlib.Path(__file__).resolve().parent
SEARCH = 'grep -rn "set_sorted_flag" crates/polars-core/src/frame/ crates/polars-core/src/chunked_array/ops/gather.rs'
COMPARE = 'grep -rn "fn take_unchecked" crates/polars-core/src/chunked_array/ops/gather.rs crates/polars-compute/src/gather/mod.rs'

# (file, literal anchor or None for the whole file, lines before, lines after)
DISPLAYS = [
    ("crates/polars-core/src/chunked_array/ops/gather.rs", None, 0, 0),
    ("crates/polars-core/src/frame/group_by/aggregations/dispatch.rs", None, 0, 0),
    ("crates/polars-core/src/frame/group_by/position.rs", "pub fn is_sorted_by_first_idx(&self) -> bool", 0, 3),
    ("crates/polars-core/src/frame/group_by/position.rs", "pub fn new_slice(groups: GroupsSlice, overlapping: bool, monotonic: bool) -> Self", 0, 30),
    ("crates/polars-core/src/frame/group_by/position.rs", "pub(crate) fn is_sorted_by_first_idx(&self) -> bool", 12, 30),
    ("crates/polars-expr/src/expressions/slice.rs", None, 0, 0),
    ("crates/polars-time/src/group_by/dynamic.rs", "let groups = GroupsType::new_slice(groups, true, true);", 40, 3),
    ("crates/polars-expr/src/expressions/aggregation.rs", "GroupByMethod::First => {", 2, 6),
    ("crates/polars-core/src/frame/group_by/aggregations/mod.rs", "pub(crate) unsafe fn agg_min(&self, groups: &GroupsType) -> Series", 0, 16),
    ("crates/polars-core/src/frame/group_by/aggregations/mod.rs", "pub(crate) unsafe fn agg_max(&self, groups: &GroupsType) -> Series", 0, 16),
    ("crates/polars-core/src/frame/column/mod.rs", "fn agg_with_scalar_identity(", 2, 60),
    ("crates/polars-core/src/frame/column/scalar.rs", "fn _to_series(", 0, 10),
    ("crates/polars-core/src/frame/column/scalar.rs", "pub fn take_materialized_series(self) -> Series", 0, 5),
    ("crates/polars-core/src/chunked_array/ops/mod.rs", "fn new_from_index(&self, index: usize, length: usize) -> ChunkedArray<T>", 4, 5),
    ("crates/polars-core/src/chunked_array/mod.rs", "pub fn set_validity(&mut self, validity: Option<Bitmap>)", 0, 20),
    ("crates/polars-core/src/chunked_array/mod.rs", "pub fn set_sorted_flag(", 0, 6),
    ("crates/polars-core/src/chunked_array/mod.rs", "pub fn first_non_null(&self)", 2, 30),
    ("crates/polars-core/src/chunked_array/mod.rs", "pub fn last_non_null(&self)", 2, 30),
    ("crates/polars-core/src/chunked_array/mod.rs", "fn copy_with_chunks(", 0, 3),
    ("crates/polars-core/src/chunked_array/from.rs", "pub fn from_chunk_iter_like", 0, 14),
    ("crates/polars-core/src/chunked_array/ops/aggregate/mod.rs", "fn min(&self) -> Option<T::Native>", 0, 60),
    ("crates/polars-core/src/chunked_array/ops/unique/mod.rs", "fn unique(&self) -> PolarsResult<Self>", 0, 85),
    ("crates/polars-core/src/chunked_array/ops/sort/mod.rs", "macro_rules! sort_with_fast_path", 0, 30),
    ("crates/polars-core/src/frame/group_by/into_groups.rs", "fn create_groups_from_sorted", 4, 100),
    ("crates/polars-arrow/src/legacy/kernels/sort_partition.rs", "pub fn partition_to_groups_amortized<T>(", 2, 60),
    ("crates/polars-core/src/chunked_array/ops/append.rs", "fn unit_or_sorted_flag", 2, 60),
    ("crates/polars-core/src/chunked_array/cast.rs", "fn cast_impl(", 0, 50),
    ("py-polars/src/polars/series/series.py", "return get_series_item_by_key(self, key)", 4, 1),
    ("py-polars/src/polars/_utils/getitem.py", "def _select_elements_by_index", 0, 3),
    ("py-polars/src/polars/_utils/getitem.py", "def _select_rows_by_index", 0, 3),
    ("py-polars/src/polars/_utils/getitem.py", "def _convert_series_to_indices", 0, 55),
    ("crates/polars-python/src/series/general.rs", "fn gather_with_series", 0, 3),
    ("crates/polars-core/src/series/implementations/mod.rs", "fn take(&self, indices: &IdxCa)", 2, 3),
    ("crates/polars-ops/src/chunked_array/gather/chunked.rs", "unsafe fn take_chunked_unchecked<", 0, 40),
    ("crates/polars-ops/src/chunked_array/gather/chunked.rs", "unsafe fn take_chunked_unchecked_binview", 0, 3),
    ("crates/polars-ops/src/chunked_array/gather/chunked.rs", "_update_gather_sorted_flag(ca.is_sorted_flag(), sorted)", 6, 3),
    ("crates/polars-compute/src/gather/mod.rs", "pub unsafe fn take_unchecked(", 0, 30),
    ("crates/polars-core/src/utils/mod.rs", "pub fn first_non_null<", 0, 40),
    ("crates/polars-ops/src/frame/join/hash_join/sort_merge.rs", None, 0, 0),
    ("crates/polars-arrow/src/legacy/kernels/sorted_join/inner.rs", None, 0, 0),
    ("crates/polars-arrow/src/legacy/kernels/sorted_join/left.rs", None, 0, 0),
    ("crates/polars-ops/src/frame/join/mod.rs", "fn _inner_join_from_series(", 0, 60),
    ("crates/polars-ops/src/frame/join/dispatch_left_right.rs", "pub fn materialize_left_join_from_series(", 0, 50),
    ("crates/polars-ops/src/frame/join/hash_join/single_keys_inner.rs", "use polars_utils::total_ord::{ToTotalOrd, TotalEq, TotalHash};", 0, 30),
]
EXTRA = [
    'grep -rn "_update_gather_sorted_flag" crates/',
    'grep -rn "is_sorted_by_first_idx" crates/polars-core/src/',
    'grep -n "agg_with_scalar_identity" crates/polars-core/src/frame/column/mod.rs',
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
