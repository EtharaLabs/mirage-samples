# Ground truth

Repository: `pola-rs/polars`
Base commit: `5eaa75417658a55b0f248d2bedd6fe919d64feae`, the sole parent of `cc12c943627d` (PR #30310). At this commit
four separate defects are live; each was fixed later by its own upstream change:

| Query | Fix | Issue | Merged |
|---|---|---|---|
| A | PR #30310, `cc12c943627d` | none | 2026-10-26 |
| B | PR #30315, `ffb83ddceada` | #30299 | 2026-10-26 |
| C | PR #30525, `efe925ae9d69` | #30519 | 2026-11-03 |
| D | PR #30468, `f1e093dae99c` | none | 2026-11-01 |

Language: Rust, with the Python front end in `py-polars/`.

Reproduction: the polars 2.1.0 wheel (released 2026-10-25) gives every result the instruction states, including the
harmless variants (45 claims checked); the four commits between `py-2.1.0` and the base commit touch none of the files
involved.

## Summary

There are four distinct root causes, one behind each query. They are not one shared bug and they live in four
different parts of the query engine: an expression-level filter rewrite (query A), the optimizer pass that removes
row orders nobody observes (query B), projection pushdown together with the planned join schema (query C), and the
SQL front end (query D). Three of them are optimizer decisions, which is why `QueryOptFlags.none()` repairs queries
A, B and C; query D is a translation fault and no optimizer setting changes it.

| Query | Root cause | File |
|---|---|---|
| A, `is_null() & ~is_in([1], nulls_equal=True)` | `classify_negation` records the negated membership's haystack as disallowed values without looking at `nulls_equal`, and `ColumnConstraints::resolve_deferred` then declares "missing and constrained to a value" impossible, so the filter becomes `false` | `crates/polars-plan/src/plans/aexpr/filter_constraint.rs` |
| B, a `when/then/otherwise` with literal branches after a sort | the `BinaryExpr`/`Ternary` arm of `ExprOrderSimplifier::rec` reports the orders of the two branches only, taken before the predicate is added, so a ternary with literal branches reports no observable order and the sort below it is removed | `crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs` |
| C, a left `join_where` | the join arm of `ProjectionPushdownVisitor::pushdown` turns on key coalescing for any inner or left join whose right keys are not projected, including the inequality join a left `join_where` becomes; the planned schema then drops the right operand `y` while the inequality join still emits it | `crates/polars-plan/src/plans/optimizer/projection_pushdown/mod.rs` |
| D, `VALUES ... ORDER BY` | the `SetExpr::Values` arm of `SQLContext::process_query` builds the rows and never applies the query's `ORDER BY`, while every other arm does | `crates/polars-sql/src/context.rs` |

Fixing any one of them leaves the other three queries wrong: none of the four code paths reaches another's routine.

## Cause A: an impossible-filter verdict for `is_null() & ~is_in(..., nulls_equal=True)` (query A)

**Where the wrong decision is made.** The filter-constraint model in
`crates/polars-plan/src/plans/aexpr/filter_constraint.rs`. It folds each conjunct of an `AND` chain into a
per-column `ColumnConstraints` (bounds, `!=` values, the `is_in` set `allowed`, the negated-`is_in` set
`disallowed`, a required `nullability`, and an `unsat` flag) and then decides whether the chain can hold at all. Two
routines in that file make the wrong decision together:

- `classify_negation`, the arm that handles a `!` over `is_in`, matches
  `IRFunctionExpr::Boolean(IRBooleanFunction::IsIn { .. })` and ignores the `nulls_equal` field. For a plain column
  and a literal, null-free haystack (`as_column`, `as_value_set`) it records the haystack with
  `ColumnConstraints::add_disallowed` and keeps the conjunct as `Opaque`.
- `ColumnConstraints::resolve_deferred` starts with
  `if self.nullability == Nullability::Null && self.has_value_constraint() { self.unsat = true; return; }`, and
  `has_value_constraint()` is `drops_nulls() || !self.disallowed.is_empty()`. So the negated membership counts as a
  value constraint. The check rests on the assumption that every value constraint drops missing values, which is true
  for bounds, `!=` and `is_in`, and for `!is_in` only without `nulls_equal`. `drops_nulls()` itself leaves `!is_in`
  out because with `nulls_equal` it keeps missing values, but `has_value_constraint()` adds it back for exactly the
  check where that matters.

With `nulls_equal=True` a missing value is compared as a value, so it is not a member of the null-free haystack `[1]`:
`is_in` is false, not missing, and `~is_in` is true. The missing row satisfies both conjuncts. The model instead
records `nullability == Null` from `is_null()` (`classify_null`, via `require_nullability`) and `disallowed == {1}`
from the negation, and `resolve_deferred` marks the column impossible.

`resolve_deferred` is a helper. Its only caller is `model_and_chain` in the same file, which calls it on every
column's constraints in stage 3 (`constraints.values_mut().any(|cc| { cc.resolve_deferred(); cc.unsat })`) and once
more on the unpropagated copy. `model_and_chain` is called by `merge_filter_constraints` and by `and_chain_bounds`.

**Path.** `LazyFrame.filter` (and `DataFrame.filter`, which runs `self.lazy().filter(...)` and collects eagerly) puts
an `IR::Filter` in the plan. `optimize` in `crates/polars-plan/src/plans/optimizer/mod.rs` registers, under
`opt_flags.simplify_expr()`, `FilterConstraintRule` (`crates/polars-plan/src/plans/optimizer/filter_constraint.rs`)
and right after it `SimplifyBooleanRule`. `FilterConstraintRule::optimize_plan` matches `IR::Filter` only and calls
`merge_filter_constraints(predicate, schema, maintain_errors, ...)`, which calls `model_and_chain`. `model_and_chain`
walks the `AND` chain with `MintermIter` and classifies each conjunct with `classify_into_constraints`; its
`IRBooleanFunction::Not` arm calls `classify_negation`, and the `is_null` conjunct goes to `classify_null`.

**Downstream.** `merge_filter_constraints` sees `unsat` and, unless the predicate must keep its errors
(`ExprPushdownGroup::blocks_pushdown(maintain_errors)`, not the case for a column test), returns `Literal(false)`.
`FilterConstraintRule::optimize_plan` puts that predicate into the filter, and `SimplifyBooleanRule::optimize_plan`
replaces a filter whose predicate is the literal `false` with an empty `IR::DataFrameScan`
(`DataFrame::empty_with_schema`). The query therefore never evaluates the mask and returns no rows. The other users of
the model inherit the same verdict: `and_chain_bounds` feeds `key_intervals` in
`crates/polars-plan/src/plans/optimizer/predicate_pushdown/join/asof.rs`, which skips an `unsat` branch, and
`predicate_selectivity` in `crates/polars-plan/src/plans/stats/node.rs`, which estimates zero rows for it.

**Why the variants behave.**

- The mask computed with `with_columns` is right because the rule rewrites `IR::Filter` predicates only; the
  expression itself is evaluated correctly.
- `QueryOptFlags.none()` turns off `simplify_expr`, so neither rule is registered.
- The eager `DataFrame.filter`, the streaming engine, swapped conditions and two chained filters are all wrong
  because they all reach the same optimized plan: eager filtering goes through the lazy optimizer, the streaming
  engine runs the optimized plan, `resolve_deferred` runs after every conjunct is collected so order does not matter,
  and predicate pushdown merges chained filters into one `AND` chain.
- `~is_in([1], nulls_equal=True)` alone records a disallowed set but no `is_null` requirement, and the disallowed set
  is used only to detect contradictions and is never emitted, so the filter is left as written.
- `|` is not split by `MintermIter`, which walks `AND` chains only, so the whole disjunction is one opaque conjunct.
- `ne_missing(1)` is a null-preserving comparison (`NotEqValidity`) that the model keeps opaque on purpose.
- With `nulls_equal=False` the same `false` verdict is produced, but there it is correct: `~is_in` on a missing value
  is missing, and the filter drops the row anyway.
- A haystack that contains `None` is refused by `as_value_set` (literal, null-free haystacks only), so nothing is
  recorded and the filter runs as written; the empty result is then the true answer, because with `nulls_equal=True`
  a missing value is a member of `[1, None]`.

**Smallest repair.** In `classify_negation`, bind the flag (`IsIn { nulls_equal, .. }`) and record the haystack only
when `nulls_equal` is false; make the `Null` check in `resolve_deferred` use `drops_nulls()`, extended with
`!self.disallowed.is_empty()`, and remove `has_value_constraint`. A negated membership with `nulls_equal` then no
longer counts as a constraint that excludes missing values.

## Cause B: an order simplifier that loses the predicate's order (query B)

**Where the wrong decision is made.** `ExprOrderSimplifier::rec` in
`crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs`, in the arm
`AExpr::BinaryExpr { .. } | AExpr::Ternary { .. }`. `rec` returns the `ObservableOrders` of an expression: `COLUMN`
when the row order of an input column can be seen in the result, `INDEPENDENT` for an order the expression creates
itself, empty when no input order can be seen. A literal returns empty, a column returns `COLUMN`.

For a ternary the arm takes `nodes = [truthy, falsy]` and keeps the predicate aside as `ternary_mask_node`. It adds
`rec(truthy)` and `rec(falsy)` to an `ExprOrderAcc`, then computes `let mut output_observable =
acc.accumulated_orders();`, and only after that adds `rec(predicate)` to the accumulator. The value it returns is the
branches' orders alone. With literal branches, `then(1).otherwise(0)`, that is empty, although the predicate
`col("x") > 1` places a value in every row in the order of `x`: the output's row order is the input's row order. The
same arm repeats the mistake in its `ALLOW_DEORDER` branch: when the predicate is the single ordered input
(`acc.single_ordered_node()`), it sets `output_observable = O::empty()` (`if Some(node) == ternary_mask_node`).

**Path.** `LazyFrame.sort("x")` and `.select(...)` give an `IR::Sort` under an `IR::Select`, and
`pl.when(...).then(1).otherwise(0)` becomes `AExpr::Ternary`. `optimize` in
`crates/polars-plan/src/plans/optimizer/mod.rs` runs `simplify_and_fetch_orderings` (in
`crates/polars-plan/src/plans/optimizer/simplify_ordering/mod.rs`) when `OptFlags::CHECK_ORDER_OBSERVE` is set. It
builds the graph of plan nodes and the edges between them, and `SimplifyIRNodeOrder::simplify_ir_node_orders`
visits each node. Its `IR::Select | IR::HStack` arm calls `ExprOrderSimplifier::simplify_projected_exprs` on the
projected expressions, which calls `rec(node, RecursionState::NO_DEORDER)` for each.

**Downstream.** The `Select` arm computes `input_order_observe = ((COLUMN || is_hstack) && !out_edge.is_unordered())
|| (is_hstack && INDEPENDENT) || internally observed COLUMN`. With nothing reported, that is false and it sets the
input edge to `Edge::Unordered`. The `IR::Sort` arm of the same routine then sees `out_edge.is_unordered() &&
slice.is_none()` and removes the sort with `unlink_node`. The optimized plan has no `SORT`, and the flag is computed
in the original row order `[5, 1, 4, 2, 3]`, giving `[1, 0, 1, 1, 1]`. `cum_sum()` observes the order of its input,
but its input is the ternary, which reports no order, so nothing is observed and the sort is removed the same way,
giving `[1, 1, 2, 3, 4]`. String literals behave like integer literals.

**Why the variants behave.**

- `QueryOptFlags.none()` clears `CHECK_ORDER_OBSERVE`, so the pass does not run.
- On an eager `DataFrame` the sort has already run when the frame was collected, so there is no sort left to remove.
- `then(pl.col("x"))` makes a branch return `COLUMN`, which is in `output_observable` before the predicate matters.
- `pl.col("x") > 1` is a `BinaryExpr`: its two operands are the nodes, and the column operand gives `COLUMN`.
- `with_columns` is an `IR::HStack` that keeps the input columns, so `is_hstack` is true and the input order counts as
  observed.
- Selecting `x` next to the flag adds a plain column, which gives `COLUMN` for the projection.
- `.head(3)` after the `select` is pushed into the sort by slice pushdown (the plan shows `SORT BY [slice: (0, 3)]`),
  so the `IR::Sort` arm sees `slice.is_some()` and keeps the sort.
- The streaming engine runs the same optimized plan, so it is wrong too.

**Smallest repair.** Chain the predicate into the nodes before the accumulated orders are read
(`for node in nodes.into_iter().chain(predicate)`), so `output_observable` includes the predicate's order, and drop
both `ternary_mask_node` special cases.

## Cause C: coalescing turned on for an inequality join (query C)

**Where the wrong decision is made.** The `IR::Join` arm of `ProjectionPushdownVisitor::pushdown` in
`crates/polars-plan/src/plans/optimizer/projection_pushdown/mod.rs`. To avoid materializing a right key nobody reads,
it switches the join to `JoinCoalesce::CoalesceColumns` when all of these hold: the join does not coalesce already
(`!options.args.should_coalesce()`), `how` is `JoinType::Inner` or `JoinType::Left`, every `left_on` and `right_on`
expression is a plain column, and no right key is projected in the output or read by a predicate. It does not check
that the join is an equi join. Coalescing merges a right key into the left key only when they are equal; for an
inequality join `x >= y` the two keys hold different values and `y` is real data.

A left `join_where` reaches that arm as an inequality join. `resolve_join_where` in
`crates/polars-plan/src/plans/conversion/dsl_to_ir/join.rs` keeps a non-inner `join_where` as a left join with
`JoinTypeOptionsIR::CrossAndFilter { predicate }` and coalescing off. Predicate pushdown's `try_rewrite_join_type` in
`crates/polars-plan/src/plans/optimizer/predicate_pushdown/join/predicate_pruning.rs` treats it as an outer non-equi
join and, through `try_rewrite_outer_iejoin`, rewrites the options to `JoinTypeOptionsIR::IEJoin { left_on: [x],
right_on: [y], .. }` while `how` stays `Left`. `JoinTypeOptionsIR::left_on()` and `right_on()` (in
`crates/polars-plan/src/plans/options.rs`) return those inequality operands, so in the query
`select("x", "k_right")` the "right key" `y` is not projected, and the arm sets `CoalesceColumns`.

**What the decision breaks.** The arm then recomputes the join's schema with `det_join_schema`
(`crates/polars-plan/src/plans/schema.rs`) and stores it as the join's output schema. With coalescing on,
`join_right_output_names` in that file drops every right-key column, treating it as "coalesced into an already added
left column". It keeps a right key only for asof joins, and has no case for inequality joins. So the planned output is
`[x, k]`, with the right `k` unsuffixed because the left `k` is no longer projected, and the select above reads
`col("k").alias("k_right")`. The join that actually runs never coalesces: `DataFrame::_join_impl` in
`crates/polars-ops/src/frame/join/mod.rs` sends `JoinTypeOptions::IEJoin` to `iejoin::iejoin` or `iejoin::iejoin_par`
(`crates/polars-ops/src/frame/join/iejoin/mod.rs`) before any of the key-dropping logic used for equi joins, and
`_finish_join` returns every right column. The physical result is `[x, y, k]`, one column more than planned, with
`y` where the plan expects `k`.

**Downstream.** Every step planned against the join's schema now disagrees with the data.

- On the streaming engine, which the default `collect()` uses here, `lower_ir` sends a left inequality join to the
  in-memory join through `PhysNodeKind::InMemoryJoin`: `match_condition_supported` is false because the join is
  neither a pure equi join, nor a fused predicate, nor a range join. The select above it is lowered by
  `build_select_stream_with_ctx` in `crates/polars-stream/src/physical_plan/lower_expr.rs`. For a selection of plain
  columns, with or without renames, it either passes the input through when the names already match, or builds a
  `PhysNodeKind::SimpleProjection`. `SimpleProjectionNode::new` in `crates/polars-stream/src/nodes/simple_projection.rs`
  turns each selected name into a position with `input_schema.index_of(&col)` on the planned schema, and at run time
  takes `df.columns()[idx]`, checking the name only with `debug_assert_eq!`. So `k` at planned position 1 picks the
  physical `y`, which `select("x", "k_right")` renames to `k_right`, giving `[0, 0]`. In `select("k", "k_right")`
  the left `k` is projected, so the right `k` is suffixed `k_right` at planned position 1, where the physical column
  is `y`; nothing is renamed, so it comes out under its own name `y`.
- When the planned output already equals the requested columns, no select is left in the plan at all. For
  `select("x")` the planned join output is `[x]` (the right side keeps only the key `y`, which the plan believes is
  coalesced away), so the physical `[x, y]` is returned as is, on both engines.
- The in-memory engine evaluates its select through `ColumnExpr`
  (`crates/polars-expr/src/expressions/column.rs`). That looks a column up by its planned position but falls back to
  a lookup by name when the name differs, so `select("x", "k_right")` is right there, while `select("x")`, which
  has no select, still shows the extra `y`.

**Why the variants behave.**

- The full `j.collect()` and `select("x", "y", "k_right")` project `y`, so the arm does not coalesce.
- `how="inner"`: `resolve_join_where` turns an inner `join_where` into a cross join with a filter, which predicate
  pushdown rewrites into `JoinType::IEJoin`, or `JoinType::Range` on the streaming engine. Neither is `Inner` or
  `Left`, so the arm skips it.
- `QueryOptFlags.none()` turns off projection pushdown, so coalescing is never switched on.

**Smallest repair.** Add `matches!(options.options, JoinTypeOptionsIR::Equi { .. })` to the arm's condition, so
coalescing is turned on only for equi joins, where the right key equals the left key.

## Cause D: `ORDER BY` dropped for a bare `VALUES` body (query D)

**Where the wrong decision is made.** `SQLContext::process_query` in `crates/polars-sql/src/context.rs`. It
dispatches on the query body (`SetExpr`), and each arm is responsible for applying the query's `ORDER BY`. The
`SetExpr::Values` arm only calls `self.process_values(rows...)`, which turns the literal rows into a frame with
columns `column_0`, `column_1`, and returns it. It never calls `self.process_order_by(lf, &query.order_by, None)`,
so the parsed `ORDER BY 1` or `ORDER BY column_1 DESC` is ignored. Every other arm applies it:

- `SetExpr::Select` goes through `execute_select` to `execute_select_block`, which calls `process_order_by`;
- `SetExpr::Query`, the parenthesized body, calls `process_order_by` after `execute_query` on the nested query;
- `process_union` (`UNION`) and `process_except_intersect` (`EXCEPT`, `INTERSECT`) call it after combining.

**Path.** `pl.SQLContext().execute(query, eager=True)` and `pl.sql(...)` call the Rust `SQLContext::execute`, which
parses the statement and executes it. A `Statement::Query` goes to `SQLContext::execute_query`, which registers the
CTEs, validates the query, calls `process_query(&query.body, query)`, and then
`process_limit_offset(lf, &query.limit_clause, &query.fetch)`.

**Why the variants behave.** `LIMIT` and `OFFSET` are applied by `execute_query` after `process_query` for every body,
so `ORDER BY 1 LIMIT 2` keeps the first two rows as written and `LIMIT 2 OFFSET 1` is right. The subquery form is a
`SELECT`, the parenthesized form is a `SetExpr::Query`, and `UNION ALL` goes through `process_union`; all three apply
`ORDER BY`. `QueryOptFlags.none()` changes nothing, because the sort is never put in the plan; this is not an
optimizer decision.

**Smallest repair.** In the `SetExpr::Values` arm, keep the frame from `process_values` and return
`self.process_order_by(lf, &query.order_by, None)`, as the `SetExpr::Query` arm does.

## Ruled out

- The expression evaluation of `is_null`, `is_in` with `nulls_equal`, `not` and `when/then/otherwise` is correct: the
  masks and flags computed outside a filter or without the optimizer are right. Queries A and B are plan rewrites.
- The inequality join kernel is correct; it returns the right rows and values. The fault in query C is that the
  planner believes the right operand column has been coalesced away.
- The streaming and in-memory engines are not separate causes: they run the same optimized plans, and in query C the
  in-memory engine only hides one symptom because its column lookup falls back to names.
- Query D is not related to the other three: it happens before any optimizer runs, and no optimizer setting changes
  it.
