# Ground truth

Repository: `pandas-dev/pandas`
Base commit: `4304b35aae259160264eec90b207c3bb5c86e152` (sole first parent of merge commit
`7ceea803f9f4e44aafd8ccf078e41cc3b583b8bc`, which landed PR #68931 and closed issue #63920)
Language: Python

## The behaviour at `base_commit`

Grouping by two keys where one is a column of declared categories and `observed=False` is requested
takes a path that neither of the two simpler paths takes. When every grouping is observed, one helper
computes the group identities. When none is, another does. When the groupings are *mixed* -- one
observed, one not -- a third arm runs, combines the two helpers' outputs by arithmetic, and it is that
arithmetic that is wrong.

A row whose category is missing is marked with `-1`. The combining arithmetic multiplies and adds the
two id arrays without regard for that marker, so the `-1` becomes some other number: negative, or a
valid position belonging to a different group. Both branches immediately below then use `ids` as
*positions*. One of them re-indexes with a plain `take`, so a mangled negative index either wraps
around to a real group -- the silent wrong total -- or exceeds the axis and raises. The restoration of
the `-1`s exists in the routine, but it runs after both branches, too late to stop either.

Nothing in the aggregation arithmetic is wrong. The sum is computed correctly over labels it was
handed; the labels are wrong before it starts.

## Where group membership is decided

The routine is `BaseGrouper.result_index_and_ids`, defined in
`pandas/core/groupby/ops.py`:

```python
    @cache_readonly
    def result_index_and_ids(self) -> tuple[Index, npt.NDArray[np.intp]]:
        levels = [
            Index._with_infer(ping.uniques, copy=False) for ping in self.groupings
        ]
        obs = [
            ping._observed or not ping._passed_categorical for ping in self.groupings
        ]
        sorts = [ping._sort for ping in self.groupings]
```

It returns a pair: the `Index` of group labels, and the `ids` array assigning each row to a position
in that index. Twenty-five distinct call targets occur syntactically inside it, in source spelling,
repeats counted once:

- `Index._with_infer`
- `MultiIndex`
- `all`
- `any`
- `compress_group_index`
- `ensure_platform_int`
- `enumerate`
- `index.take`
- `len`
- `level.set_categories`
- `list`
- `np.arange`
- `np.concatenate`
- `np.delete`
- `np.repeat`
- `np.tile`
- `np.unique`
- `np.where`
- `result_index._drop_level_numbers`
- `result_index.argsort`
- `result_index.take`
- `reversed`
- `self._ob_index_and_ids`
- `self._unob_index_and_ids`
- `zip`

The routine has four arms, selected on how many groupings are observed:

```python
        if len(self.groupings) == 1:
            result_index = levels[0]
            result_index.name = self.names[0]
            ids = ensure_platform_int(self.codes[0])
        elif all(obs):
            result_index, ids = self._ob_index_and_ids(
                levels, self.codes, self.names, sorts
            )
        elif not any(obs):
            result_index, ids = self._unob_index_and_ids(levels, self.codes, self.names)
        else:
```

The first three are sound. The team's report lands in the fourth, the mixed arm, and only there: a
single grouping key cannot reach it, and neither can two keys that are both observed or both not.
`observed=False` on a categorical is what makes `ping._observed or not ping._passed_categorical`
false for that key while the other key's stays true.

## The arithmetic that destroys the marker

Inside the mixed arm the two helpers are called on the partitioned groupings, their indexes are
stitched into one `MultiIndex`, and then:

```python
            ids = len(unob_index) * ob_ids + unob_ids
```

This is the defect. `ob_ids` carries `-1` for a row whose observed key was dropped, `unob_ids` carries
`-1` for a row whose unobserved key was dropped, and the expression treats both as ordinary
non-negative positions. With `len(unob_index)` of 3 and `ob_ids` of `-1` against `unob_ids` of 2, the
result is `-1`; with `ob_ids` of 1 against `unob_ids` of `-1`, it is `2`, a position that belongs to a
real group. The marker is gone and nothing downstream can tell the difference.

## What is then done with the destroyed value

Two branches follow, and they do not behave alike. The sort branch re-indexes:

```python
            if any(sorts):

                n_levels = len(sorts)
                drop_levels = [
                    n_levels - idx
                    for idx, sort in enumerate(reversed(sorts), 1)
                    if not sort
                ]
                if len(drop_levels) > 0:
                    sorter = result_index._drop_level_numbers(drop_levels).argsort()
                else:
                    sorter = result_index.argsort()
                result_index = result_index.take(sorter)
                _, index = np.unique(sorter, return_index=True)
                ids = ensure_platform_int(ids)
                ids = index.take(ids)
```

`index.take(ids)` is a positional gather. A mangled `-1` reads the *last* element of `index`, which is
a real group's new position, so the row is silently filed under a group it does not belong to. A
mangled value more negative than `-len(index)` is out of range, and numpy raises -- which is the
out-of-bounds error naming a negative position that the team cannot account for. They never index
anything by hand; numpy does it for them, with an index this arithmetic produced.

The unsorted branch does something else entirely:

```python
            else:


                ids, uniques = compress_group_index(ids, sort=False)
                ids = ensure_platform_int(ids)
                taker = np.concatenate(
                    [uniques, np.delete(np.arange(len(result_index)), uniques)]
                )
                result_index = result_index.take(taker)
```

`compress_group_index` renumbers the id values densely and reports the distinct ones; `result_index`
is then reordered to match. The mangled value is never used as a position into anything, so this
branch cannot raise. It can still be wrong -- a mangled id that collides with a real one merges two
groups, and the reordering can put groups in an order the caller did not ask for -- but the wrong
ordering and the duplicated group are its failure mode, not the index error.

The team reports both symptoms, which is consistent: the arithmetic is shared, and which branch runs
depends on whether they asked for sorted output.

## Why the restoration already present does not help

The routine does restore the markers. It simply does so too late:

```python
            if self.dropna:
                ids = np.where((ob_ids < 0) | (unob_ids < 0), -1, ids)
```

This sits *after* both branches, at the end of the mixed arm. By the time it runs, the sort branch has
already gathered with a corrupted index -- and if that gather raised, this line is never reached at
all. Where the value it writes is correct, the damage it repairs has already been done.

Both preconditions the team observed follow from these two facts. `dropna=True` is what makes any
`-1` exist to be mangled. `sort=False` is what selects the branch whose failure is silent rather than
loud; note that `any(sorts)` is over the *per-grouping* sort flags, so the branch is chosen by the
groupings' own settings rather than by one global switch.

## The identically named routine in the same file, and why it is not the one

`pandas/core/groupby/ops.py` defines `result_index_and_ids` twice. The second is on `BinGrouper`:

```python
    @cache_readonly
    def result_index_and_ids(self):
        result_index = self.binlabels
        if len(self.binlabels) != 0 and isna(self.binlabels[0]):
            result_index = result_index[1:]

        ngroups = len(result_index)
        rep = np.diff(np.r_[0, self.bins])

        rep = ensure_platform_int(rep)
        if ngroups == len(self.bins):
            ids = np.repeat(np.arange(ngroups), rep)
        else:
            ids = np.repeat(np.r_[-1, np.arange(ngroups)], rep)
        ids = ensure_platform_int(ids)

        return result_index, ids
```

`BinGrouper` is declared `class BinGrouper(BaseGrouper)` and overrides the method, so an instance of
it never reaches the arm described above. Three things rule it out on its own body. It has no mixed
arm and no combining arithmetic -- there is nothing to destroy a marker. It builds its `-1`s
deliberately, with `np.repeat(np.r_[-1, np.arange(ngroups)], rep)`, and never uses `ids` as a position
into anything afterwards. And it is reached only for binned grouping, which is resampling and
`cut`-style binning, not a `groupby` on two columns; it has no `groupings` list of the kind the mixed
arm partitions.

Six distinct call targets occur inside it -- `ensure_platform_int`, `isna`, `len`, `np.arange`,
`np.diff`, `np.repeat` -- of which four are shared with the real target. Read quickly, the two look
like variations on one routine. They are not: one combines two independently computed id spaces, the
other repeats a range.

Nothing chooses between them at runtime in the sense of a dispatch table. Ordinary attribute lookup
resolves to whichever class the grouper actually is, and for a two-column `groupby` that is
`BaseGrouper`.

## The sibling helper that gets the same recode right

`BaseGrouper._ob_index_and_ids`, immediately below the target in the same file, performs a recode of
exactly the same shape -- and guards it:

```python
            ob_ids = np.where(ob_ids == -1, -1, index.take(ob_ids))
```

The comparison is the sharpest evidence available in the checkout that the target's `ids =
index.take(ids)` is a defect rather than a deliberate choice: the same author, the same file, the same
`index.take` against the same kind of id array, with the sentinel explicitly preserved. The mixed arm
does the ungarded version of a thing its own helper does carefully.

`_unob_index_and_ids` is the other half of the pair:

```python
    def _unob_index_and_ids(
        self,
        levels: list[Index],
        codes: list[npt.NDArray[np.intp]],
        names: list[Hashable],
    ) -> tuple[MultiIndex, npt.NDArray[np.intp]]:
        shape = tuple(len(level) for level in levels)
        unob_ids = get_group_index(codes, shape, sort=True, xnull=True)
        unob_index = MultiIndex.from_product(levels, names=names)
        unob_ids = ensure_platform_int(unob_ids)
        return unob_index, unob_ids
```

It builds the full cartesian product of the unobserved levels, which is what `observed=False` asks
for, and returns ids that may carry `-1`. Neither helper is the culprit; both hand back correct
values that the mixed arm then combines incorrectly.

## The path from the call the team makes

`result_index_and_ids` is never called directly by user code. Two cached accessors stand in front of
it, immediately above it in the same file:

```python
    @property
    def result_index(self) -> Index:
        return self.result_index_and_ids[0]

    @property
    def ids(self) -> npt.NDArray[np.intp]:
        return self.result_index_and_ids[1]
```

Both are thin projections of the same pair, and `result_index_and_ids` is `@cache_readonly`, so the
arithmetic runs once per grouper and both halves of the report are served from one computation. That
is why the wrong membership and the wrong totals always agree with each other.

The aggregation reads both, in `pandas/core/groupby/groupby.py`:

```python
        ids = self._grouper.ids
        ngroups = self._grouper.ngroups

        res_mgr = df._mgr.apply(
            aggregator, labels=ids, ngroups=ngroups, **aggregator_kwargs
        )
        res_mgr.axes[1] = self._grouper.result_index
```

`ids` goes in as `labels` and `result_index` becomes the output axis. The summation itself is handed a
label per row and sums by label; it has no way to know a label is wrong. `ngroups` is `len(self.result_index)`,
so it too derives from the same pair.

The membership half of the report comes from `BaseGrouper.groups`, in the same file:

```python
    def groups(self) -> dict[Hashable, Index]:
        ""
        if len(self.groupings) == 1:
            return self.groupings[0].groups
        result_index, ids = self.result_index_and_ids
        values = result_index._values
        categories = Categorical.from_codes(ids, categories=range(len(result_index)))
```

For a single grouping it delegates and never touches the pair; for two it unpacks the same
`result_index_and_ids`. `pandas/core/groupby/generic.py` reads `self._grouper.result_index` and
`self._grouper.ids` at a further eight sites for the Series and DataFrame surfaces.

So the chain is: the user's `.sum()` in `generic.py` / `groupby.py`, reading the cached accessors on
the grouper, which evaluate `result_index_and_ids` in `ops.py`. The symptom appears three files away
from its cause.

## What the earlier repair changed, and why the fault survives it

A repair for this issue was merged shortly before this commit: GH-63961, titled as a regression fix
for groupby with categorical and NA values giving incorrect groups. It is the reason an engineer
reading the tracker concludes the problem is already fixed.

What it added is the `if self.dropna:` restoration quoted above -- at the end of the mixed arm. That
addresses the *reported* symptom on the inputs it was tested against, because for those the corrupted
ids survived to the end of the routine and were overwritten there. What it does not do is stop the
corrupted ids being *used* in between. The positional gather in the sort branch runs first, and a
restoration that happens afterwards cannot unwind a gather that already put a row in the wrong place,
let alone one that raised.

The `index.take(ids)` the restoration fails to protect is itself older than that repair; it entered
with GH-55738. So the sequence is: a positional recode added without sentinel handling, then a
restoration added at the end of the routine rather than at the point of damage, leaving a fix that
reads complete and is not.

The eventual fix, PR #68931, moves the restoration to immediately after the arithmetic and gives the
sort branch a recode table with a `-1` sentinel appended, so a dropped row lands on `-1` instead of on
a real group:

```
-            ids = len(unob_index) * ob_ids + unob_ids
+            ids = len(unob_index) * ob_ids + unob_ids
+            if self.dropna:
+                ids = np.where((ob_ids < 0) | (unob_ids < 0), -1, ids)
...
-                ids = ensure_platform_int(ids)
-                ids = index.take(ids)
+                recode = np.empty(len(index) + 1, dtype=np.intp)
+                recode[:-1] = index
+                recode[-1] = -1
+                ids = recode.take(ids)
...
-            if self.dropna:
-                ids = np.where((ob_ids < 0) | (unob_ids < 0), -1, ids)
```

Its own differential over 1920 generated frames reports 124 cases that raised `IndexError` and now
return the right frame, and 121 that changed silently -- every one of them `sort=False, dropna=True`,
of which 117 were groups in the wrong order and 4 had a duplicated group. That split is the same
two-branch asymmetry described above, measured.

## Why several files must be read

No single file yields the answer.

`pandas/core/groupby/ops.py` holds the target routine, the arithmetic, both branches, the late
restoration, the two helpers that bracket it, the identically named `BinGrouper` override, the two
cached accessors and the `groups` property.

`pandas/core/groupby/groupby.py` holds the aggregation that consumes `ids` as `labels` and
`result_index` as the output axis -- the file an engineer who suspects the summation will read, and
where they will find nothing wrong.

`pandas/core/groupby/generic.py` holds the Series and DataFrame entry points that read the same two
accessors, and is the layer nearest the call the team actually makes.

`pandas/core/arrays/categorical.py` holds the `codes` the third engineer suspects, with its own `-1`
for missing -- correct, and the origin of the marker that the mixed arm destroys rather than the place
it is destroyed.

`pandas/core/apply.py` defines `result_index` three further times, so a tree-wide search for that name
returns hits in a file with no part in this at all.

A reader who stops at the aggregation reports that the arithmetic is correct and has no explanation. A
reader who stops at the tracker reports that GH-63961 already fixed it. A reader who stops at the
categorical array reports that the marker is correct. All three are true statements and none of them
is the answer.
