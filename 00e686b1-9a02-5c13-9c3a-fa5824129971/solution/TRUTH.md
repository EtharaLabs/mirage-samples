# Ground truth

Repository: `pandas-dev/pandas`
Base commit: `03e5d938adbd3ec9314c326b002170b73bde2c9f`, the sole parent of `ee4989f150f8` (PR #71033). At this commit
four separate defects are live; each was fixed later by its own upstream change:

| Pipeline | Fix | Issue | Merged |
|---|---|---|---|
| A | PR #70963, `b2c790724d99` | #47607 | 2026-10-17 |
| B | PR #71031, `b21d122365e9` | #40366 | 2026-10-17 |
| C | PR #71227, `808b0672c089` | #59106 | 2026-10-17 |
| D | PR #71098, `073f8e3c85f4` | none | 2026-10-25 |

Language: Python, with the compiled kernels in Cython (`pandas/_libs/`).

Reproduction: a wheel built from the base commit gives every result the instruction states, including the harmless
variants (46 checked claims).

## Summary

There are four distinct root causes, one behind each pipeline. They are not one shared bug and they sit in four
different layers of the library: the sortedness test of a multi-level index (pipeline A), the reshape that builds the
stacked index (pipeline B), the compiled group-wise minimum and maximum kernels (pipeline C), and column assignment
in the frame together with the block manager (pipeline D). Fixing any one of them leaves the other three pipelines
wrong.

| Pipeline | Root cause | File |
|---|---|---|
| A, `sort_index` on an ordered-categorical tier level | `MultiIndex.is_monotonic_increasing` falls back to `np.lexsort` over the level values when a level is not monotonic, and for a categorical level that compares the category values as strings, so an index in alphabetical order is reported sorted although the category order differs; `_sort_levels_monotonic` and `get_indexer_indexer` then skip the sort | `pandas/core/indexes/multi.py` |
| B, lookups of a missing label after `stack` | `stack_v3` factorizes the stacked labels with `use_na_sentinel=False` and builds the result with `verify_integrity=False`, so the missing label becomes a real level entry with a non-negative code instead of code -1, which every lookup expects | `pandas/core/reshape/reshape.py` |
| C, `groupby` `max`/`min`/`cummax`/`cummin` over not-a-number values in a nullable float column | `group_min_max` and `group_cummin_max` take missingness only from the mask when one is passed, so an unmasked not-a-number counts as an observation, never wins a comparison, and leaves the `+inf`/`-inf` seed as the result | `pandas/_libs/groupby.pyx` |
| D, an `Int64` (or other one-dimensional extension) array assigned to a label matching two columns | `DataFrame._set_item` broadcasts a one-dimensional value across matched columns only when it is not a one-dimensional-only extension array and the columns are not unique; `BlockManager.iset` then gives every matched position a new block holding the same array object, each with its own reference tracker, so Copy-on-Write never sees the sharing | `pandas/core/frame.py`, `pandas/core/internals/managers.py` |

## Cause A: a sortedness test that reads category values as strings (pipeline A)

**Where the wrong decision is made.** The cached property `MultiIndex.is_monotonic_increasing` in
`pandas/core/indexes/multi.py`. It decides in three steps:

1. `if any(-1 in code for code in self.codes): return False`.
2. `if all(level.is_monotonic_increasing for level in self.levels):` it checks the codes with
   `libalgos.is_lexsorted([x.astype("int64", copy=False) for x in self.codes])`. Codes follow each level's own order,
   so this branch is right.
3. Otherwise it builds `values = [self._get_level_values(i)._values for i in reversed(range(len(self.levels)))]` and
   returns `Index(np.lexsort(values)).is_monotonic_increasing`, falling back to
   `Index(self._values).is_monotonic_increasing` on `TypeError`.

The tier level is a `CategoricalIndex` whose values are `bronze, gold, silver` (the alphabetical order
`from_product` produced and `set_levels(... .astype(tier))` kept) with the category order gold < silver < bronze. In
category order those values are codes `2, 0, 1`, so the level is not monotonic and the property takes step 3. There
`_get_level_values(0)._values` is a `Categorical`, and `np.lexsort` converts it to an array of its values, the
strings, and orders them as strings. The rows are already in alphabetical order, so the permutation is the identity
and the property answers `True`. The decision is based on the natural order of the level values instead of the
level's own order; for a categorical level those disagree. Ordered or unordered makes no difference, because step 3
never looks at the categories.

**Path.** `DataFrame.sort_index` calls `NDFrame.sort_index` in `pandas/core/generic.py`, which calls
`get_indexer_indexer` in `pandas/core/sorting.py`. That routine runs `target = target._sort_levels_monotonic()` and
then `if np.all(ascending) and target.is_monotonic_increasing` (or `not np.any(ascending) and
target.is_monotonic_decreasing`) returns `None` when no `level` is given. `MultiIndex._sort_levels_monotonic`
starts with `if self._is_lexsorted() and self.is_monotonic_increasing: return self`. `_is_lexsorted` compares
`_lexsort_depth` with `nlevels` over the codes, which are lexsorted here, so it returns the index unchanged: the
categorical level is never reordered into category order.

**Downstream.**

- `sort_index()`: `get_indexer_indexer` sees `is_monotonic_increasing` true and returns `None`, and
  `NDFrame.sort_index` returns the rows as they are, bronze first.
- `sort_index(level="tier")`: the short cut does not return for a `MultiIndex` with a `level`, so the routine calls
  `target.sortlevel(level, ...)`, which orders by the level codes. Because `_sort_levels_monotonic` returned the
  index unchanged, those codes are positions in the alphabetical level, and the order stays alphabetical.
- `sort_index(ascending=False)`: `is_monotonic_decreasing` is `self[::-1].is_monotonic_increasing`, which is false
  here, so the routine sorts with `lexsort_indexer` over `target._get_codes_for_sorting()`. Those codes are again
  alphabetical positions, so the result is the alphabetical order reversed: silver, gold, bronze.
- `report.index.is_monotonic_increasing` is the wrong answer itself.

**Why the variants behave.** With the gold rows first, or all rows reversed, the strings are not in order, so step 3
answers `False` and `_is_lexsorted()` is false too. `_sort_levels_monotonic` then rebuilds every non-monotonic level
with `lev.argsort()`, which for a `CategoricalIndex` follows the category order, and remaps the codes; sorting those
codes gives gold, silver, bronze. `set_index(["tier", "quarter"])` builds the index with `MultiIndex.from_arrays`,
which takes the categorical's categories, in category order, as the level, so the level is monotonic and step 2
decides on codes. A one-level `CategoricalIndex` never reaches this property; its own sortedness test and
`nargsort` use the categorical codes. `reset_index().sort_values(...)` sorts the column through the categorical's
`argsort` and does not involve the multi-level index at all.

**Smallest repair.** In `is_monotonic_increasing`, decide on codes after putting the levels in order:
`target = self._sort_levels_monotonic(raise_if_incomparable=True)` (keeping the object-values fallback for
incomparable levels) and `return libalgos.is_lexsorted([x.astype("int64", copy=False) for x in target.codes])`.
In `_sort_levels_monotonic`, change the early return to `if all(lev.is_monotonic_increasing for lev in
self.levels): return self`, so it no longer consults the property it is used to compute.

## Cause B: a stacked index that stores the missing label as a level entry (pipeline B)

**Where the wrong decision is made.** `stack_v3` in `pandas/core/reshape/reshape.py`, the implementation behind
`DataFrame.stack` (its only caller; `DataFrame.stack` calls it as `result = stack_v3(self, level)`). The wrong
decision is repeated inline in its two branches:

- for a frame whose index is not a `MultiIndex`: `codes, uniques = factorize(frame.index, use_na_sentinel=False)`,
  then `index_levels = [uniques]`;
- for a single stacked column level: `column_levels = [ordered_stack_cols_unique]` and
  `column_codes = [factorize(ordered_stack_cols_unique, use_na_sentinel=False)[0]]`.

It then builds `MultiIndex(levels=index_levels + column_levels, codes=index_codes + column_codes, names=...,
verify_integrity=False)`. With `use_na_sentinel=False`, `factorize` gives the missing label a real code (1 here)
and keeps NaN among the uniques, so the level holds NaN and the rows point at it. A `MultiIndex` assumes the
opposite: a missing label is code -1 and never a level entry. `MultiIndex.from_arrays` and `from_tuples` factorize
with the sentinel, and the constructor with `verify_integrity=True` runs `_verify_integrity`, which calls
`_validate_codes` to re-code every code that points at a missing level entry to -1. `stack_v3` passes
`verify_integrity=False`, so the convention is never restored.

**Path.** `wide.stack()` calls `DataFrame.stack` in `pandas/core/frame.py`, which calls `stack_v3`; the index
branch handles pipeline B, and `stack(level="region")` on the column variant takes the column branch.

**Downstream.** Every lookup encodes a missing key as code -1:

- `long.loc[(np.nan, "units")]` (and the same with `None`) goes to `MultiIndex.get_loc`, which for a full-length tuple
  calls `self._engine.get_loc(key)`. `BaseMultiIndexCodesEngine.get_loc` in `pandas/_libs/index.pyx` encodes each
  component as `1 if checknull(v) else lev.get_loc(v) + multiindex_nulls_shift`, so the missing component becomes
  1, the shifted -1, while the stacked rows were stored from code 1 shifted to 3 (`codes += multiindex_nulls_shift`).
  No row matches, and `get_loc` raises `KeyError`.
- `long.xs(np.nan, level="region")` goes through `get_loc_level` and `_get_level_indexer`, which turns the missing
  key into -1 with `_get_loc_single_level_index` and finds no row with code -1, so it raises `KeyError`.
- `long.index.isin([...])` builds `MultiIndex.from_tuples(values)`, where the missing label is code -1, and calls
  `get_indexer_for(self)`. The engine's `_extract_level_codes` re-codes the stacked index onto the lookup's levels
  with `_recode_for_new_levels`, where NaN is not a level, and treats only rows whose code is -1 as missing, so the
  stacked NaN rows encode as not found and come out `False`.
- The column variant fails in the same engine `get_loc`.

`groupby(level="region", dropna=False)` and printing work because they read the level values through the codes and
never encode a key.

**Why the variants behave.** `MultiIndex.from_tuples` codes the missing label -1. A wide frame that already has a
two-level index takes the other branch of `stack_v3`, `index_levels = frame.index.levels` with its codes tiled, so its
missing label stays -1. `melt` followed by `set_index` builds the index with `MultiIndex.from_arrays`. The north
lookup has no missing component.

**Smallest repair.** Factorize with the sentinel in both branches: `codes, uniques = factorize(frame.index)` for the
index, and `codes, uniques = factorize(ordered_stack_cols_unique)` with `column_levels = [uniques]` and
`column_codes = [codes]` for the columns, so the missing label is code -1 and absent from the levels.

## Cause C: group minimum and maximum kernels that keep their seed for an unmasked not-a-number (pipeline C)

**Where the wrong decision is made.** The compiled kernels `group_min_max` and `group_cummin_max` in
`pandas/_libs/groupby.pyx`; the decision is repeated inline in both. When a mask is passed (`uses_mask`), each
decides whether an entry is missing from `mask[i, j]` alone; without a mask it uses `_treat_as_na(val, ...)`, which
for floats is `val != val`. With `future.distinguish_nan_and_na` the masked float division `0/0` keeps NaN in the
data and leaves the mask false, so the NaN is treated as an observation. In `group_min_max` it increments
`nobs[lab, j]` and is compared with `val > group_min_or_max[lab, j]` (or `<` for the minimum), which is false for
NaN, so the accumulator keeps the seed `_get_min_or_max` set (through `get_rank_nan_fill_val`): `+inf` for the
minimum and `-inf` for the maximum. `_check_below_mincount` then copies the seed into `out`, because `nobs` meets
`min_count`. In a group that also holds numbers, the NaN loses every comparison and is skipped, so store c gets 2.0
instead of a propagated not-a-number. `skipna=False` does not help, because its branches only run for masked
entries. `group_cummin_max` seeds `accum` the same way, the NaN never replaces it, and each row gets
`out[i, j] = mval`, the seed.

The kernels are called by the wrappers `group_max` and `group_min` (`group_min_max` with `compute_max` true and
false) and `group_cummax` and `group_cummin` (`group_cummin_max`), in the same file.

**Path.** `df.groupby("store")["ratio"].max()` runs `GroupBy.max` in `pandas/core/groupby/groupby.py`, which calls
`_cython_agg_general`; its `array_func` calls the grouper's `_cython_operation` in `pandas/core/groupby/ops.py`,
which builds a `WrappedCythonOp` and calls its `cython_operation`. For a value that is not a NumPy array this calls
`values._groupby_op(...)`, here `BaseMaskedArray._groupby_op` in `pandas/core/arrays/masked.py`, which passes
`self._data` together with `mask=self._mask` and a `result_mask` to `WrappedCythonOp._cython_op_ndim_compat`. `WrappedCythonOp._call_cython_op`
transposes the values and mask, picks the kernel with `_get_cython_function` and calls `group_max(out, counts,
values, labels, min_count, ..., mask=mask, result_mask=result_mask, skipna=skipna)`. `cummax` and `cummin` take the
transform kind of the same path to `group_cummax` and `group_cummin`. `resample("2D").max()` groups through the same
grouper and kernel. A `float64[pyarrow]` column reaches it through `ArrowExtensionArray._groupby_op` in
`pandas/core/arrays/arrow/array.py`, which for numeric types converts with `_to_masked()`: its mask is `self.isna()`,
the Arrow nulls only, and `to_numpy` keeps NaN, so the NaN arrives unmasked again.

**Downstream.** `BaseMaskedArray._maybe_mask_result(res_values, result_mask)` wraps the output as a nullable float
array; `result_mask` is false for the group, so the infinities are reported as valid values.

**Why the variants behave.** A plain `float64` column has no mask, so `_treat_as_na` skips the NaN, `nobs` stays 0,
and `_check_below_mincount` writes NaN. With the option off, masked arithmetic folds NaN into the mask, so the
entries are skipped as missing. Reducing without grouping uses the masked reductions in
`pandas/core/array_algos/masked_reductions.py`, not these kernels. `rolling(2).max()` uses the window kernels in
`pandas/_libs/window/aggregations.pyx`. `sum` and `mean` add the NaN in `group_sum` and `group_mean`, where it
propagates, and `first` copies the first value.

**Smallest repair.** In the masked path of both kernels, let an unmasked float NaN propagate instead of comparing it:
before the `compute_max` comparison, `if (numeric_t is float32_t or numeric_t is float64_t) and val != val:
group_min_or_max[lab, j] = val` in `group_min_max`, and `accum[lab, j] = mval = val` in `group_cummin_max`.

## Cause D: one array shared by every column a key matches (pipeline D)

**Where the wrong decision is made.** `DataFrame._set_item` in `pandas/core/frame.py`, together with
`BlockManager.iset` in `pandas/core/internals/managers.py`.

`_set_item(key, value)` first calls `self._sanitize_column(value)`, which for an array returns
`sanitize_array(value, self.index, copy=True, ...)` and `refs=None`. It broadcasts a one-dimensional value across
several matched columns only when `key in self.columns and value.ndim == 1 and not
is_1d_only_ea_dtype(value.dtype)` and the columns are not unique or are a `MultiIndex`, as
`value.reshape(1, -1).repeat(ncols, axis=0).T`. An `Int64`, string or categorical array is a one-dimensional-only
extension array, so it is passed on unchanged: `_set_item_mgr(key, value, refs)` resolves `loc =
self._info_axis.get_loc(key)`, a mask or slice over the matched columns, and calls `_iset_item_mgr(loc, value,
refs=refs)`, which calls `self._mgr.iset(loc, value, inplace=False, refs=refs)`.

In `BlockManager.iset`, `value_is_extension_type = is_1d_only_ea_dtype(value.dtype)`. For such a value,
`value_getitem` returns `value` itself, the column-count check (`len(value) != len(blklocs)`) is skipped, and the
replaced positions get new blocks `new_block_2d(values=value, placement=BlockPlacement(slice(mgr_loc, mgr_loc + 1)),
refs=refs)`, one per position, all holding the same array object. With `refs=None`, each new block creates its own
`BlockValuesRefs` (the block constructor in `pandas/_libs/internals.pyx`), so Copy-on-Write sees every column as
unreferenced although they share memory.

**Path.** `inv["qty"] = pd.array(...)` calls `DataFrame.__setitem__`. The key is a plain label and the value is not a
frame. The branch for a duplicated label sends a value to `_setitem_array([key], value)` only when its length equals
the number of matched columns, 2 here, and the value has 3 rows, so `__setitem__` calls `self._set_item(key, value)`.

**Downstream.** `inv.iloc[0, 0] = 99` goes through the `iloc` setter to `BlockManager.column_setitem`, which copies
the column first only `if not self._has_no_reference(loc)`. The block's private reference tracker says there are no
references, so it writes in place into the shared array, and the second `qty` column shows the same change.
`inv.iloc[0, 1] += 1` and `inv.iloc[:, 0] = inv.iloc[:, 0] * 2` write through the same path. The `"string"` array
and the `pd.Categorical` behave like the `Int64` array because they are also one-dimensional-only extension arrays,
and with two-level columns the key `"qty"` matches both columns, so the same branch runs.

On a unique `DatetimeIndex`, the key `"2024"` matches two columns, but the broadcast in `_set_item` runs only for
non-unique columns or a `MultiIndex`. A NumPy array or the scalar 7 therefore reaches `iset` as one column for two
positions and fails its column-count check with `Got 2 positions but value has 1 columns.` An `Int64` array skips
that check and is shared as above.

**Why the variants behave.** A NumPy array is broadcast with `reshape`/`repeat` into a new two-dimensional array that
holds one column per position. A `pd.Series` goes through `_reindex_for_setitem`, which returns
`value._values, value._references`; both new blocks register with that one `BlockValuesRefs` (`refs.add_reference`),
so `_has_no_reference` is false and `column_setitem` copies the column before the first write. A timezone-aware
datetime array is two-dimensional-capable, not one-dimensional-only, so it takes the broadcast. Two assignment
statements sanitize, and so copy, the array twice.

**Smallest repair.** In `_set_item_mgr`, when `loc` selects several positions and the value is one-dimensional:
for a one-dimensional-only extension array, set the first position with the value and every other position with
`value.copy()`; otherwise broadcast with `reshape`/`repeat` whether or not the columns are unique (moving the
broadcast out of `_set_item`). In `BlockManager.iset`, check the column count for extension values too.

## Ruled out

- The four faults are independent. Pipeline A is a sortedness test, pipeline B the construction of a stacked index,
  pipeline C two compiled kernels and pipeline D column assignment. Fixing one leaves the others wrong.
- Categorical sorting itself is correct: a one-level categorical index and `sort_values` order by category. The
  fault in pipeline A is the multi-level index's sortedness test.
- The lookup engine, `get_loc`, `xs` and `isin` are correct; they implement the code -1 convention for missing labels,
  and indexes built by `from_tuples` or `from_arrays` work. The fault in pipeline B is the index that `stack_v3`
  builds.
- The option `future.distinguish_nan_and_na`, the masked arithmetic and the masked reductions are correct; the fault
  in pipeline C is that the min and max kernels ignore an unmasked not-a-number.
- Copy-on-Write and the `iloc` setter are correct: the columns already share one array before the write, and the
  reference trackers say they do not. The fault in pipeline D is in `_set_item` and `iset`.
