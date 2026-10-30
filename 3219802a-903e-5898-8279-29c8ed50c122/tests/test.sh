#!/bin/bash
# Deterministic channel for this bundle -- reproducible offline.
#
# Mirrors evaluation/grading/criteria.py: same pytest flags, same outcome
# regex, same PASS set, same weighting. The rubric is judged separately
# (it needs an LLM and is not reproducible); this file scores only pytest.
set -uo pipefail

TRAJECTORY="${HG_TRAJECTORY:-/logs/agent/trajectory.json}"
ANSWER_FILE="${HG_ANSWER_FILE_IN:-/logs/agent/answer.md}"
PATCH="${HG_PATCH:-/logs/artifacts/agent.patch}"
REWARD="${HG_REWARD_OUT:-/logs/verifier/reward.json}"
TESTS_DIR="${HG_TESTS_DIR:-/tests}"
mkdir -p "$(dirname "${REWARD}")" /logs/verifier
[ -f "${PATCH}" ] || : > "${PATCH}"

python3 - <<'PYEOF'
from __future__ import annotations   # extract.py's spliced functions annotate
# `str | Path`, which 3.9 evaluates at def time and rejects with "unsupported operand
# type(s) for |". The image pins 3.12, but the README invites replay on the host,
# and a host python3 is routinely 3.9 -- this machine's is. test_output.py already
# carries the import; this file did not, so the bundle failed to score itself.
import json, os, pathlib, re, subprocess, sys
from pathlib import Path   # extract.py's functions are spliced in below and use it
from typing import Any

AGENT_SOURCE = "agent"

_TEXT_KEYS = ("text", "content", "value")

def _part_text(part: Any) -> str:
    """Text of one ATIF content part, which may be a bare string or a dict."""
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        for key in _TEXT_KEYS:
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""

def message_text(message: Any) -> str:
    """Flatten an ATIF `message`, which is `str | list[ContentPart]`.

    Parts are joined rather than first-wins: a model that emits its prose in
    several content blocks would otherwise be graded on its opening sentence.
    """
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = [t for t in (_part_text(p) for p in message) if t.strip()]
        return "\n".join(parts)
    return _part_text(message)

def answer_from_events(events_dir: str | Path) -> str:
    """The answer as the `finish` action states it, or "" when there is none.

    Read-only families answer in prose and then keep working -- verifying the
    tree is clean, re-checking a file -- so the LAST agent message is routinely a
    sign-off, not the answer. Measured on 7c9f9c14 run-01: the analysis was 8,704
    chars at step 44 and the finish action's `final_thought` 5,784, while the last
    agent message was 172 chars of "the working tree is clean, nothing was
    written to disk". Grading that sign-off scored 1 of 45 rubric criteria on a
    run whose actual answer named the right routine -- rubric 0.0116 for an
    answer that was essentially correct.

    Mirrors evaluation.utils.shared.extract_final_answer, which solves this for
    the rollout path and documents the same failure. It cannot be reused
    directly: that one walks OpenHands `state.history`, this one has the raw
    event files.

    `outputs` is deliberately not read -- it was `{}` on the measured run --
    and neither is `thought`: combine_thought() builds it as
    "<reasoning_content>\\n<content>", so the model's private thinking would lead
    the graded answer. Reasoning is graded in the judge's trajectory digest, not
    as the answer.
    """
    d = Path(events_dir)
    if not d.is_dir():
        return ""

    def _key(p: Path) -> tuple[int, str]:
        try:
            return (int(p.stem), p.stem)
        except ValueError:
            return (1 << 30, p.stem)

    for f in sorted(d.glob("*.json"), key=_key, reverse=True):
        try:
            ev = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(ev, dict) or ev.get("action") != "finish":
            continue
        args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
        text = args.get("final_thought")
        if isinstance(text, str) and text.strip():
            return text
    return ""

