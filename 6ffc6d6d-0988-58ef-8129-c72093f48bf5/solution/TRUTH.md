# Ground truth

Repository: `pandas-dev/pandas`
Base commit: `03e5d938adbd3ec9314c326b002170b73bde2c9f`, the sole parent of `ee4989f150f8` (PR #71033), the earliest of
the four fixes. At this commit four separate defects are live; each was fixed later by its own upstream change:

| Step | Fix | Issue | Merged |
|---|---|---|---|
| A | PR #71020, `c64d1448ef1a` | #50293 | 2026-10-17 |
| B | PR #71324, `07b3c9382182` | #12755 | 2026-10-30 |
| C | PR #71033, `ee4989f150f8` | #39899 | 2026-10-17 |
| D | PR #71087, `119e3fc415e3` | #43547 | 2026-10-17 |

Language: Python, with compiled helpers in Cython (`pandas/_libs/`).

Reproduction: a wheel built from the base commit gives every result the instruction states, including the harmless
variants (41 checked claims).

## Summary

There are four distinct root causes, one behind each step. They are not one shared bug and they sit in four different
routines: the conversion of tuples to a multi-level index together with the lookup that relies on it (step A), the
in-place arithmetic wrapper (step B), frame comparison (step C), and `pivot` (step D). Fixing any one of them leaves
the other three steps wrong.

| Step | Root cause | File |
|---|---|---|
| A, lookups with tuple keys of another length | `tuples_to_object_array` sizes every row by the first tuple, so longer keys are cut to their prefix and shorter ones raise `IndexError`; `Index._maybe_downcast_for_indexing` converts the keys with `MultiIndex.from_tuples` and accepts the result whatever its number of levels, and the codes engine then compares only as many levels as the index has | `pandas/_libs/lib.pyx`, `pandas/core/indexes/base.py` |
| B, `+=` and friends with a partner that has extra labels | `NDFrame._inplace_method` computes the full operation, aligned on the union of labels, and only then cuts the result back with `reindex_like(self)`, so missing values from the extra labels have already changed the dtype | `pandas/core/generic.py` |
| C, `compare` | `NDFrame.compare` masks the equal cells with `where` before it drops the all-equal rows and columns, so the missing values it inserts change the dtype of the rows it keeps | `pandas/core/generic.py` |
| D, `pivot` with a list of values | `pivot` builds the intermediate frame from `data[values]._values`, one two-dimensional array in the columns' common dtype, so every value column takes that dtype | `pandas/core/reshape/pivot.py` |

## Cause A: tuple keys converted by their first entry's length (step A)

**Where the wrong decision is made.** Two routines decide together.

- `tuples_to_object_array` in `pandas/_libs/lib.pyx` sets `k = len(tuples[0])`, allocates an `(n, k)` object array
  and copies `tup[j]` for `j < k` from every tuple. It never checks the other tuples' lengths, so `("a", "b", "c")`
  after `("a", "b")` is cut to `("a", "b")`, and `("a", "b")` after `("b",)` fails with `IndexError: tuple index out
  of range`. Its only caller is `MultiIndex.from_tuples` in `pandas/core/indexes/multi.py`, which uses it for
  ndarray and `Index` input (`np.asarray(tuples._values)`); a plain list goes through `to_object_array_tuples`
  instead.
- `Index._maybe_downcast_for_indexing` in `pandas/core/indexes/base.py`, for a multi-level index looked up with a flat
  index (`self._is_multi and not other._is_multi`), replaces the keys with `type(self).from_tuples(other)` and keeps
  the result without comparing its number of levels with `self.nlevels`. It is called by `Index.get_indexer`,
  `Index.get_indexer_non_unique` and `Index.join`.

Three-part keys that all have three parts become a valid three-level index, which is then accepted; mixed keys are
cut to the first key's length.

**Path.** `s.reindex(keys)` runs `NDFrame.reindex`, which calls `Index.reindex` on the multi-level index (it is
inherited, not overridden), which asks for an indexer with `get_indexer`. `s.loc[[...]]` reaches the same
`get_indexer` through the `.loc` list lookup, and `DataFrame.reindex` takes the same route. `Index.get_indexer`
calls `_maybe_downcast_for_indexing`, which calls `MultiIndex.from_tuples`, which calls `tuples_to_object_array`. A
plain list of keys takes a different road to the same comparison: the `Index` constructor turns
`[("a", "b"), ("a", "b", "c")]` into a three-level index, padding the shorter tuple with a missing value, so the
lookup receives a multi-level target with more levels than the index.

**Downstream.** `Index._get_indexer` sees two multi-level indexes and calls the codes engine's
`_extract_level_codes(target)`, which recodes the target with `target._recode_for_new_levels(self.levels)`. That
generator recodes only `len(self.levels)` levels, so a three-level target is compared on its first two levels, and it
raises `AssertionError: Length of new_levels (2) must be <= self.nlevels (1)` when the converted target has fewer
levels than the index. The cut keys `("a", "b")` match row 0, giving `get_indexer` `[0, 0]` and `reindex` `[1, 1]`;
`MultiIndex._wrap_reindex_result` then builds the result's index from `self.take(indexer)`, so the three-part label
does not even appear in it. With `[("a", "b", "c"), ("c", "d", "e")]`, and with the plain list, the prefixes match
rows 0 and 1, or row 0 twice. `Index.map`
returns `MultiIndex.from_tuples(new_values, ...)` when the first mapped value is a tuple, and `new_values` is an
ndarray, so its tuples are cut the same way.

**Why the variants behave.** Keys of the right length convert to a two-level index and match exactly. A single tuple
in `.loc` is split into one indexer per level and rejected with `Too many indexers`. `MultiIndex.isin` checks that
every value has `nlevels` elements before it converts them, and raises.

**Smallest repair.** In `tuples_to_object_array`, raise `ValueError("All tuples must have the same length")` when a
tuple's length differs from `k`; in `_maybe_downcast_for_indexing`, use the converted index only when
`from_tuples` succeeds and its `nlevels` equals `self.nlevels`, and otherwise compare as a flat index, so keys of
another length never match. Callers that build an index from mixed tuples (`Index.map`, the non-unique reindex) then
fall back to a flat index on that `ValueError`.

## Cause B: in-place arithmetic aligned on the union of labels (step B)

**Where the wrong decision is made.** `NDFrame._inplace_method` in `pandas/core/generic.py`:
`result = op(self, other)`, then `self._update_inplace(result.reindex_like(self))`. The operation aligns both operands
on the union of their labels, as binary operations do, so the label 3 that only the partner has gets a missing value,
and an `int64` column cannot hold one, so the whole result becomes `float64`. `reindex_like(self)` then drops label 3
but keeps the dtype. The decision is to compute the full union first and cut it back afterwards, although an in-place
update can only ever keep the labels of `self`.

`_inplace_method` is called by every in-place operator in the same file: `__iadd__`, `__isub__`, `__imul__`,
`__itruediv__`, `__ifloordiv__`, `__imod__`, `__ipow__`, `__iand__`, `__ior__` and `__ixor__`.

**Path.** `x += partner` calls `NDFrame.__iadd__`, which calls `_inplace_method(other, type(self).__add__)`.
`df["a"] += partner` evaluates `df["a"].__iadd__(partner)` and assigns the result back. `df += other_df` and
`df &= other_df` go through `DataFrame.__iadd__` and `__iand__`.

**Downstream.** `_update_inplace` installs the `float64` values in `x`, so `x` is the same object with a new dtype.
For `df &= other_df` the union-aligned `&` itself fails: the extra row puts a missing value into the integer column
`a`, which becomes `float64`, and `float & int` raises `TypeError` before `reindex_like` is reached. The label order
of the partner does not matter because alignment sorts it out either way.

**Why the variants behave.** With exactly the labels of `x` the alignment adds nothing. An `Int64` series holds the
missing value in its mask, so the union result stays `Int64` and `reindex_like` restores the values. Boolean
operators align the operands as objects, and `fill_bool` in `logical_op` sets the aligned missing values to `False`,
so the result stays boolean. `x + partner` without assignment is
supposed to return the union, and labels of `x` that the partner lacks are missing in the operation itself.

**Smallest repair.** In `_inplace_method`, when `other` is an `NDFrame` of the same dimension whose index differs
from `self.index`, align `other` to `self` first (`other = self.align(other, join="left", axis=0)[1]`), so rows that
only `other` has can never introduce missing values.

## Cause C: comparison that masks before it drops (step C)

**Where the wrong decision is made.** `NDFrame.compare` in `pandas/core/generic.py`. It builds
`mask = ~((self == other) | (self.isna() & other.isna()))` and then, unless `keep_equal`, sets
`self = self.where(mask)` and `other = other.where(mask)`, which puts a missing value into every equal cell,
including the whole second row and the whole column `b`. Only after that, unless `keep_shape`, it computes
`cmask = mask.any()` and `rmask = mask.any(axis=1)` and keeps `self.loc[rmask, cmask]`. The missing values have
already turned `int64` into `float64` (and booleans into `object`) for the column, so the kept row carries the
rounded floats: `1.567808378753274e+18` is not `1567808378753274000`, and `2**63 + 1` and `2**63 + 3` round to the
same float, so the reported difference disappears. The decision is the order: mask first, drop second.

`NDFrame.compare` is called by `DataFrame.compare` and `Series.compare`, which both return `super().compare(...)`.

**Downstream.** The comparison result is concatenated from the masked, cut `self` and `other`, so the frame the team
gets has the upcast dtype.

**Why the variants behave.** `keep_equal=True` never masks. When every row differs, the mask has no false entry in
the column, so `where` inserts nothing. `Int64` holds missing values in its mask and datetimes hold `NaT`, so neither
is upcast. With `keep_shape=True` the equal rows are kept, so they must be shown as missing, and `float64` is the
expected dtype.

**Smallest repair.** Drop the all-equal rows and columns first and only then mask: compute `rmask`/`cmask`, cut
`self`, `other` and `mask` with them, and then apply `where(mask)` to what is left.

## Cause D: a pivot that stacks several value columns into one array (step D)

**Where the wrong decision is made.** `pivot` in `pandas/core/reshape/pivot.py`. When `values` is list-like and not a
tuple it builds `indexed = data._constructor(data[values]._values, index=multiindex, columns=values)`.
`data[values]._values` is one two-dimensional array, so the block manager picks a common dtype for all the value
columns: `float64` for `int64` with `float64`, `object` once a string column is involved. For a single value it builds
`data._constructor_sliced(data[values]._values, index=multiindex)`, a one-dimensional array of that column's own
dtype. The decision is to go through a single array instead of keeping the columns.

`pivot` is called by `DataFrame.pivot` in `pandas/core/frame.py`, and `pd.pivot` is the same function.

**Downstream.** `indexed.unstack(columns_listlike)` keeps whatever dtype `indexed` has, so every value column of the
result has the common dtype.

**Why the variants behave.** `values="ints"` takes the one-dimensional branch; `values=["ints"]` makes an array of a
single dtype. With `values` left out, `pivot` calls `data.set_index(...)` and unstacks, which keeps each column's
dtype. `pivot_table` aggregates through `groupby`, column by column, and `set_index(...).unstack(...)` never builds the
joint array.

**Smallest repair.** Build the intermediate frame without going through one array, for example
`indexed = data[values].set_axis(multiindex, axis=0).set_axis(values, axis=1)`, so each value column keeps its dtype.

## Ruled out

- The four faults are independent: a tuple conversion and the lookup that trusts it, the in-place wrapper, the
  comparison, and the pivot. Fixing one leaves the others wrong.
- The codes engine and the alignment of binary operations are correct: the engine compares the levels it is given,
  and binary operations are meant to align on the union. The faults are in what step A hands the engine and in
  `_inplace_method` keeping the union.
- `where`, `reindex_like` and `unstack` are correct; steps B, C and D go wrong in the order and form in which their
  callers use them.
