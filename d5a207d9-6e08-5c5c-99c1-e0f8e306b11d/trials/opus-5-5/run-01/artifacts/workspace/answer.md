# Analysis of the four silently-wrong lazy queries (work in progress)

Preliminary finding: four independent root causes, one per query.

- A: `ColumnConstraints::resolve_deferred` / `has_value_constraint` in `crates/polars-plan/src/plans/aexpr/filter_constraint.rs` treats a negated `is_in` ("disallowed" set) as null-excluding even when `nulls_equal=True`; `is_null() & ~is_in(..)` is folded to `false`.
- B: `ExprOrderSimplifier::rec` (Ternary arm) in `crates/polars-plan/src/plans/optimizer/simplify_ordering/expr.rs` snapshots the output ordering before adding the `when` mask's ordering; the `Sort` upstream is deleted.
- C: projection pushdown `IR::Join` arm in `crates/polars-plan/src/plans/optimizer/projection_pushdown/mod.rs` flips `coalesce` to `CoalesceColumns` for a join that has been rewritten to an IEJoin (inequality keys).
- D: `SQLContext::process_query` (`SetExpr::Values` arm) in `crates/polars-sql/src/context.rs` never calls `process_order_by`.

(Details being filled in.)
