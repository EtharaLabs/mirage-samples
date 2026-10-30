"""Hybrid deterministic tests -- generic logic, per-bundle GOLDEN data.

Driven entirely by the GOLDEN block below; nothing else in this file is task-specific.

One layer: process -- what the agent must have READ, from the tool calls in history.
A bundle whose GOLDEN carries no "answer" and no "negatives" scores nothing from the
text of the answer; the rubric does that.

GOLDEN schema:

    {"answer": {                      # answer keys -> expected value, one test each
        "marker":            {"symbol": "OPENDISTRO_...", "weight": 5},
        "marker_file":       {"path": "src/.../ConfigConstants.java", "weight": 3},
        "producer.file":     {"path": "...", "weight": 5},
        "producer.function": {"symbol": "handle", "weight": 5},
        "readers":           {"path_set": ["...", "..."], "weight": 5}},
     "negatives": [                   # penalty tests: pass (penalty applies) when all match
        {"name": "names_the_valve_as_writer", "weight": -3,
         "when": {"producer.file": {"path": "..."}, "producer.function": {"symbol": "invoke"}}}],
     "targets": [                     # process: (file, function|None) the agent must have read
        {"file": "...", "function": "handle"}],
     "symbols": ["OPENDISTRO_..."],   # process: constants the agent must have grepped for
     "process_weights": {"files_opened": 2, "functions_read": 5, "symbols_searched": 2,
                         "answer_grounded": 3, "read_only": 1, "modified_code_penalty": -5}}

The row arrives via HG_OUTPUT_JSONL (first line). make_hybrid.py inlines GOLDEN and
emits the matching test_weights.json, so the shipped test_output.py is self-contained.
It also deletes whole sections that this bundle's GOLDEN cannot populate -- the
answer-identity section when "answer" and "negatives" are both empty, the citation
section unless "cites" is true, the grounding section unless "process_weights" declares
"answer_grounded" -- so no shipped file carries machinery that generates
nothing and would silently revive tests if a key were later filled. The sections are
delimited by SECTION markers in the template; keep them in step when editing it.
"""
from __future__ import annotations

import json
import os
import re

# Per-bundle golden data, from truth.md. Inlined: no companion file.
GOLDEN = {'answer': {},
 'negatives': [],
 'process_weights': {'answer_grounded': 1, 'modified_code_penalty': -5, 'read_only': 1},
 'symbols': ['result_index_and_ids'],
 'targets': [{'file': 'pandas/core/groupby/ops.py',
              'function': 'result_index_and_ids',
              'weight': 5},
             {'file': 'pandas/core/groupby/ops.py', 'function': '_ob_index_and_ids', 'weight': 3},
             {'file': 'pandas/core/groupby/ops.py', 'function': '_unob_index_and_ids', 'weight': 3},
             {'file': 'pandas/core/groupby/ops.py', 'function': 'groups', 'weight': 1},
             {'file': 'pandas/core/groupby/groupby.py', 'function': None, 'weight': 3},
             {'file': 'pandas/core/groupby/generic.py', 'function': None, 'weight': 1},
             {'file': 'pandas/core/arrays/categorical.py', 'function': None, 'weight': 1},
             {'file': 'pandas/core/apply.py', 'function': None, 'weight': 1}]}

_JSONL_ENV = 'HG_OUTPUT_JSONL'


# ------------------------------------------------------------------ row access

class RolloutError(RuntimeError):
    """The rollout could not be read. Distinct from an agent that did nothing."""


def _no_dup(pairs):
    """Duplicate JSON keys mean two answers in one row; last-wins would hide that."""
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f'duplicate key {k!r} in rollout JSON')
        seen[k] = v
    return seen


def _load_row() -> dict:
    """The rollout row, or RolloutError saying which way the input was unusable.

    Absent input is the one tolerated case: no HG_OUTPUT_JSONL and no file means the
    tests were collected outside a harness run, and every process test then fails on
    its own terms. Input that is present but unreadable is a harness fault, and must
    not be reported as "the agent never read anything".

    One row scores one rollout. A second row is as ambiguous as a duplicate key -- both
    are two answers in one file -- so neither is silently resolved by taking the first.
    """
    path = os.environ.get(_JSONL_ENV)
    if not path:
        return {}
    if not os.path.exists(path):
        raise RolloutError(f'{_JSONL_ENV}={path} does not exist')
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = [line for line in fh if line.strip()]
        if not lines:
            raise RolloutError(f'{path} is empty')
        if len(lines) > 1:
            raise RolloutError(f'{path} holds {len(lines)} rows; exactly one is scored')
        row = json.loads(lines[0], object_pairs_hook=_no_dup)
    except OSError as exc:
        raise RolloutError(f'{path} could not be opened: {exc}') from exc
    except ValueError as exc:
        raise RolloutError(f'{path} is not valid JSONL: {exc}') from exc
    if not isinstance(row, dict):
        raise RolloutError(f'{path} row is {type(row).__name__}, not an object')
    return row


