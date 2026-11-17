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
SEARCH = 'grep -rn "sum_output_dtype" crates/'
COMPARE = 'grep -rn "ExtraColumnsPolicy" crates/polars-plan/src/plans/'

SER = "py-polars/src/polars/series/series.py"
HZ = "crates/polars-ops/src/series/ops/horizontal.rs"
SCH = "crates/polars-plan/src/plans/aexpr/function_expr/schema.rs"
FS = "crates/polars-plan/src/dsl/file_scan/mod.rs"
ASOF = "crates/polars-ops/src/frame/join/asof/mod.rs"
STREAM_ASOF = "crates/polars-stream/src/nodes/joins/asof_join.rs"
# (file, literal anchor or None for the whole file, lines before, lines after)
DISPLAYS = [
    ("crates/polars-python/src/series/scatter.rs", None, 0, 0),
    (SER, "def scatter(", 0, 65),
    (SER, "def __setitem__(", 0, 85),
    ("py-polars/src/polars/dataframe/frame.py", "s[row_selection] = value", 25, 10),
    (HZ, "pub fn sum_horizontal(", 0, 75),
    (HZ, "pub fn mean_horizontal(", 0, 60),
    (SCH, "SumHorizontal { .. } => mapper.map_to_supertype().map(|mut f| {", 0, 18),
    (SCH, "pub fn nested_sum_type(&self) -> PolarsResult<Field> {", 0, 12),
    ("crates/polars-core/src/chunked_array/ops/aggregate/mod.rs", "pub fn sum_output_dtype(in_dtype: &DataType) -> DataType {", 0, 10),
    ("crates/polars-expr/src/dispatch/misc.rs", "polars_ops::prelude::sum_horizontal(s, null_strategy).map(Option::unwrap)", 8, 12),
    ("crates/polars-python/src/functions/aggregation.rs", "let e = dsl::sum_horizontal(exprs, ignore_nulls).map_err(PyPolarsErr::from)?;", 6, 4),
    (SER, "def _arithmetic(self, other: Any, op_s: str_, op_ffi: str_) -> Self:", 0, 70),
    (SER, "def __truediv__(self, other: Any) -> Series | Expr:", 0, 28),
    (SER, "def __floordiv__(self, other: Any) -> Series | Expr:", 0, 15),
    (SER, "def __rtruediv__(self, other: Any) -> Series:", 0, 20),
    (SER, "def __rfloordiv__(self, other: Any) -> Series:", 0, 8),
    ("crates/polars-plan/src/plans/conversion/type_coercion/mod.rs", "ref ae @ AExpr::Cast { .. } => {", 0, 70),
    (FS, "pub fn should_cast_column(", 0, 130),
    (FS, "if target_dtype.is_integer() && incoming_dtype.is_integer() {", 0, 12),
    ("crates/polars-plan/src/plans/conversion/stack_opt.rs", "has_inputs: !get_input(ir_arena, current_ir_node).is_empty(),", 30, 6),
    (ASOF, "fn _join_asof(", 3, 50),
    (ASOF, "pub fn _check_asof_columns(", 0, 36),
    (ASOF, "struct AsofJoinForwardState {", 0, 64),
    ("crates/polars-ops/src/frame/join/asof/default.rs", "fn join_asof_impl<", 0, 32),
    ("crates/polars-ops/src/frame/join/asof/groups.rs", "fn _join_asof_by(", 0, 70),
    ("crates/polars-ops/src/frame/join/mod.rs", "JoinType::AsOf(options) => match (options.left_by, options.right_by) {", 2, 30),
    ("crates/polars-mem-engine/src/executors/join.rs", "let df = df_left._join_impl(", 5, 10),
    (STREAM_ASOF, "async fn compute_asof_join(", 0, 30),
    (STREAM_ASOF, "async fn prune_right_side(", 0, 42),
    ("crates/polars-ops/src/series/ops/various.rs", "fn is_sorted_impl(", 0, 75),
    ("crates/polars-core/src/datatypes/any_value.rs", "(Categorical(l_cat, l_map), Categorical(r_cat, r_map)) => unsafe {", 0, 5),
]
EXTRA = [
    'grep -rn "fn scatter" crates/polars-python/src/series/',
    'grep -rn "sum_horizontal(" crates/polars-expr/src/ crates/polars-ops/src/',
    'grep -n "def __rfloordiv__\\|def __rtruediv__\\|__rfloordiv__(" py-polars/src/polars/series/series.py',
    'grep -rn "to_physical_repr" crates/polars-ops/src/frame/join/asof/ crates/polars-stream/src/nodes/joins/asof_join.rs',
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