def answer_from_trajectory(trajectory_path: str | Path) -> str:
    """The agent's final prose answer, or "" when the trajectory has none.

    Walks backwards so the LAST agent turn wins. Tool-call steps carry no
    message and are skipped, which is why this cannot simply take `steps[-1]`:
    a run that ends on a tool call would otherwise grade as blank.

    NOTE: on read-only families the last agent turn is often a sign-off rather
    than the answer -- see answer_from_events, which is preferred whenever the
    event stream survived.
    """
    path = Path(trajectory_path)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return ""
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return ""
    for step in reversed(steps):
        if not isinstance(step, dict) or step.get("source") != AGENT_SOURCE:
            continue
        text = message_text(step.get("message"))
        if text.strip():
            return text
    return ""

def find_events_dir(base: str | Path) -> Path | None:
    """OpenHands' own event directory inside a trial, if it survived.

    Laid out as <agent logs>/sessions/<session-id>/events/<n>.json.
    """
    root = Path(base)
    if not root.exists():
        return None
    for cand in sorted(root.glob("sessions/*/events")):
        if cand.is_dir():
            return cand
    for cand in sorted(root.glob("**/sessions/*/events")):
        if cand.is_dir():
            return cand
    return None

def history_from_events(events_dir: str | Path) -> list[dict[str, Any]]:
    """OpenHands' raw event stream, verbatim -- this IS `history`.

    The process tests read row['history'] as OpenHands events, which is exactly
    what these files already are: an action event {source, action, args, id} and
    an observation event {observation, cause, content}. So nothing is converted
    here; the files are returned in id order and that is the whole function.

    Preferred over history_from_trajectory: Harbor's ATIF is a projection of this
    same data (renamed fields, action and observation merged into one step), and
    reconstructing events from it is a second conversion that has silently lost
    tool output twice -- once on the tool-call field name, once on the nested
    observation shape. Reading the source avoids the round trip entirely.
    """
    d = Path(events_dir)
    if not d.is_dir():
        return []

    def _key(p: Path) -> tuple[int, str]:
        try:
            return (int(p.stem), p.stem)
        except ValueError:
            return (1 << 30, p.stem)

    events: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.json"), key=_key):
        try:
            ev = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events

def _observation_text(obs: Any, tool_call_id: Any = None) -> str:
    """Tool output for one call, whatever shape the adapter recorded it in.

    OpenHands nests results and keys them back to the call:
        {"results": [{"source_call_id": "toolu_...", "content": "..."}]}
    so a step with several calls has several results and only the matching one
    belongs to this call. Other adapters put the text flat on the observation.
    Returning "" here is not harmless: the process tests read this string, so a
    missed shape scores every one of them 0 and looks like a bad agent.
    """
    if obs is None:
        return ""
    if isinstance(obs, str):
        return obs
    if not isinstance(obs, dict):
        return str(obs)

    results = obs.get("results")
    if isinstance(results, list):
        matched = [r for r in results if isinstance(r, dict)
                   and (tool_call_id is None or r.get("source_call_id") == tool_call_id)]
        if not matched:
            matched = [r for r in results if isinstance(r, dict)]
        return "\n".join(str(r.get("content") or r.get("text") or "") for r in matched)

    for key in ("content", "output", "text", "stdout"):
        if obs.get(key):
            return str(obs[key])
    return ""

def history_from_trajectory(trajectory_path: str | Path) -> list[dict[str, Any]]:
    """ATIF steps -> the OpenHands event stream `test_output.py` reads.

    The process tests ask what the agent DID: which files it displayed, which
    constants it grepped. They read `row['history']` as OpenHands events --
    an action event {source, action, args, id} followed by an observation event
    {observation, cause, content} carrying that tool's output.

    ATIF already carries both (Step.tool_calls / Step.observation); nothing here
    invents evidence, it only renames fields. Without this the row has no
    history at all and every process test fails regardless of what the agent
    did -- which is why an oracle scored 0 and a blank answer outscored it.
    """
    try:
        data = json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    events: list[dict[str, Any]] = []
    next_id = 1
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for call in step.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            args = call.get("arguments") or call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            # OpenHands names the field function_name; other adapters have used
            # name/function. Accept all three -- reading the wrong one silently
            # yields no tool output and every process test fails.
            name = str(call.get("function_name") or call.get("name")
                       or call.get("function") or "").lower()
            # Map the tool onto the three actions the tests recognise. Anything
            # that runs a shell command is 'run'; a file viewer is 'read'.
            if name in ("read", "view", "open", "str_replace_editor", "file_read"):
                action = "read"
            elif name in ("edit", "write", "str_replace", "file_edit"):
                action = "edit"
            else:
                action = "run"
            events.append({
                "id": next_id, "source": "agent", "action": action,
                "args": args if isinstance(args, dict) else {"command": str(args)},
            })
            events.append({"observation": action, "cause": next_id,
                            "content": _observation_text(step.get("observation"),
                                                         call.get("tool_call_id"))})
            next_id += 1
    return events