_ROW_CACHE = []


def _row() -> dict:
    if not _ROW_CACHE:
        _ROW_CACHE.append(_load_row())
    return _ROW_CACHE[0]


def _absent() -> str:
    """Names the tolerated absent case, so a run with no rollout at all does not read as
    a run in which the agent did nothing."""
    return '' if _row() else f' (no rollout: {_JSONL_ENV} is unset)'


# SECTION answer-text BEGIN
def _answer() -> str:
    a = (_row().get('test_result') or {}).get('answer')
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        return str(a.get('text') or '')
    return ''
# SECTION answer-text END


def _patch():
    p = (_row().get('test_result') or {}).get('git_patch')
    return p if isinstance(p, str) else None


# ------------------------------------------------------------------ process tests

_SRC = r'\.(?:java|kt|go|rs|py|pyi|ts|tsx|js|jsx|mjs|rb|c|cc|cpp|h|hpp|scala|cs|swift|php|proto)'
_FILE = re.compile(r'[\w./+-]*?[\w+-]+' + _SRC + r'\b')
_DISPLAY = re.compile(r"\bsed\s+-n|\bawk\b[^|]*NR|\bcat\s|\bnl\b|\bhead\s|\btail\s"
                      r"|\bgrep\b[^|]*\s-[a-zA-Z]*n[a-zA-Z]*\b|\bless\b|\bbat\b"
                      r"|\bgit\s+show\s")
_SEARCH = re.compile(r'\b(?:grep|rg|ag|ack|git\s+grep)\b')
# A segment that only enumerates paths never shows a file's contents, however it is piped on.
# Anchored at COMMAND position, not anywhere in the string. `\b...\b` matched
# these words inside PATHS: hibernate's
# hql/internal/ast/tree/FromElementFactory.java contains `tree`, so a plain
# `grep -n <fn> <that file>` was classified as a directory listing and its
# output discarded -- the read test failed with the definition sitting in
# the output. Any path component named find/ls/fd/tree/locate/stat hit this.
# Segments are already split on shell operators, so the verb starts a segment.
_LISTING = re.compile(r'^\s*(?:find|ls|git\s+ls-files|fd|tree|locate|stat)\b')
# Output that reports a failure is not file contents, so it cannot ground a read.
# Anchored per line, with at most a short `prog: ` prefix: an unanchored `error:` also
# matches ordinary source -- `except OSError:`, `CommandExecutionError:` -- and threw away
# the display of any file that merely handles an error.
_ERROR_OUT = re.compile(r'^(?:[^\n]{0,60}?: )?(?:No such file or directory|command not found'
                        r'|Permission denied|cannot access|cannot open|Is a directory'
                        r'|unknown revision|Traceback \(most recent call last\))'
                        r'|^(?:fatal|error): ', re.I | re.M)


def _calls():
    hist = _row().get('history') or []
    obs = {e['cause']: str(e.get('content') or '') for e in hist
           if isinstance(e, dict) and e.get('observation') and e.get('cause') is not None}
    out = []
    for e in hist:
        if not (isinstance(e, dict) and e.get('source') == 'agent'):
            continue
        if e.get('action') == 'finish':
            break
        if e.get('action') not in ('run', 'read', 'edit'):
            continue
        a = e.get('args') or {}
        cmd = str(a.get('command') or '') if e['action'] == 'run' else str(a.get('path') or '')
        out.append((e['action'], cmd, obs.get(e.get('id'), '')))
    return out


def _norm_rel(p: str) -> str:
    p = p.replace('\\', '/').strip().strip('\'"')
    while p.startswith('./'):
        p = p[2:]
    return p.rstrip('/')


# Third-party trees that carry their own copy of a name the repository also uses.
_VENDORED = re.compile(r'(?:^|/)(?:vendor|third_party|thirdparty|node_modules|\.venv|'
                       r'site-packages|external|Godeps)(?:/|$)')


