# Ticket analysis: four quietly wrong pipelines (DRAFT, being refined)

Preliminary finding: four distinct root causes, one per pipeline.

- A: `MultiIndex.is_monotonic_increasing` (`pandas/core/indexes/multi.py`). Its fallback path calls `np.lexsort` on the raw level *values*. For a Categorical level that compares the labels alphabetically and ignores the category order.
- B: `stack_v3` (`pandas/core/reshape/reshape.py`) calls `factorize(..., use_na_sentinel=False)` twice and passes `verify_integrity=False`. This stores NaN as a real level entry with a non-negative code. Lookup code expects NaN to be code -1.
- C: `group_min_max` / `group_cummin_max` (`pandas/_libs/groupby.pyx`). On the masked path, NA is decided only from the mask, so an unmasked NaN goes into `>`/`<` comparisons that are always False. The result stays at the ±inf seed.
- D: `DataFrame._set_item` (`pandas/core/frame.py`) does not broadcast 1-D-only extension arrays. `BlockManager.iset` (`pandas/core/internals/managers.py`) then puts the same EA object into one block per duplicate column, with no refs.

(Details to follow.)
