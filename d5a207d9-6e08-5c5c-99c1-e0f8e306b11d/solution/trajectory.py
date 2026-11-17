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
SEARCH = 'grep -rn "CoalesceColumns" crates/polars-plan/src/'
COMPARE = 'grep -n "process_order_by" crates/polars-sql/src/context.rs'

FC = "crates/polars-plan/src/plans/aexpr/filter_constraint.rs"
SQL = "crates/polars-sql/src/context.rs"
# (file, literal anchor or None for the whole file, lines before, lines after)
DISPLAYS = [
    (FC, "fn drops_nulls(&self) -> bool {", 0, 14),
    (FC, "fn resolve_deferred(&mut self) {", 0, 14),
    (FC, "fn model_and_chain(predicate: Node, schema: &Schema, expr_arena: &Arena<AExpr>) -> ConstraintModel {", 0, 100),
    (FC, "pub(crate) fn and_chain_bounds(", 0, 30),
    (FC, "pub(crate) fn merge_filter_constraints(", 0, 30),
    (FC, "fn classify_into_constraints(", 0, 30),
    (FC, "fn classify_negation(", 0, 45),
    (FC, "fn classify_null(", 0, 22),
    ("crates/polars-plan/src/plans/optimizer/filter_constraint.rs", None, 0, 0),
    ("crates/polars-plan/src/plans/optimizer/mod.rs", "rules.push(Box::new(filter_constraint::FilterConstraintRule {", 6, 8),
    ("crates/polars-plan/src/plans/optimizer/mod.rs", "simplify_ordering::simplify_and_fetch_orderings(&roots, ir_arena, expr_arena);", 14, 4),
    ("crates/polars-plan/src/plans/optimizer/simplify_expr/mod.rs", "impl OptimizationRule for SimplifyBooleanRule {", 0, 30),
    ("crates/polars-plan/src/plans/optimizer/predicate_pushdown/join/asof.rs", "let bounds = and_chain_bounds(branch, schema_left, expr_arena);", 12, 4),
    ("crates/polars-plan/src/plans/stats/node.rs", "let chain = and_chain_bounds(predicate, schema, expr_arena);", 8, 4),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs", "pub fn simplify_projected_exprs(", 0, 30),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs", "AExpr::Column(_) => O::COLUMN,", 0, 8),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs", "AExpr::BinaryExpr { .. } | AExpr::Ternary { .. } => {", 0, 50),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/mod.rs", "pub fn simplify_and_fetch_orderings(", 0, 30),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/mod.rs", "IR::Select { .. } | IR::HStack { .. } => {", 0, 75),
    ("crates/polars-plan/src/plans/optimizer/simplify_ordering/mod.rs", "fn unlink_node(&mut self, current_ir_node: Node, input_to_current_ir_node: Node) -> bool {", 0, 12),
    ("crates/polars-plan/src/plans/conversion/dsl_to_ir/join.rs", "fn resolve_join_where(", 0, 40),
    ("crates/polars-plan/src/plans/conversion/dsl_to_ir/join.rs", "new_options.options = JoinTypeOptionsIR::CrossAndFilter { predicate };", 12, 4),
    ("crates/polars-plan/src/plans/optimizer/predicate_pushdown/join/predicate_pruning.rs", "let is_outer_non_equi = matches!(", 0, 30),
    ("crates/polars-plan/src/plans/optimizer/predicate_pushdown/join/predicate_pruning.rs", "fn try_rewrite_outer_iejoin(", 0, 65),
    ("crates/polars-plan/src/plans/options.rs", "pub fn left_on(&self) -> Exprs<'_> {", 0, 22),
    ("crates/polars-plan/src/plans/optimizer/projection_pushdown/mod.rs", "Arc::make_mut(options).args.coalesce = JoinCoalesce::CoalesceColumns;", 30, 25),
    ("crates/polars-plan/src/plans/schema.rs", "pub(crate) fn det_join_schema(", 0, 22),
    ("crates/polars-plan/src/plans/schema.rs", "pub(crate) fn join_right_output_names(", 0, 75),
    ("crates/polars-ops/src/frame/join/mod.rs", "if let Some(JoinTypeOptions::IEJoin(ie_options)) = options {", 0, 28),
    ("crates/polars-ops/src/frame/join/iejoin/mod.rs", "pub(super) fn iejoin(", 0, 70),
    ("crates/polars-stream/src/physical_plan/lower_ir.rs", "let match_condition_supported =", 0, 10),
    ("crates/polars-stream/src/physical_plan/lower_ir.rs", "PhysNodeKind::InMemoryJoin {", 6, 6),
    ("crates/polars-stream/src/physical_plan/lower_expr.rs", "fn build_select_stream_with_ctx(", 0, 40),
    ("crates/polars-stream/src/nodes/simple_projection.rs", None, 0, 0),
    ("crates/polars-expr/src/expressions/column.rs", "fn process_by_idx(", 0, 20),
    (SQL, "pub fn execute(&mut self, query: &str) -> PolarsResult<LazyFrame> {", 0, 20),
    (SQL, "pub(crate) fn execute_query(&mut self, query: &Query) -> PolarsResult<LazyFrame> {", 0, 8),
    (SQL, "fn process_query(&mut self, expr: &SetExpr, query: &Query) -> PolarsResult<LazyFrame> {", 0, 60),
    (SQL, "fn process_values<'a>(", 0, 30),
    (SQL, "fn process_except_intersect(", 0, 75),
    (SQL, "fn process_union(", 0, 60),
    (SQL, "fn execute_select(&mut self, select_stmt: &Select, query: &Query) -> PolarsResult<LazyFrame> {", 0, 14),
    (SQL, "lf = self.process_order_by(lf, &query.order_by, Some(&final_cols[..n_selected]))?;", 4, 2),
]
EXTRA = [
    'grep -n "resolve_deferred" crates/polars-plan/src/plans/aexpr/filter_constraint.rs',
    'grep -rn "and_chain_bounds\\|merge_filter_constraints(" crates/polars-plan/src/',
    'grep -n "fn rec(" crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs',
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