def _names_path(text: str, path: str) -> bool:
    """True when `text` names the target by path.

    Only the repository-relative path counts, in full or as a suffix of a longer path.
    A bare basename never counts, however unusual: uniqueness among THIS task's targets
    says nothing about the repository, so `cd components/homeassistant/triggers && cat
    event.py` would otherwise credit a target in components/zwave_js/triggers/ -- the
    decoy the task is built around (final_QC.md G4). A name that carries a directory is
    taken at its word, so service/frontend/api.go never credits a target in
    service/history/api/updateactivityoptions/.
    """
    want = _norm_rel(path)
    want_vendored = _VENDORED.search(want) is not None
    for found in _FILE.findall(text):
        got = _norm_rel(found)
        # A vendored copy is a different file: cortex carries both
        # pkg/compactor/blocks_cleaner.go and a thanos one under vendor/.
        if _VENDORED.search(got) and not want_vendored:
            continue
        if got == want or got.endswith('/' + want):
            return True
    return False


# Shell separators, not just the pipe: `ls target.rs && head -5 README.md` chains a
# display of one file to a mention of another, and crediting the target for it is the
# same false positive as a display verb loose in the command line.
_SEP = re.compile(r'\|\||&&|[|;]')


def _strip_comment(seg: str) -> str:
    """Drop a trailing shell comment.

    A path named only in a comment was never acted on: `cat README.md  # foo/bar.go`
    displays README.md. Quotes are tracked so a searched-for pattern containing "#"
    survives.
    """
    quote = ''
    for i, ch in enumerate(seg):
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '\'"':
            quote = ch
        elif ch == '#' and (i == 0 or seg[i - 1].isspace()):
            return seg[:i]
    return seg


def _segments(cmd: str):
    return [_strip_comment(s) for s in _SEP.split(cmd)]


def _display_segments(cmd: str):
    """Command segments that show a file's own contents, not a listing of names."""
    for seg in _segments(cmd):
        if _DISPLAY.search(seg) and not _LISTING.search(seg):
            yield seg


def _displays_of(path: str):
    """Output of every call that displayed `path` itself AND came back with contents."""
    for action, cmd, out in _calls():
        if not out.strip() or _ERROR_OUT.search(out):
            continue
        if action in ('read', 'edit'):
            if _names_path(cmd, path):
                yield out
            continue
        if any(_names_path(seg, path) for seg in _display_segments(cmd)):
            yield out


def _hit_lines_of(path: str):
    """Lines a recursive search printed for `path`, each still carrying its own prefix.

    `grep -rn 'def x' pkg/` shows the definition from the file itself and labels it with
    the path, which is provenance a bare mention never has. Only such prefixed lines count.
    """
    want = _norm_rel(path)
    for action, cmd, out in _calls():
        if action != 'run' or not out.strip() or _ERROR_OUT.search(out):
            continue
        if not any(_DISPLAY.search(seg) and not _LISTING.search(seg) for seg in _segments(cmd)):
            continue
        for line in out.splitlines():
            head = line.split(':', 1)[0] if ':' in line else ''
            if head and (_norm_rel(head) == want or _norm_rel(head).endswith('/' + want)):
                yield line


# Line-numbering prefixes: grep -n ("path:12:"), its context lines ("path-12-"), and
# cat -n / nl, which indent the number and follow it with a tab.
_PRE = r'^[ \t]*(?:(?:[^\n]*?[-:])?\d+[-:\t ])?[ \t]*'


