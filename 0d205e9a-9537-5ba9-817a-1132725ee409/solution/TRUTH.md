# Ground truth

Repository: `pola-rs/polars`
Base commit: `3a8b583f8b341fe25dd1f4c31487ca3b1da73126`, the sole parent of `9cfb74722853` (PR #30427). At this commit
five separate defects are live; each was fixed later by its own upstream change:

| Pipeline | Fix | Issue | Merged |
|---|---|---|---|
| A | PR #30431, `ad25ea47fcd3` | #30428 | 2026-10-30 |
| B | PR #30427, `9cfb74722853` | #30426 | 2026-10-29 |
| C | PR #30439, `4cf4fa120d48` | #30432 | 2026-10-30 |
| D | PR #30461, `22c1bb73b192` | #30326 | 2026-10-30 |
| E | PR #30434, `e1849960acc0` | #30076 | 2026-10-29 |

PR #30377 (`26b1d58521ec`, merged 2026-10-29 before the base) changed sorted markers on append and is present at the
base as a decoy. Language: Rust, with the Python front end in `py-polars/`.

Reproduction: the polars 2.1.0 wheel (released 2026-10-25) gives every result the instruction states, including the
harmless variants; the routines involved are unchanged between `py-2.1.0` and the base commit.

## Summary

There are five distinct root causes, one behind each pipeline. They are not one shared bug. In pipelines A to D the
fetched or aggregated values and their validity are correct; what is wrong is the sorted marker (`IsSorted`, kept in
the column's statistics flags and stored with `set_sorted_flag`) that the result carries. Each pipeline reaches a
different routine that marks a result as sorted ascending although its missing entries are not all at one end, or
although its values are not in order. The routines that later trust the marker then give the wrong answers.
Pipeline E is different: its key really is sorted and its marker is true, but the sorted-merge join that the marker
selects compares keys with IEEE operators, under which NaN never matches, while the hash join treats NaN as equal.

| Pipeline | Root cause | File |
|---|---|---|
| A, the lookup | `_update_gather_sorted_flag` decides the gather's marker from the two input markers only | `crates/polars-core/src/chunked_array/ops/gather.rs` |
| B, rolling `first`/`min` with empty windows | `agg_first` (and the same copy in `agg_first_non_null` and `agg_last_non_null`) copies the input's marker without regard to the missing entries empty groups insert | `crates/polars-core/src/frame/group_by/aggregations/dispatch.rs` |
| C, per-window `slice` then `first` | `GroupsType::is_sorted_by_first_idx` answers true for every slice group set, so `agg_first` copies the marker onto values that step back | `crates/polars-core/src/frame/group_by/position.rs` |
| D, a constant column aggregated with empty groups | `Column::agg_with_scalar_identity` materializes the constant, which is marked sorted, then adds missing entries for empty groups and keeps the marker | `crates/polars-core/src/frame/column/mod.rs` |
| E, a join on a sorted float key | the sorted-merge kernels `sorted_join::inner::join` and `sorted_join::left::join` compare with `PartialOrd`, so NaN never matches, unlike the hash join | `crates/polars-arrow/src/legacy/kernels/sorted_join/inner.rs`, `left.rs` |

Fixing any one of them leaves the other pipelines wrong: the gather fix never runs in an aggregation, an
empty-group check in `agg_first` does not catch pipeline C (it has no missing entries) or pipeline D (its marker comes
from materializing the constant, not from `Series::agg_first`), and the slice-order fix does not catch pipeline B (its
windows really are ordered); none of the four marker repairs touches pipeline E, whose marker is true.

## The routines that trust the marker (shared by pipelines A to D)

Each consumer assumes that a column marked sorted holds all its missing entries together at one end, and that its
values are in order, and checks at most one element.

- **Largest and smallest value.** `ChunkAgg::max` and `ChunkAgg::min` in
  `crates/polars-core/src/chunked_array/ops/aggregate/mod.rs` take their sorted branch: for an ascending column `max`
  reads the element at `last_non_null()` and `min` the element at `first_non_null()`. `ChunkedArray::last_non_null`
  and `ChunkedArray::first_non_null` in `crates/polars-core/src/chunked_array/mod.rs` have a shortcut for sorted
  columns: they look only at element 0; if it is present they assume every missing entry is at the end, so
  `last_non_null` returns `len - null_count - 1`. For `[2, None, 4, None]` and `[5, None, 5, None]` that is index 1, a
  missing entry, so `max` returns missing; `min` reads index 0 and happens to be right. For `[None, 1, None]`
  element 0 is missing, so both shortcuts pick index 2, missing, and both `max` and `min` return missing. (In a build
  with debug assertions the shortcut's `debug_assert!` "incorrect sorted flag" fires instead.) The free function
  `first_non_null` in `crates/polars-core/src/utils/mod.rs` scans the validity and is not the one used here.
- **Distinct count.** `ChunkUnique::n_unique` and `ChunkUnique::unique` in
  `crates/polars-core/src/chunked_array/ops/unique/mod.rs` take their sorted arm and count, or keep the first of,
  each run of consecutive equal values, treating missing as a value. `[2, None, 4, None]`, `[1, 2, 1, 3, 3]` and
  `[5, None, 5, None]` have 4 runs each and `[None, 1, None]` has 3, so every `n_unique` is one or two too high.
- **Sorting.** The `sort_with_fast_path!` macro in `crates/polars-core/src/chunked_array/ops/sort/mod.rs` returns the
  column unchanged when it is marked sorted in the requested order (for a column with missing values it checks one end
  element). `[1, 2, 1, 3, 3]` has no missing values and is marked ascending, so `sort()` returns it as is; for
  `[None, 1, None]` both ends are missing and it also comes back unchanged.
- **Grouping.** For a numeric key column marked sorted, `group_tuples` in
  `crates/polars-core/src/frame/group_by/into_groups.rs` goes to `create_groups_from_sorted`, which takes
  `nulls_first = arr.get(0).is_none()`, sets the `null_count` rows aside at that end, and splits the rest into runs
  with `partition_to_groups` in `crates/polars-arrow/src/legacy/kernels/sort_partition.rs`; each group is labelled
  by its first row. With `[2, None, 4, None]` the missing rows are taken to be the last two, rows 2 and 3, so the row
  with key 4 heads a group that also holds the missing row 3: key 4 is counted twice and the missing key once. With
  `[1, 2, 1, 3, 3]` the runs are `[1] [2] [1] [3, 3]`, so key 1 appears as two groups. With `[5, None, 5, None]` the
  raw value under each missing entry is the materialized constant 5, so rows 0 and 1 form one run labelled 5 and
  rows 2 and 3 form the "missing" group, labelled 5 by its first row: two groups labelled 5 and no missing group.

None of these routines is at fault: each is handed a column whose marker lies.

## Cause A: the lookup (pipeline A)

**Routine.** `_update_gather_sorted_flag` in `crates/polars-core/src/chunked_array/ops/gather.rs`:

```rust
pub fn _update_gather_sorted_flag(sorted_arr: IsSorted, sorted_idx: IsSorted) -> IsSorted {
    use crate::series::IsSorted::*;
    match (sorted_arr, sorted_idx) {
        (_, Not) => Not,
        (Not, _) => Not,
        (Ascending, Ascending) => Ascending,
        (Ascending, Descending) => Descending,
        (Descending, Ascending) => Descending,
        (Descending, Descending) => Ascending,
    }
}
```

It calls nothing; its body is one `match` over the indexed column's marker and the positions' marker. It never looks
at the gathered result, the validity of either input, the null counts, or where any missing entry lands.

**Why it is wrong here.** The keys are ascending with missing keys first and the positions ascending with missing
positions last, so both markers are ascending and the result is marked ascending. But the smallest positions point at
the missing keys, which come out at the front, and the missing positions (nulls in the position column's validity)
come out at the back: `[None, 1, None]`. A sorted marker cannot describe missing entries at both ends. With only one
of the two inputs carrying missing entries they all land together at one end, which the consumers handle, so the
team's harmless cases are harmless.

**Path.** `keys[positions]` goes through `Series.__getitem__` in `py-polars/src/polars/series/series.py` to
`get_series_item_by_key` in `py-polars/src/polars/_utils/getitem.py`, which calls `_convert_series_to_indices` and
`_select_elements_by_index`, then `PySeries::gather_with_series` in `crates/polars-python/src/series/general.rs`,
which passes the positions as an `IdxCa`. `SeriesTrait::take` (from `impl_dyn_series!` in
`crates/polars-core/src/series/implementations/mod.rs`) calls `ChunkTake<IdxCa>::take` in `gather.rs`, which bounds
checks the present positions and calls `ChunkTakeUnchecked<IdxCa>::take_unchecked`; that builds the result, calls
`_update_gather_sorted_flag(ca.is_sorted_flag(), indices.is_sorted_flag())`, and stores the answer with
`set_sorted_flag`.

**Why only unsigned positions.** `_convert_series_to_indices` returns positions that already have the index type
(`UInt32`) unchanged, marker included, and casts any other integer type. `cast_impl` in
`crates/polars-core/src/chunked_array/cast.rs` puts the marker back only for casts to a signed type, unsigned to
unsigned, or no physical change; `Int64` to `UInt32` is none of these, so signed positions arrive unmarked and the
`(_, Not) => Not` arm returns `Not`.

**Every call.** In `gather.rs` it is called by the five `ChunkTakeUnchecked<IdxCa>` implementations: for
`ChunkedArray<T>`, `BinaryChunked`, `StringChunked`, `ArrayChunked` and `ListChunked`. Outside that file it is called
twice, both in `crates/polars-ops/src/chunked_array/gather/chunked.rs`: in `take_chunked_unchecked` (the
`TakeChunked` implementation for `ChunkedArray<T>`) and in the free function `take_chunked_unchecked_binview`.

**Look-alikes.** The plain-position implementation `ChunkTakeUnchecked<I> for ChunkedArray<T>` with
`I: AsRef<[IdxSize]>` builds its result with `from_chunk_iter_like` (`crates/polars-core/src/chunked_array/from.rs`),
which carries no flags, and never sets a marker. The imported kernel `polars_compute::gather::take_unchecked` in
`crates/polars-compute/src/gather/mod.rs` works on arrow arrays, which have no sorted marker, copies values and
validity correctly, and is not even called for integer keys. Trait resolution on `&IdxCa` picks the `IdxCa`
implementation.

**Repair.** At the decision: when both inputs have missing entries, keep the combined marker only if the result's
missing entries are all at its start or all at its end, otherwise return `Not`.

## Cause B: rolling `first` / `min` with empty windows (pipeline B)

**Routine.** `Series::agg_first` in `crates/polars-core/src/frame/group_by/aggregations/dispatch.rs`. It gathers the
first row of each group, with `None` as the index of an empty group (`if len == 0 { None } else { Some(first) }`), so
an empty window becomes a missing entry wherever it falls. Then:

```rust
        if groups.is_sorted_by_first_idx() {
            out.set_sorted_flag(s.is_sorted_flag())
        }
```

It copies the input column's marker whenever the groups are ordered by their first row, and never asks where the
missing entries of empty groups landed. The same unguarded copy is repeated in `agg_first_non_null` (for slice groups
that do not overlap) and `agg_last_non_null` (for groups flagged monotonic) in the same file.

**Why it is wrong here.** `v` is ascending. The rolling windows `(t, t+1]` at `t = 1` and `t = 4` hold no row, so the
result is `[2, None, 4, None]`, missing entries in the middle and at the end, and it is marked ascending.

**Path.** `DataFrame.rolling(...).agg(...)` builds its windows in `crates/polars-time/src/group_by/dynamic.rs` as
slice groups, `GroupsType::new_slice(groups, true, true)` (overlapping, monotonic), with a zero-length slice for an
empty window. The `first` aggregation in `crates/polars-expr/src/expressions/aggregation.rs` calls `agg_first` on
the column, which for an ordinary column reaches `Series::agg_first`. `min` reaches the same copy: `agg_min` in
`crates/polars-core/src/frame/group_by/aggregations/mod.rs` takes a sorted fast path and, for an ascending column,
returns `agg_first_non_null(groups)`, which for a column without missing entries returns `agg_first(groups)`.

**Why `max` and `last` behave.** `agg_max` for an ascending column returns `agg_last_non_null(groups)`, which for a
column without missing entries returns `agg_last(groups)`, and `agg_last` sets no marker at all. Its result is
unmarked, so every consumer takes its general path.

**Repair.** In `agg_first`, `agg_first_non_null` and `agg_last_non_null`, copy the input's marker only when the
result has no missing entries or they are all at one end.

## Cause C: a per-window `slice` then `first` (pipeline C)

**Routine.** `GroupsType::is_sorted_by_first_idx` in `crates/polars-core/src/frame/group_by/position.rs`:

```rust
    pub(crate) fn is_sorted_by_first_idx(&self) -> bool {
        match self {
            GroupsType::Idx(groups) => groups.is_sorted_by_first_idx(),
            GroupsType::Slice { .. } => true,
        }
    }
```

It answers true for every slice group set, treating "slices are ordered by their start" as an invariant of the type,
and ignores the `overlapping` and `monotonic` flags the slice groups carry. `GroupPositions::sort_by_first_idx`
in the same file relies on the same belief and skips sorting slice groups.

**Why it is wrong here.** The rolling windows are overlapping slices. `SliceExpr` in
`crates/polars-expr/src/expressions/slice.rs`, for an offset that varies per group, moves each window's start by its
own offset and rebuilds the groups with `GroupsType::new_slice(groups, *overlapping, false)`: it records that the new
groups are not monotonic. With `period="3i"` and offset `t.last() % 2` the new first rows are 0, 1, 0, 2, 2, which
step back. `Series::agg_first` asks `is_sorted_by_first_idx`, gets true, and copies `v`'s ascending marker onto
`[1, 2, 1, 3, 3]`. `Series::agg_first` is the routine on the reported path that consults it; its other caller is
`GroupPositions::sort_by_first_idx`.

**Why the variants behave.** With a literal offset such as `slice(1, 1)` the slice expression keeps the groups'
`monotonic` flag and every window moves by the same amount, so the first rows stay non-decreasing and the marker is
true (a window shorter than the offset only adds a missing entry at the start). With `last` the aggregation is
`agg_last`, which sets no marker.

**Look-alike.** `GroupsIdx::is_sorted_by_first_idx`, also in `position.rs`, has the same name and is correct: it
returns the `sorted_by_first_idx` field, set when the index groups were actually sorted.

**Repair.** Answer true for slice groups only when they do not overlap or are flagged monotonic
(`!overlapping || monotonic`).

## Cause D: a constant column aggregated with empty groups (pipeline D)

**Routine.** `Column::agg_with_scalar_identity` in `crates/polars-core/src/frame/column/mod.rs`. `pl.lit(5)` makes
`v` a scalar column. After the per-group filter, the groups for `keep = False` are empty. For a scalar column with an
empty group the routine broadcasts the single aggregated value to all groups, materializes it with
`take_materialized_series()`, and applies a validity with a missing entry for each empty group via `with_validity`.

**Why it is wrong here.** The materialized constant is marked sorted: `ScalarColumn::_to_series` in
`crates/polars-core/src/frame/column/scalar.rs` builds it with `new_from_index`, and `new_from_index`
(`ChunkExpandAtIndex` in `crates/polars-core/src/chunked_array/ops/mod.rs`) calls
`set_sorted_flag(IsSorted::Ascending)`, which is true for equal values. `with_validity` goes to
`ChunkedArray::set_validity` in `crates/polars-core/src/chunked_array/mod.rs`, which updates the null count but
leaves the marker alone, so `[5, None, 5, None]` keeps its ascending marker with missing entries interleaved.

**Every route in.** `agg_with_scalar_identity` is called by the `Column` aggregations whose value on a non-missing
constant is the constant itself: `agg_min`, `agg_max`, `agg_mean`, `agg_median`, `agg_first`, `agg_first_non_null`,
`agg_last`, `agg_last_non_null`, `agg_and` and `agg_or`. That is why `min`, `mean` and `last` fail the same way as
`first`.

**Why an ordinary column behaves.** For `Column::Series` the routine calls the series aggregation directly, and an
ordinary column built from a list carries no sorted marker, so there is nothing to copy.

**Repair.** After applying the validity, keep the marker only if the missing entries are all at one end, and set
`IsSorted::Not` otherwise.

## Cause E: a join on a sorted float key (pipeline E)

**Routine.** `join` in `crates/polars-arrow/src/legacy/kernels/sorted_join/inner.rs` for the inner join, and its twin
`join` in `crates/polars-arrow/src/legacy/kernels/sorted_join/left.rs` for the left join. Both are generic over
`T: PartialOrd + Copy + Debug` and walk the two sorted key slices comparing with IEEE operators: `partition_point(|v| v <
&first_right)` to find the start, `val_l == val_r` to match, and `val_r > val_l` to decide which side advances.

**Why it is wrong here.** Under IEEE comparison NaN is unequal to everything, itself included, so a NaN key never
matches. The hash join, which the same call uses when the key is not marked sorted, hashes and compares keys with
total equality (`TotalHash`, `TotalEq` and `to_total_ord`, see `crates/polars-ops/src/frame/join/hash_join/single_keys_inner.rs`),
under which NaN equals NaN. The two paths therefore disagree on NaN keys. The sorted marker is not at fault in this
pipeline: `left.sort("k")` really is ascending, with NaN placed last.

**How the call gets there.** `DataFrame.join` reaches `_inner_join_from_series` in `crates/polars-ops/src/frame/join/mod.rs`,
which calls `_sort_or_hash_inner` in `crates/polars-ops/src/frame/join/hash_join/sort_merge.rs`. That dispatcher takes the
sorted merge path when the left key is marked ascending, neither key has a missing value (`no_nulls`; NaN is not
missing), the physical type is a primitive number, and, when the right key is not marked sorted, the right key is
shorter than the left (`POLARS_JOIN_SORT_FACTOR`, default 1.0); it then sorts the right key with `arg_sort` and
calls `par_sorted_merge_inner_no_nulls`, which dispatches on the dtype to `par_sorted_merge_inner_impl`, which calls
`sorted_join::inner::join` per thread chunk. The left join goes `materialize_left_join_from_series` in
`crates/polars-ops/src/frame/join/dispatch_left_right.rs` (and `private_left_join_multiple_keys` in `mod.rs`) to
`sort_or_hash_left`, `par_sorted_merge_left`, `par_sorted_merge_left_impl` and `sorted_join::left::join`, which
reports the NaN row as unmatched, hence the missing `rid`.

**Callers of the kernels.** `sorted_join::inner::join` is called only by `par_sorted_merge_inner_impl`, and
`sorted_join::left::join` only by `par_sorted_merge_left_impl`, both in `sort_merge.rs`.

**Why the variants behave.** Unsorted `left`: neither key is marked sorted, so the dispatcher falls through to
`hash_join_inner` / `hash_join_left` with total equality. Integer keys: `PartialOrd` is a total order on integers.
A missing value in either key: `no_nulls` is false, so the hash join runs. A right frame with more rows than the left: the
right key is not marked sorted and `size_factor_rhs` is not below `POLARS_JOIN_SORT_FACTOR`, so neither sorted arm
applies and the hash join runs.

**Repair.** Bound both kernels on `TotalOrd` and compare with `tot_lt`, `tot_eq` and `tot_gt`, so the sorted path
agrees with the hash path; excluding float keys from the sorted path would also do.

## Ruled out

- The consumers above (`max`/`min`, `n_unique`/`unique`, the sort fast path, the sorted-key grouping) are correct
  given a truthful marker.
- The recent repair PR #30377 ("Keep sorted flag when appending a unit-length array next to all-null data") changed
  `update_sorted_flag_before_append` in `crates/polars-core/src/chunked_array/ops/append.rs` (with
  `unit_or_sorted_flag`). It applies to appending only, keeps markers in more cases and never drops one, so it cannot
  fix any of these pipelines.
- The arrow gather kernel copies values and validity correctly and has no marker.
- Pipeline E's sorted marker is true; clearing or recomputing markers would not change its result, and `nulls_equal`
  concerns missing values, not NaN.