TRAJ = os.environ.get("HG_TRAJECTORY", "/logs/agent/trajectory.json")
ANSWER_FILE = os.environ.get("HG_ANSWER_FILE_IN", "/logs/agent/answer.md")
PATCH = os.environ.get("HG_PATCH", "/logs/artifacts/agent.patch")
REWARD = os.environ.get("HG_REWARD_OUT", "/logs/verifier/reward.json")
TESTS = pathlib.Path(os.environ.get("HG_TESTS_DIR", "/tests"))
WORK = pathlib.Path("/tmp/teresa-verify"); WORK.mkdir(parents=True, exist_ok=True)


def read(p):
    try:
        return pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# The finish action first. Read-only families answer in prose and then keep
# working -- verifying the tree is clean, re-checking a file -- so the LAST agent
# message is routinely a sign-off. On this corpus the analysis ran to 8,704 chars
# while the trailing message was 172 chars of "the working tree is clean"; grading
# that scored 1 of 45 rubric criteria and tripped test_answer_grounded's "the
# answer cites no file or routine". The host grader reads the finish action, so
# the bundle must too or it cannot reproduce its own score.
_ev = find_events_dir(os.path.dirname(TRAJ) or ".")
answer = answer_from_events(_ev) if _ev else ""
if not answer.strip() and os.path.exists(TRAJ):
    answer = answer_from_trajectory(TRAJ)
if not answer.strip():
    answer = read(ANSWER_FILE)

# A submission with no answer is worth zero. Scoring it would let the grounding
# tests ("if the answer names X, a tool output showed X") pass VACUOUSLY, so an
# agent that produced nothing outscores one that answered perfectly.
if not answer.strip():
    # Two keys here too -- see the write below: a lone key is promoted to a
    # primary reward, and a lone 0/1 value feeds pass@k.
    pathlib.Path(REWARD).write_text(
        json.dumps({"pytest": 0.0, "rubric_scored": 0}) + chr(10))
    print("[info] no answer -> 0")
    raise SystemExit(0)

row = {
    "instance_id": os.environ.get("HG_INSTANCE_ID", ""),
    "test_result": {"answer": {"text": answer}, "git_patch": read(PATCH)},
}
# OpenHands' raw event files ARE row['history'] -- same shape, no conversion.
# Harbor's ATIF is a projection of them, so remapping it back is a second
# conversion and strictly lossier; use it only when the events are absent.
events = find_events_dir(os.path.dirname(TRAJ) or ".")
history = history_from_events(events) if events else []
src = "events"
if not history and os.path.exists(TRAJ):
    history = history_from_trajectory(TRAJ)
    src = "trajectory(atif)"
if history:
    row["history"] = history
    print("[info] history: %d events from %s" % (len(history), src))
row_path = WORK / "output.jsonl"
row_path.write_text(json.dumps(row, default=str) + chr(10), encoding="utf-8")

target = TESTS / "test_output.py"
if not target.exists():
    print("[FATAL] missing", target, file=sys.stderr)
    raise SystemExit(2)

# Flags, env and parsing mirror evaluation/grading/criteria.py exactly. Plugin
# autoload is off so a stray plugin cannot crash collection and score 0 like a
# real failure; HG_ANSWER_FILE/HG_PATCH_FILE are dropped so an operator's shell
# cannot silently replace the trajectory being graded.
env = dict(os.environ)
env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
env["HG_OUTPUT_JSONL"] = str(row_path)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env.pop("HG_ANSWER_FILE", None)
env.pop("HG_PATCH_FILE", None)