def _definition_res(fn: str, owner: str):
    """Definition forms for `fn`. A bare call site `fn(` must never satisfy these."""
    f = re.escape(fn)
    pats = [_PRE + r'(?:async[ \t]+)?def[ \t]+' + f + r'[ \t]*\(',
            _PRE + r'func[ \t]+' + f + r'[ \t]*[(\[]',
            _PRE + r'func[ \t]*\([^)\n]*\)[ \t]*' + f + r'[ \t]*[(\[]',
            _PRE + r'(?:pub[ \t]+)?(?:async[ \t]+)?fn[ \t]+' + f + r'[ \t]*[(<]',
            _PRE + r'(?:export[ \t]+)?(?:async[ \t]+)?function[ \t]+' + f + r'[ \t]*\(',
            # Match the signature START, not the whole header. Requiring
            # `(...) {` on ONE line assumed Java never wraps a parameter list;
            # hibernate does routinely, e.g.
            #   public void addEntityAtRevisionRestriction(GlobalConfiguration globalCfg,
            #           QueryBuilder rootQueryBuilder, String revisionProperty,
            # so every wrapped declaration was unmatchable and the oracle scored
            # 0.0 on 4 of 4 read tests with the definitions plainly in its output.
            # The leading modifier keyword is what separates a declaration from a
            # call site; the trailing brace never added safety, only brittleness.
            # Modifiers OPTIONAL, return type REQUIRED. Requiring a modifier
            # assumed every declaration is public/private/protected; hibernate's
            # `RelationQueryGenerator build(...)` and `FromElement
            # addFromElement()` are package-private and matched nothing. The
            # return type is what separates a declaration from a call site --
            # `builder.build(x)` and `return this.build(x)` have no type token
            # before the name, and the required whitespace stops `obj.build(`
            # matching.
            _PRE + r'(?:(?:public|private|protected|static|final|abstract'
            r'|synchronized|default|native|strictfp)[ \t]+)*'
            r'[\w<>\[\],.?]+[ \t]+' + f + r'[ \t]*\(',
            # A GOLDEN target's `function` is sometimes a TYPE, not a routine:
            # deno's LoaderHookRegistry is `pub struct LoaderHookRegistry {`.
            # Every form above is callable-shaped, so such a target could never
            # be satisfied however completely the agent displayed the file --
            # test_read_LoaderHookRegistry_in_module_hooks failed on 6,412 chars
            # of output whose first line was the declaration itself.
            _PRE + r'(?:pub[ \t]+)?(?:export[ \t]+)?'
            r'(?:struct|enum|trait|impl|type|class|interface)[ \t]+' + f + r'\b',
            # Rust macros are declared `macro_rules! name {`, which no
            # fn/type form covers. swc's `srcmap` is one, so its read test
            # could never pass -- the declaration was the first line of the
            # oracle's own grep output.
            _PRE + r'macro_rules![ \t]*!?[ \t]*' + f + r'\b']
    return [re.compile(p, re.M) for p in pats]


def _owner_res(fn: str, owner: str):
    """The owning type, either as a Go receiver on the definition or as a class nearby."""
    f, o = re.escape(fn), re.escape(owner)
    return (re.compile(_PRE + r'func[ \t]*\([^)\n]*\b' + o + r'\b[^)\n]*\)[ \t]*' + f + r'[ \t]*[(\[]', re.M),
            re.compile(_PRE + r'(?:class|type|struct|impl|interface)[ \t]+' + o + r'\b', re.M))


def _stem(path: str) -> str:
    """Test-name stem for a target: its parent directory and its basename.

    A bare basename is ambiguous in every tree that repeats module filenames -- this
    repository holds three postgres.rs and two mod.rs -- so the generated name carries
    the directory that tells them apart.
    """
    parts = [p for p in path.replace('\\', '/').rstrip('/').split('/') if p]
    base = parts[-1].rsplit('.', 1)[0]
    parent = parts[-2] if len(parts) > 1 else ''
    return re.sub(r'\W', '_', f'{parent}_{base}' if parent else base).strip('_')


_ANY_OWNER = re.compile(_PRE + r'(?:class|type|struct|impl|interface)[ \t]+(\w+)', re.M)
# `func (i *someIter) Name(` -- the receiver is on the definition line itself.
_GO_RECEIVER = re.compile(_PRE + r'func[ \t]*\([^)\n]*\)[ \t]*\w+[ \t]*[(\[]')


def _owner_owns_definition(out: str, defn, owner: str, recv, strict: bool = True) -> bool:
    """True when `out` shows a definition that BELONGS TO `owner`.

    With strict=False the owner only has to not CONTRADICT: a definition whose nearest
    enclosing declaration names a different owner still fails, but one shown with no
    enclosing declaration in the output passes, so reading just the method counts.

    The owner has to hold on the definition line itself. Testing it anywhere in the
    output credits the wrong routine: a display of join_iters.go shows
    `func (i *joinIter) Next(` and `type fullJoinIter struct` together, which would
    otherwise pass fullJoinIter.Next without that method ever being shown. Go carries
    the receiver on the line; Python and Java carry it as the nearest class above.
    """
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if not any(p.search(line) for p in defn):
            continue
        if not owner:
            return True
        if recv is not None and recv.search(line):
            return True
        # A Go definition carries its receiver on its own line, so a receiver-bearing
        # line that does not name this owner belongs to a different type -- full stop.
        # Consulting the nearest `type X struct` above it would credit fullJoinIter for
        # `func (i *crossJoinIterator) Next(` merely because line 417 was in the same
        # output (final_QC.md G4).
        if _GO_RECEIVER.search(line):
            continue
        for j in range(i - 1, -1, -1):          # nearest enclosing declaration wins
            m = _ANY_OWNER.search(lines[j])
            if m:
                if m.group(1) == owner:
                    return True
                break
        else:                                   # no enclosing declaration in this output
            if not strict:
                return True
    return False


