An analytics team using the dataframe library in this checkout has filed one ticket that bundles four steps of its reporting job whose results are quietly wrong. Most of them raise no error and no warning; they return frames and series of the expected shape, just with the wrong rows or the wrong dtypes. The team does not know whether the four share a cause.

Step A, lookups by tuple keys on a two-level index.

```python
mi = pd.MultiIndex.from_tuples([("a", "b"), ("c", "d"), ("b", np.nan)])
s = pd.Series([1, 2, 3], index=mi)
keys = pd.Index([("a", "b"), ("a", "b", "c")], tupleize_cols=False)
s.reindex(keys)
```

The second key has three parts and cannot be an entry of a two-level index, so the team expects `[1, nan]`. The result is `[1, 1]`: the three-part key picks up the row `("a", "b")`. `mi.get_indexer(keys)` gives `[0, 0]`, `s.loc[[("a", "b", "c")]]` returns the value 1, and `DataFrame.reindex` and `s.reindex([("a", "b"), ("a", "b", "c")])` with a plain list behave the same way. With the keys `[("a", "b", "c"), ("c", "d", "e")]`, `s.reindex` gives `[1, 2]` and `get_indexer` gives `[0, 1]`. Keys whose first entry is shorter fail confusingly: `mi.get_indexer` raises `IndexError: tuple index out of range` for `[("a", "b"), ("b",)]` and `AssertionError: Length of new_levels (2) must be <= self.nlevels (1)` for `[("b",), ("a", "b")]`. `pd.MultiIndex.from_tuples(np.array([("a", "b"), ("a", "b", "c")], dtype=object))` gives the entries `("a", "b")` twice, and so does `pd.Index([1, 2]).map(lambda x: ("a", "b") if x == 1 else ("a", "b", "c"))`. Keys of the right length behave, `s.loc[("a", "b", "c")]` with a single tuple raises `IndexingError: Too many indexers`, and `mi.isin([("a", "b", "c")])` raises a `ValueError` that names the wrong length.

Step B, in-place arithmetic with a partner that has extra labels.

```python
x = pd.Series([1, 2, 3])
x += pd.Series(10, index=range(4))
```

The partner has one label `x` does not have. The team expects `x` to stay `int64` and become `[11, 12, 13]`. It becomes `[11.0, 12.0, 13.0]` with dtype `float64`. `*=` does the same, as do `df["a"] += pd.Series(10, index=range(4))` on an integer column and `df += other_df` where `other_df` has an extra row; the partner's label order does not matter. On a frame with an integer column `a` and a boolean column `b`, `df &= other_df` with an extra row raises `TypeError: unsupported operand type(s) for &: 'float' and 'int'`. `x` stays `int64` when the partner has exactly the labels of `x`, an `Int64` series stays `Int64` with the right values, and a boolean series combined with `|=` stays boolean. The team accepts that `x + partner` without assignment has four rows with a missing value at label 3, and that labels of `x` missing from the partner become missing.

Step C, comparing two frames.

```python
left = pd.DataFrame({"a": [1567808378753000000, 1567808378753000000], "b": [0, 0]})
right = pd.DataFrame({"a": [1567808378753274000, 1567808378753000000], "b": [0, 0]})
left.compare(right)
```

Only the first row differs, so the team expects one row with the two exact integers. The result has dtype `float64` and shows `1.567808378753e+18` and `1.567808378753274e+18`, which are not the original integers. Two `uint64` values `2**63 + 1` and `2**63 + 3` compared the same way come back as the same float, so the reported difference is invisible, and two boolean frames come back with dtype `object`. `Series.compare` behaves the same way. The integers are kept with `keep_equal=True`, when every row differs, for `Int64` columns, and for datetime columns; with `keep_shape=True` the team expects missing values in the equal rows and accepts `float64` there.

Step D, pivoting several value columns at once.

```python
df = pd.DataFrame({"idx": [0, 1, 0, 1], "col": ["a", "a", "b", "b"], "ints": [10, 20, 30, 40], "floats": [0.1, 0.2, 0.3, 0.4], "strs": ["A", "B", "C", "D"]})
df.pivot(index="idx", columns="col", values=["ints", "floats"])
```

The team expects the two `ints` columns to stay `int64`. All four columns come back as `float64`. With `values=["ints", "strs"]` the `ints` columns come back as `object`, and `pd.pivot` behaves the same way as the method. The `ints` columns stay `int64` with `values="ints"`, with `values=["ints"]`, when `values` is left out, with `pivot_table(..., aggfunc="first")`, and with `set_index(["idx", "col"])[["ints", "floats"]].unstack("col")`.

Work out from the actual source in this checkout what is wrong, rather than from release notes, the tracker, or what you recall of this library. State how many distinct root causes there are and which step or steps each one explains. For each root cause: name the routine where the wrong decision is made and its repository-relative file path; if that decision is made by a helper, list every routine that calls the helper, and if it is repeated inline in several places, name every one of them; say exactly what the decision is based on and why it is wrong for the reported inputs, including why each variant the team found harmless behaves; trace the path from the call the team makes to that routine; name the routines downstream that trust what it decided, and explain how each reported wrong answer comes out of them; and propose the smallest repair at the point of the decision.

Leave the repository exactly as you found it and modify no files inside it. Write your full explanation to `/workspace/answer.md`, outside the checkout, as soon as you have a first version, keep that file up to date as you learn more, and give the same explanation as your final message.
