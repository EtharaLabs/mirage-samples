# Task List

1. ✅ Locate grouping routine
BaseGrouper.result_index_and_ids, pandas/core/groupby/ops.py:756-842
2. ✅ Trace call path + cached accessor
sum->_agg_general->_cython_agg_general->array_func->_cython_operation->has_dropped_na->ids(property)->result_index_and_ids(cache_readonly)
3. ✅ Arithmetic destroying -1
line 811 ids = len(unob_index)*ob_ids+unob_ids
4. ✅ Compare the two branches
CORRECTED: both can raise; else-branch (sort=False) uniquely corrupts result_index via taker -> duplicate labels
5. ✅ BinGrouper twin + dispatch
line 1216; BaseGrouper instance; 1 grouping; no mul/no np.delete
6. ✅ Earlier repair GH 66893
Confirmed by AST: indices differs, result_index_and_ids identical
7. ✅ Reproduce empirically
IndexError + duplicate labels reproduced; mass conserved, no inflated totals found
8. ✅ Verify repo unmodified
git status clean