def _definition_displayed(path: str, qualified: str, anchor: str = '') -> bool:
    """True when the definition of `qualified` was shown from `path` itself.

    One predicate serves both layers: a routine is established by the same evidence
    whether a read test asks for it or the answer cites it.

    `owner` is corroboration, not a requirement: the path already pins the file, and
    demanding the `class X` line in the SAME output failed a correct targeted read of
    the method alone (final_QC.md G3 determinism). It is still used to reject a
    definition the output shows belongs to a DIFFERENT owner.

    `anchor`, when the golden target carries one, is a literal the same output must
    also contain. It separates a real definition from a same-named stub -- the two
    empty `@overload` declarations above build_from_crawler, or the abstract
    async_validate_trigger_config methods above the module-level one (G4).
    """
    fn = qualified.split('.')[-1]
    owner = qualified.split('.')[-2] if '.' in qualified else ''
    defn = _definition_res(fn, owner)
    recv, klass = _owner_res(fn, owner) if owner else (None, None)
    for out in _displays_of(path):
        if anchor and anchor not in out:
            continue
        if _owner_owns_definition(out, defn, owner, recv, strict=False):
            return True
    if anchor:
        return False            # a grep hit line cannot carry the anchor's context
    for line in _hit_lines_of(path):
        if any(p.search(line) for p in defn) and (not owner or recv.search(line)):
            return True
    return False


def _make_target_test(t: dict):
    """One test per golden target, named for it: what THIS task required the agent to read."""
    path = t['file']
    stem = _stem(path)
    qualified = (t.get('function') or '')
    anchor = t.get('anchor') or ''
    fn = qualified.split('.')[-1]
    if fn:
        def test():
            assert _definition_displayed(path, qualified, anchor), \
                (f'the definition of {qualified} was never displayed from {path}'
                 + (f' with {anchor!r} in the same output' if anchor else '') + _absent())
        test.__name__ = 'test_read_' + re.sub(r'\W', '_', fn) + '_in_' + stem
        test.__doc__ = f'The agent displayed the definition of {qualified or fn} in {path}.'
    else:
        def test():
            outs = [o for o in _displays_of(path) if not anchor or anchor in o]
            assert outs, (f'{path} was never displayed before finish'
                          + (f' with {anchor!r} in the output' if anchor else '') + _absent())
        test.__name__ = 'test_opened_' + stem
        test.__doc__ = (f'The agent displayed {path} (contents shown, not merely listed)'
                        + (f', including {anchor}.' if anchor else '.'))
    return test


for _t in GOLDEN.get('targets', []):
    _fn = _make_target_test(_t)
    globals()[_fn.__name__] = _fn


def _has_path_operand(seg: str) -> bool:
    """True when the search names a file or directory of its own to read."""
    for tok in seg.split():
        if tok.startswith('-'):
            continue
        tok = tok.strip('\'"')
        if tok in ('.', './') or '/' in tok or _FILE.search(tok):
            return True
    return False


def _search_segments(cmd: str):
    """Search segments that read the tree.

    A search naming no path of its own, piped out of a listing, filters that listing's
    output: `ls pkg/foo/ | grep SYMBOL` searches file names, not code, and must not
    stand in for having searched the tree for SYMBOL.
    """
    parts, seps = _SEP.split(cmd), _SEP.findall(cmd)
    for k, seg in enumerate(parts):
        if not _SEARCH.search(seg):
            continue
        if k and seps[k - 1] == '|' and not _has_path_operand(seg) \
                and _LISTING.search(parts[k - 1]) and not _DISPLAY.search(parts[k - 1]):
            continue
        yield seg