proc = subprocess.run(
    [sys.executable, "-m", "pytest", str(target), "-v",
     "-p", "no:cacheprovider", "--rootdir", str(TESTS)],
    cwd=str(TESTS), capture_output=True, text=True, env=env)
stdout = (proc.stdout or "") + (proc.stderr or "")

_W = chr(92) + "w"
_OB = chr(92) + "["
_CB = chr(92) + "]"
_S = chr(92) + "s"
# Same node-outcome pattern as evaluation/grading/criteria.py. Assembled
# from chr(92) pieces because this file is generated through two layers of
# string escaping, where a literal backslash silently becomes a double one
# and the regex then matches nothing -- scoring a perfect run 0.
NODE = re.compile("::(?P<name>[" + _W + _OB + _CB + "<>-]+)" + _S + "+"
                  "(?P<status>PASSED|FAILED|ERROR|XPASS|XFAIL|SKIPPED)")
PASS = {"PASSED", "XPASS"}
outcomes = {m.group("name"): m.group("status") for m in NODE.finditer(stdout)}
if not outcomes:
    print("[FATAL] pytest produced no outcomes (rc=%d)" % proc.returncode, file=sys.stderr)
    print(stdout[-1500:], file=sys.stderr)
    raise SystemExit(2)

weights = json.loads(read(TESTS / "test_weights.json") or "{}")
if weights:
    # Divide by the POSITIVE weight total only: a negative penalty must subtract
    # from the numerator, not shrink the divisor, or earned/total exceeds 1.0
    # whenever the penalty test fails.
    total = sum(w for w in weights.values() if w > 0)
    earned = sum(w for n, w in weights.items() if outcomes.get(n) in PASS)
    value = max(0.0, min(1.0, earned / total)) if total > 0 else 0.0
else:
    passed = sum(1 for v in outcomes.values() if v in PASS)
    value = passed / len(outcomes)

# TWO keys, and never a "reward". This file scores the DETERMINISTIC channel
# only, and for these bundles that channel is process -- did the agent read the
# right code. Answer correctness lives entirely in tests/rubric.json (33
# criteria, 27 positive, all "answer content"/"final_answer"), needs a judge,
# and is scored by scripts/grade_rubric.py on the host.
#
# The key COUNT is load-bearing; harbor promotes a lone key exactly as it
# promotes one named "reward":
#
#   upload/uploader.py:_extract_primary_reward  &  cli/jobs.py:_primary_reward
#       if "reward" in rewards: return rewards["reward"]
#       if len(rewards) == 1:   return next(iter(rewards.values()))
#
# so {"pytest": 1.0} is promoted to a primary reward of 1.0 -- byte-identical
# to the {"pytest": 1.0, "reward": 1.0} it replaced. Emitting one key fixes
# nothing and silently breaks a second consumer:
#
#   utils/pass_at_k.py:_compute_pass_at_k_for_trials
#       if len(rewards) != 1: return {}          # 2 keys -> metric disabled
#       if reward_value not in (0, 1): return {}
#       task_successes[...].append(int(reward_value))
#
# With one key of value 1.0 a fabricated trajectory carrying a negated answer
# is counted as a pass@k SUCCESS; with two keys the task is excluded, which is
# what a process-only score deserves. So emit a second dimension: both rules
# fall through, no primary reward is invented, and pass@k stays disabled.
pathlib.Path(REWARD).write_text(
    json.dumps({"pytest": value, "rubric_scored": 0}) + chr(10), encoding="utf-8")
for n, w in sorted(weights.items()):
    print("  %-46s %-7s w=%s" % (n, outcomes.get(n, "MISSING"), w))
print("[ok] pytest=%.4f  (process channel only -- rubric scores the answer)" % value)

PYEOF
status=$?
cat "${REWARD}" 2>/dev/null
exit $status
