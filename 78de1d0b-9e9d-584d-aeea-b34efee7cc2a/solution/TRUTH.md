# Ground truth

Repository: `pola-rs/polars`
Base commit: `5eaa75417658a55b0f248d2bedd6fe919d64feae`, the sole parent of `cc12c943627d` (PR #30310). At this commit
five separate defects are live; each was fixed later by its own upstream change:

| Operation | Fix | Issue | Merged |
|---|---|---|---|
| A | PR #30420, `621b9b7e47f0` | #21474 | 2026-10-30 |
| B | PR #30433, `a31c7ebaef77` | #21515 | 2026-10-30 |
| C | PR #30452, `0260c77513f3` | none | 2026-10-30 |
| D | PR #29231, `0b47007ab65f` | #28587 | 2026-11-02 |
| E | PR #30554, `ca27922c6afe` | #30540 | 2026-11-03 |

Language: Rust, with the Python front end in `py-polars/`.

Reproduction: the polars 2.1.0 wheel (released 2026-10-25) gives every result the instruction states, including the
harmless variants; every file the five fixes touch is unchanged between `py-2.1.0` and the base commit.

## Summary

There are five distinct root causes, one behind each operation. They are not one shared bug and they live in five
different parts of the library: the Python bindings' in-place element update (operation A), the horizontal sum kernel
together with the planned schema of its expression (operation B), the Python `Series` floor-division operator with the
number on the left (operation C), the type-coercion rule that rewrites casts while a lazy query is converted to its
plan (operation D), and the conversion of the join keys before an asof join searches them (operation E). Fixing any
one of them leaves the other four operations wrong.

| Operation | Root cause | File |
|---|---|---|
| A, `scatter` of a timestamp into a nanosecond column | `scatter` converts new values to the column's logical dtype only for categorical, enum and decimal columns; for every other column it reinterprets the values' physical integers, so a microsecond timestamp, a microsecond duration or a day count is stored as if it were in the column's own unit | `crates/polars-python/src/series/scatter.rs` |
| B, `sum_horizontal` over small integer columns | `sum_horizontal` adds the columns at their common supertype and never widens small integers the way the vertical sum does (`sum_output_dtype`); the `SumHorizontal` arm of the planned schema makes the same choice | `crates/polars-ops/src/series/ops/horizontal.rs`, `crates/polars-plan/src/plans/aexpr/function_expr/schema.rs` |
| C, `number // Series` | `Series.__rfloordiv__` computes `_arithmetic(other, "div", "div_<>_rhs")`, which is true division, and `__rtruediv__` relies on it | `py-polars/src/polars/series/series.py` |
| D, a strict struct cast in a lazy query | the `AExpr::Cast` arm of `TypeCoercionRule::optimize_expr` checks a strict cast against a `CastColumnsPolicy` that inserts missing struct fields and ignores extra ones, so `should_cast_column` accepts any field mismatch and the rule rewrites the cast as non-strict | `crates/polars-plan/src/plans/conversion/type_coercion/mod.rs` |
| E, `join_asof` on a categorical key | `_join_asof` converts both keys with `to_physical_repr()` before the search, so a `Categorical` key is searched by its category codes, which follow the order the categories were first registered in, not the order of the strings the columns are sorted and checked by; `_join_asof_by` and the streaming engine's `compute_asof_join` repeat the conversion | `crates/polars-ops/src/frame/join/asof/mod.rs`, `crates/polars-ops/src/frame/join/asof/groups.rs`, `crates/polars-stream/src/nodes/joins/asof_join.rs` |

## Cause A: an in-place update that reinterprets physical values (operation A)

**Where the wrong decision is made.** The free function `scatter(s, idx, values)` in
`crates/polars-python/src/series/scatter.rs`. It decides how to convert the new values with

- `if logical_dtype.is_categorical() || logical_dtype.is_enum()`: a strict cast to the column's logical dtype;
- `else if logical_dtype.is_decimal()`: a strict cast to the column's logical dtype;
- `else { values }`: no conversion at all.

It then takes `values.to_physical_repr().cast(&s.dtype().to_physical())`, which casts the values' physical integers to
the column's physical type without looking at either logical dtype. A Python `datetime` becomes a one-value series of
`Datetime("us")`, so its physical value is a count of microseconds; the column is `Datetime("ns")` with the same
physical `i64`, so the count is written unchanged and read back as nanoseconds, a thousand times too small:
1970-01-20 20:53:57.300. A `timedelta(seconds=1)` is a `Duration("us")` of 1,000,000, stored into a `Duration("ms")`
series as 1,000,000 milliseconds, 1000 seconds. A `date` is a `Date`, physically an `i32` count of days (19844 for
2024-05-01), cast to `i64` and read as 19844 milliseconds, 00:00:19.844. A timezone-aware nanosecond column has the
same physical layout, so it fails in the same way. The decision is based on the column's dtype class, not on whether
the value's logical dtype differs from the column's.

`scatter` is called only by `PySeries::scatter`, the method in the same file that Python's `Series.scatter` calls.

**Path.** `ts.scatter(1, value)` in `py-polars/src/polars/series/series.py` wraps the value with
`Series(values=[value])` and calls `self._s.scatter(indices._s, values._s)`, which is `PySeries::scatter`, which
calls `scatter`. `ts[1] = value` goes through `Series.__setitem__`, which calls `self.scatter(key, value)` for an
integer key. `df[0, "ts"] = value` goes through `DataFrame.__setitem__` in `py-polars/src/polars/dataframe/frame.py`,
which takes the column, assigns `s[row_selection] = value` (so `Series.__setitem__` and `scatter`), and then
replaces the column.

**Downstream.** `scatter_impl` writes the physical values into the column's physical array, and `scatter` restores
the logical dtype with `from_physical_unchecked(&logical_dtype)`, which relabels the integers without converting
them. Every later read sees the relabelled value.

**Why the variants behave.** A `Datetime("us")` column has the same unit as the value, so the reinterpretation is
exact. A `pl.Series` of the column's own dtype has the same physical unit. A `date` written into a `Date` series has
the same physical type and unit, and integer series have no logical layer. `with_columns` with `when/then/otherwise`
never calls `scatter`: the expression engine casts the literal to the column's dtype with a real temporal cast.

**Smallest repair.** Cast the new values to the column's logical dtype before taking their physical representation
whenever the column is temporal and the value's temporal dtype differs from it, as is already done for categorical,
enum and decimal columns: `needs_logical_cast = is_categorical || logical_dtype.is_decimal() ||
(logical_dtype.is_temporal() && values.dtype().is_temporal() && values.dtype() != &logical_dtype)`, followed by
`values.strict_cast(&logical_dtype)`.

## Cause B: a horizontal sum that never widens small integers (operation B)

**Where the wrong decision is made.** `sum_horizontal` in `crates/polars-ops/src/series/ops/horizontal.rs`. It adds
the non-null columns pairwise with `sum_fn`, which calls `std::ops::Add::add(acc, s)`, so the sum is computed in
the common supertype of the inputs, `Int8` for two `Int8` columns, and wraps: 1 + 127 = -128 and 100 + 100 = -56. The
only widening it does is for `Boolean`, to `IDX_DTYPE`, which is repeated inline in the one-column case and in the
early return for null columns (`match dtypes_to_supertype(...) { DataType::Boolean => IDX_DTYPE, dt => dt }`). The
vertical sum widens with `sum_output_dtype` in `crates/polars-core/src/chunked_array/ops/aggregate/mod.rs`, which maps
`Int8`, `UInt8`, `Int16` and `UInt16` to `Int64` (and `Boolean` to the index type); the horizontal sum never applies
it.

The same decision is repeated in the planned schema: the `SumHorizontal` arm of the field mapping in
`crates/polars-plan/src/plans/aexpr/function_expr/schema.rs` takes `mapper.map_to_supertype()` and widens only
`Boolean`, so `collect_schema()` reports `Int8`.

`sum_horizontal` is called by the expression dispatch in `crates/polars-expr/src/dispatch/misc.rs` (the
`SumHorizontal` function), by `mean_horizontal` in the same file, and by the `DataFrame` method of the same name in
that file.

**Path.** `pl.sum_horizontal("a", "b")` builds the expression with `plr.sum_horizontal`
(`crates/polars-python/src/functions/aggregation.rs`, `dsl::sum_horizontal`); evaluating it reaches the dispatch in
`polars-expr`, which calls `polars_ops::prelude::sum_horizontal`. `DataFrame.sum_horizontal()` and
`DataFrame.mean_horizontal()` in Python select the same expressions.

**Downstream.** `mean_horizontal` computes `sum_horizontal` and divides it by the per-row count of non-null values
as `Float64`, so it divides the wrapped sum: -128 / 2 = -64.0 and -56 / 2 = -28.0. `UInt8` 200 + 100 wraps to 44,
`Int16` 30000 + 30000 to -5536, and three `Int8` values of 100 to 44.

**Why the variants behave.** `Int64` columns do not overflow at these values. An `Int8` column added to an `Int64`
column is added in their supertype, `Int64`. `Boolean` columns are widened to the index type. `list.sum()` after
`concat_list` uses the list sum, which applies `sum_output_dtype`. `pl.fold(pl.lit(0), ...)` starts from an `Int32`
literal, so every addition happens in `Int32`.

**Smallest repair.** In `sum_horizontal`, compute the output dtype once as
`sum_output_dtype(&dtypes_to_supertype(...)?)`, cast every column to it before adding, and use it for the null-column
result; in the `SumHorizontal` schema arm, set `f.dtype = sum_output_dtype(&f.dtype)`.

## Cause C: reflected floor division implemented as true division (operation C)

**Where the wrong decision is made.** `Series.__rfloordiv__` in `py-polars/src/polars/series/series.py`, which
Python calls for `-7.5 // s` because a `float` does not know how to floor-divide by a `Series`. After rejecting
temporal dtypes it returns `self._arithmetic(other, "div", "div_<>_rhs")`, the same operation as true division with
the number as the dividend. `_arithmetic` dispatches through `get_ffi_func(op_ffi, self.dtype, self._s)`, for a
`Float64` series the scalar-on-the-left division, and returns `-7.5 / s`. For an integer series and a float number,
`_arithmetic` first turns the number into a one-value `Float64` series and calls `div` on it, again true division.
The decision is to use division instead of floor division.

The mistake is entangled with `Series.__rtruediv__` in the same file, which casts the series to `Float64` and then
returns `self.__rfloordiv__(other)`; true division with the number on the left works only because
`__rfloordiv__` divides without flooring.

**Path.** `-7.5 // s` calls `float.__floordiv__`, which returns `NotImplemented`, so Python calls
`Series.__rfloordiv__(s, -7.5)`, which calls `_arithmetic` and the native division.

**Downstream.** The native division returns the unfloored quotients, `[-3.75, 3.75, -15.0, 1.875]`.

**Why the variants behave.** For an integer number and an integer series the `div` operation is integer division,
which rounds toward negative infinity, so `-7 // pl.Series([2, -2, 3, -3])` is right. `s // -7.5` calls
`Series.__floordiv__`, which evaluates the floor-division expression `F.col(self.name) // other`.
`pl.Series([-7.5] * 4) // s` also calls `__floordiv__`, and `pl.lit(-7.5) // pl.col("s")` is the floor-division
expression itself. `-7.5 / s` is true division, which is what `__rfloordiv__` computes.

**Smallest repair.** Make `__rfloordiv__` floor-divide, for example by evaluating
`(F.lit(other) // F.col(self.name)).alias(self.name)` over `self.to_frame()` (or returning `other // self` for a
`Series`), and make `__rtruediv__` call `self._arithmetic(other, "div", "div_<>_rhs")` itself.

## Cause D: a strict cast rewritten as non-strict during plan conversion (operation D)

**Where the wrong decision is made.** The `AExpr::Cast` arm of `TypeCoercionRule::optimize_expr` in
`crates/polars-plan/src/plans/conversion/type_coercion/mod.rs`. For a strict cast (`CastOptions::Strict`) on a node
with inputs (`ctx.has_inputs`), it builds a `CastColumnsPolicy`, the policy scans use to reconcile file schemas,
with `missing_struct_fields: MissingColumnsPolicy::Insert` and `extra_struct_fields: ExtraColumnsPolicy::Ignore`,
and asks `should_cast_column("", cast_to, &cast_from)`. On `Ok(true)` it replaces the node with a cast whose options
are `CastOptions::Overflowing` for two primitive numeric dtypes and `CastOptions::NonStrict` otherwise; on `Err` it
keeps the strict cast.

`CastColumnsPolicy::should_cast_column` in `crates/polars-plan/src/dsl/file_scan/mod.rs`, for two struct dtypes,
walks the target fields: a target field the input lacks is accepted under `Insert` (`should_cast = true`), and an
input field the target lacks is accepted under `Ignore` (`should_cast = true`). Any field mismatch therefore answers
`Ok(true)` instead of an error, and the strict cast becomes non-strict. A schema-reconciliation policy is the wrong
basis for a strict cast, and ignoring extra fields is what removes the error.

**Path.** `pl.col("s").cast(dtype)` is strict by default. Converting the lazy query to its plan runs the
`ConversionOptimizer` in `crates/polars-plan/src/plans/conversion/stack_opt.rs`, which applies `TypeCoercionRule` to
every expression with `has_inputs: !get_input(...).is_empty()`, true for the select over the frame. `with_columns`,
`LazyFrame.cast` and `DataFrame.cast` (which runs lazily) build the same cast expression.

**Downstream.** The executed cast is now non-strict, and the non-strict struct cast matches fields by name, fills
`x` and `y`, which the input lacks, with nulls, and drops `b` when the target is `{"a": Int64}`.

**Why the variants behave.** The eager `Series.cast` does not go through plan conversion, so the strict struct cast
runs and raises `structs field name mismatch`. Casting to the same field names with other dtypes is a legitimate
cast either way. `strict=False` never enters the arm, and non-strict nulls are its documented result. A strict cast
of 300 to `Int8` is a narrowing integer cast, which the policy refuses (it only allows integer upcasts), so
`should_cast_column` returns `Err`, the strict cast stays, and it raises at run time.

**Smallest repair.** In the `AExpr::Cast` arm, build the policy with `extra_struct_fields: ExtraColumnsPolicy::Raise`,
so a struct with fields the target lacks makes `should_cast_column` return an error and the strict cast is kept and
raises.

## Cause E: an asof join that searches categorical keys by their codes (operation E)

**Where the wrong decision is made.** `AsofJoin::_join_asof` in `crates/polars-ops/src/frame/join/asof/mod.rs`.
After `_check_asof_columns` has validated the keys, it converts both with `to_physical_repr()` and hands the results
to `_join_asof_dispatch`. For a `Categorical` key the physical representation is its `UInt32` category code, so the
asof search compares codes, not the category strings the columns are sorted by. The same conversion is repeated
inline in two more places: `AsofJoinBy::_join_asof_by` in `crates/polars-ops/src/frame/join/asof/groups.rs`, the
`by=` join, which converts the keys before it calls `_check_asof_columns`, and `compute_asof_join` in
`crates/polars-stream/src/nodes/joins/asof_join.rs`, the streaming engine's asof node.

**What the decision is based on, and why it is wrong.** A category's code records when the category was first
registered in the session, not where it sorts. `grades` registered "e" first, so while it is alive the codes are
e=0, d=1, c=2, b=3 and a=4: `loans` holds the codes `[4, 3, 2, 1, 0]` and `bands` holds `[3, 1]`, both descending,
while the strings ascend. The asof kernels assume ascending keys. `_join_asof_dispatch` matches on the physical dtype
(`UInt32`) and calls `join_asof_numeric`, whose `join_asof_impl` (`asof/default.rs`) feeds each left key to a scan
state from `asof/mod.rs` that keeps one position in the right keys and only moves it forward. For the first loan
(code 4) `AsofJoinBackwardState::next` passes both bands, since 3 and 1 are both at most 4, and settles on the last
one, "d"; the position is then at the end, so every later loan gets "d" as well. `AsofJoinForwardState::next` looks
for the first right key at or above 4, finds none, moves past the last band, and from there returns nothing for every loan.

**Why the sortedness check passes.** `_check_asof_columns` (same file) accepts the keys because their physical dtype
is primitive, and with `check_sortedness` it calls `ensure_sorted_arg` (`crates/polars-ops/src/series/ops/various.rs`)
on the categorical series themselves. `is_sorted_impl` sends a `Categorical` to
`is_sorted_categorical_lexical_adjacent`, which compares the decoded strings, so the check confirms the A-Z order and
the search then runs on codes. `_join_asof_by` converts first and passes `by_groups_present = true`, so with `by=` the
check is skipped with a warning.

**Path.** `DataFrame.join_asof` builds the same query lazily and collects it eagerly in the in-memory engine; the
join executor in `crates/polars-mem-engine/src/executors/join.rs` calls `_join_impl` in
`crates/polars-ops/src/frame/join/mod.rs`, whose `JoinType::AsOf` arm calls `_join_asof`, or `_join_asof_by` when
`by` columns are given. `collect(engine="streaming")` runs the asof node instead, whose `compute_asof_join` converts
the keys itself.

**Downstream.** The scan states return, for each left row, a row index into `bands` or none; `_join_asof` takes
those rows from `bands` (`take_unchecked`) and `_finish_join` attaches them, so the wrong indices become the wrong
`band` values. The streaming node buffers and prunes its right input by comparing `AnyValue`s of the logical key,
which order categoricals by their strings, and joins on the codes only in `compute_asof_join`; it searches
differently from the in-memory kernel, so the same unsorted codes give a different wrong answer.

**Why the variants behave.** `pl.String` keys are compared as strings. An `Enum`'s codes follow its declared
category order, which is also the order its values sort in, so codes and sort order agree. In a session where
`grades` was never built, `loans` registers "a" to "e" in that order, so the codes happen to ascend with the
strings. Sorting by `to_physical()` orders the frames by code, which is not A-Z order, so the string-based
sortedness check raises.

**Smallest repair.** Compare categorical keys by their strings: before the search, cast a `Categorical` key to
`String` (or map it to its lexical rank) instead of taking its physical representation, in `_join_asof`,
`_join_asof_by` and `compute_asof_join`, for instance through one shared helper. `Enum` keys can keep their codes.

## Ruled out

- The five faults are independent: an in-place update in the Python bindings, a horizontal sum kernel and its
  schema, a Python operator, a plan-conversion rule, and the asof join's key conversion. Fixing one leaves the others
  wrong.
- The temporal casts and `scatter_impl` itself are correct; the fault in operation A is that `scatter` never asks for
  the cast.
- The integer addition kernels are correct (adding two `Int8` columns with `+` wraps by design); the fault in
  operation B is that the horizontal sum does not widen first, as the vertical sum does.
- The native division and floor-division kernels are correct; the fault in operation C is which one
  `__rfloordiv__` calls.
- The struct cast in `polars-core` is correct in both modes; the fault in operation D is that the plan conversion
  turns a strict cast into a non-strict one.
- The asof search kernels (`join_asof_numeric`, `join_asof_impl` and the backward and forward scan states) are correct
  for ascending keys, and the categorical sortedness check is right to compare strings; the fault in operation E is
  that categorical keys reach the kernels as codes, which do not follow that order.