def _search_patterns():
    """Arguments of search calls. Text elsewhere in the command line does not count."""
    pats = []
    for action, cmd, _ in _calls():
        if action != 'run':
            continue
        for seg in _search_segments(cmd):
            pats += re.findall(r'["\']([^"\']{3,})["\']', seg)
            for tok in re.findall(r'(?<![\w/.\'"-])([A-Za-z_][\w.]{2,})(?![\w/])', seg):
                if tok in ('grep', 'rg', 'ag', 'ack', 'git', 'egrep', 'fgrep') or _FILE.fullmatch(tok):
                    continue
                pats.append(tok)
    return pats


def _make_symbol_test(sym: str):
    """One test per golden constant: it was passed to a search call.

    The pattern must contain the whole symbol -- `rg 'PerNSWorkerTaskQueue\b'` and
    `grep -rn PerNSWorkerTaskQueue .` both count. A pattern the symbol merely contains
    ("Worker", "Queue") does not: that is a different search.
    """
    def test():
        assert any(sym in p for p in _search_patterns()), f'never searched for {sym}' + _absent()
    test.__name__ = 'test_searched_' + re.sub(r'\W', '_', sym)
    test.__doc__ = f'The agent searched the tree for {sym}.'
    return test


for _sym in GOLDEN.get('symbols', []):
    _fn = _make_symbol_test(_sym); globals()[_fn.__name__] = _fn


# SECTION grounding BEGIN
# ------------------------------------------------------------------ citation grounding

def _cited_paths(text: str):
    """Repository-relative source paths the answer points at, in order, without repeats."""
    out = []
    for found in _FILE.findall(text):
        p = _norm_rel(found)
        if p and p not in out:
            out.append(p)
    return out


def _cited_targets(text: str):
    """Golden targets whose routine the answer names. A name it never uses it never claims."""
    out = []
    for t in GOLDEN.get('targets', []):
        fn = (t.get('function') or '').split('.')[-1]
        if fn and re.search(r'\b' + re.escape(fn) + r'\b', text):
            out.append(t)
    return out


def _grounding_base_count(paths):
    """Basename census over everything in play: the targets, and the paths the answer
    itself cites. A basename two distinct paths share can stand in for neither, so a
    cited a/x.go is never grounded by a display of b/x.go."""
    known = {t['file'].replace('\\', '/').rstrip('/') for t in GOLDEN.get('targets', [])}
    known |= {p for p in paths if '/' in p}
    counts = {}
    for p in known:
        b = p.split('/')[-1]
        counts[b] = counts.get(b, 0) + 1
    return counts


def test_answer_grounded():
    """Every location the answer cites was opened, to the standard the read tests use.

    This asks nothing about WHICH locations the answer picks -- that is what the written
    criteria judge. It asks only that each one rest on a display of that file, so a path
    glimpsed in a listing, in an error message, or in the agent's own command line cannot
    be cited as though it had been read, and a routine cannot be named without its
    definition ever having been shown from the file the answer puts it in.
    """
    ans = _answer()
    paths = _cited_paths(ans)
    targets = _cited_targets(ans)
    assert paths or targets, 'the answer cites no file and no routine' + _absent()

    counts = _grounding_base_count(paths)
    ungrounded = [p for p in paths if not any(True for _ in _displays_of(p))]
    assert not ungrounded, ('the answer cites ' + ', '.join(ungrounded)
                            + ' but their contents were never displayed' + _absent())

    unread = [f"{t['function']} in {t['file']}" for t in targets
              if not _definition_displayed(t['file'], t['function'])]
    assert not unread, ('the answer names ' + ', '.join(unread)
                        + ' but the definition was never displayed from that file' + _absent())
# SECTION grounding END


# ------------------------------------------------------------------ patch tests

def _patch_modifies_source():
    """True = source changed; False = clean; None = no patch recorded, or unreadable.

    Clean means a patch that is present and empty, or one whose diff structure is there
    with nothing added or removed. Text that is neither -- a harness that stored a status
    message where the patch belongs -- is unreadable, and must not be credited as clean:
    that would award read_only for a rollout nobody checked.
    """
    p = _patch()
    if p is None:
        return None
    structured = False
    for line in p.splitlines():
        if line.startswith(('diff --git', 'rename ', 'new file', 'deleted file')):
            return True
        if line.startswith(('index ', '--- ', '+++ ', '@@')):
            structured = True
        elif line[:1] and line[0] in '+-':
            return True
    return False if structured or not p.strip() else None


def test_modified_code_penalty():
    """NEGATIVE: passes -- penalty applies -- only when the patch changes source."""
    assert _patch_modifies_source() is True
