A reporting team using the dataframe library in this checkout has filed one ticket that bundles four pipelines whose results are quietly wrong. Nothing in the pipelines raises an error or a warning; they return frames and numbers, just not the right ones. The team does not know whether the four share a cause.

Pipeline A, a report sorted by an ordered tier.

```python
tier = pd.CategoricalDtype(["gold", "silver", "bronze"], ordered=True)
idx = pd.MultiIndex.from_product([["bronze", "gold", "silver"], [1, 2]], names=["tier", "quarter"])
report = pd.DataFrame({"revenue": [10, 11, 20, 21, 30, 31]}, index=idx)
report.index = report.index.set_levels(report.index.levels[0].astype(tier), level="tier")
```

The team expects `report.sort_index()` to list the tiers as gold, silver, bronze. The rows come back unchanged, bronze, bronze, gold, gold, silver, silver. `sort_index(level="tier")` gives the same unchanged order, and `sort_index(ascending=False)` gives silver, gold, bronze, the alphabetical order reversed, instead of bronze, silver, gold. `report.index.is_monotonic_increasing` is `True`. Making the dtype unordered does not help. The same rows in another starting order, for example with the gold rows first or with all rows reversed, sort correctly. So does a frame built with `set_index(["tier", "quarter"])` from a column of this dtype, a one-level index of this dtype, and `reset_index().sort_values(["tier", "quarter"])`.

Pipeline B, a wide table stacked to long form.

```python
wide = pd.DataFrame({"units": [5, 7, 9], "returns": [1, 0, 2]}, index=pd.Index(["north", np.nan, "south"], name="region"))
long = wide.stack()
```

`list(long.index)` holds the entries `(nan, "units")` and `(nan, "returns")`, yet `long.loc[(np.nan, "units")]` raises `KeyError`, and so do the same lookup with `None` and `long.xs(np.nan, level="region")`. `long.index.isin([(np.nan, "units"), ("south", "units")])` marks only the south row. `long.loc[("north", "units")]` is 5, and `long.groupby(level="region", dropna=False).sum()` gives the missing region its right total of 7. The same three regions stacked from a column level, a frame with columns `pd.MultiIndex.from_arrays([["units"] * 3, ["north", np.nan, "south"]], names=[None, "region"])` and one row `"w1"`, stacked with `stack(level="region")`, fail in the same way on `.loc[("w1", np.nan), "units"]`. Lookups of the missing region succeed when the same long index is built with `pd.MultiIndex.from_tuples`, when the wide frame already has a two-level index of region and year before the stack, and when the long form is made with `reset_index().melt(...)` followed by `set_index`.

Pipeline C, store ratios where not-a-number is kept apart from missing.

```python
pd.set_option("future.distinguish_nan_and_na", True)
num = pd.Series([0.0, 0.0, 3.0, 0.0, 2.0], dtype="Float64")
den = pd.Series([0.0, 0.0, 1.0, 0.0, 1.0], dtype="Float64")
df = pd.DataFrame({"store": ["a", "a", "b", "c", "c"], "ratio": num / den})
```

`ratio` is `[nan, nan, 3.0, nan, 2.0]`, with not-a-number values rather than missing ones. `df.groupby("store")["ratio"].max()` gives `-inf` for store a, and `min()` gives `inf`. `cummax()` gives `[-inf, -inf, 3.0, -inf, 2.0]` and `cummin()` gives `inf` in the same places. For store c, `sum()`, `mean()` and `first()` give not-a-number, but `max()` and `min()` give 2.0. The same `-inf` appears from `max(skipna=False)`, from `resample("2D").max()` over a daily index, and from a `groupby(...).max()` over a `float64[pyarrow]` column holding not-a-number values. No infinity appears with a plain `float64` column, with the option left off, from the same values reduced without grouping, from `rolling(2).max()`, or from `mean`, `sum` and `first`.

Pipeline D, a frame whose column label appears twice.

```python
inv = pd.DataFrame([[1, 2], [3, 4], [5, 6]], columns=["qty", "qty"])
inv["qty"] = pd.array([10, 20, 30], dtype="Int64")
inv.iloc[0, 0] = 99
```

Both `qty` columns now show 99 in the first row, though only the first column was written. `inv.iloc[0, 1] += 1` and `inv.iloc[:, 0] = inv.iloc[:, 0] * 2` likewise change both columns. The same happens with a `"string"` array, with a `pd.Categorical`, and with two-level columns `("qty", "a")` and `("qty", "b")` assigned through the key `"qty"`. With columns `pd.DatetimeIndex(["2024-01-31", "2024-02-29", "2025-01-31"])`, assigning an `Int64` array through the key `"2024"` ties the two 2024 columns together in the same way, while assigning a NumPy array or the scalar 7 through the same key raises `ValueError: Got 2 positions but value has 1 columns.` The two `qty` columns stay independent when the assigned value is a NumPy array, an `Int64` `pd.Series`, or a timezone-aware datetime array, and assigning one `Int64` array to two differently named columns in two statements also keeps them independent.

Work out from the actual source in this checkout what is wrong, rather than from release notes, the tracker, or what you recall of this library. State how many distinct root causes there are and which pipeline or pipelines each one explains. For each root cause: name the routine where the wrong decision is made and its repository-relative file path; if that decision is made by a helper, list every routine that calls the helper, and if it is repeated inline in several places, name every one of them; say exactly what the decision is based on and why it is wrong for the reported inputs, including why each variant the team found harmless behaves; trace the path from the call the team makes to that routine; name the routines downstream that trust what it decided, and explain how each reported wrong answer comes out of them; and propose the smallest repair at the point of the decision.

Leave the repository exactly as you found it and modify no files inside it. Write your full explanation to `/workspace/answer.md`, outside the checkout, as soon as you have a first version, keep that file up to date as you learn more, and give the same explanation as your final message.
