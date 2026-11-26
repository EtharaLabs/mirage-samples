# Analysis (first draft, being refined)

Four distinct root causes, one per step (A, B, C, D); no shared cause.

- A: `lib.tuples_to_object_array` (pandas/_libs/lib.pyx) fixes the MultiIndex width from `len(tuples[0])`; `Index._maybe_downcast_for_indexing` (pandas/core/indexes/base.py) converts tuple keys with it and never compares key length with `self.nlevels`.
- B: `NDFrame._inplace_method` (pandas/core/generic.py) computes the out-of-place, outer-aligned result and then `reindex_like(self)`, keeping the upcast dtype.
- C: `NDFrame.compare` (pandas/core/generic.py) applies `where(mask)` before dropping the equal rows/columns.
- D: `pivot` (pandas/core/reshape/pivot.py) builds the frame from `data[values]._values` (single interleaved 2-D array of a common dtype).

(details to follow)
