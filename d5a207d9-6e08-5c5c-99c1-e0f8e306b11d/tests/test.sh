#!/bin/bash
# RewardKit verifier entrypoint. Stages the final answer, raw-first history,
# and collected patch, then lets reward.toml perform all score aggregation.
set -uo pipefail

WS="${HG_WORKSPACE:-/app}"
TRAJECTORY="${HG_TRAJECTORY:-/logs/agent/trajectory.json}"
ANSWER_FILE="${HG_ANSWER_FILE_IN:-/logs/agent/answer.md}"
PATCH="${HG_PATCH:-/logs/artifacts/agent.patch}"
REWARD="${HG_REWARD_OUT:-/logs/verifier/reward.json}"
JUDGE_DETAILS="${HG_JUDGE_DETAILS:-/logs/verifier/reward-details.json}"
TESTS_DIR="${HG_TESTS_DIR:-/tests}"

# reward.txt fails closed: it holds 0 from here on, and on exit it takes the "reward" value of
# reward.json when one was written (Harbor reads reward.json first and reward.txt otherwise).
REWARD_TXT="$(dirname "${REWARD}")/reward.txt"
mkdir -p "$(dirname "${REWARD}")"
printf '0\n' > "${REWARD_TXT}"
finish() {
  python3 - "${REWARD}" "${REWARD_TXT}" <<'PYEOF'
import json, math, sys
try:
    value = float(json.load(open(sys.argv[1]))["reward"])
    if not math.isfinite(value):
        raise ValueError(value)
except (OSError, ValueError, KeyError, TypeError):
    value = 0.0
open(sys.argv[2], "w").write(f"{value}\n")
PYEOF
}
trap finish EXIT

# The judge is tests/judge.toml's model, anthropic/claude-fable-5-1 (REWARDKIT_JUDGE overrides it);
# litellm reads ANTHROPIC_API_KEY and ANTHROPIC_API_BASE. With no judge credentials only the
# deterministic channel is scored, and the log says judge_unavailable.
JUDGE_READY=1
if [ -z "${ANTHROPIC_API_KEY:-}${CLAUDE_CODE_OAUTH_TOKEN:-}${REWARDKIT_JUDGE:-}" ]; then
  JUDGE_READY=0
fi
ANSWER_DELIVERABLE="${HG_ANSWER_DELIVERABLE:-/workspace/answer.md}"

mkdir -p "${WS}" "$(dirname "${REWARD}")"
[ -f "${PATCH}" ] || : > "${PATCH}"

HG_WS="${WS}" python3 - <<'PYEOF'
from __future__ import annotations   # extract.py's spliced functions annotate
# `str | Path`, which 3.9 evaluates at def time and rejects with "unsupported operand
# type(s) for |". The image pins 3.12, but the README invites replay on the host,
# and a host python3 is routinely 3.9 -- this machine's is. test_output.py already
# carries the import; this file did not, so the bundle failed to score itself.
import json, os, pathlib
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
WORK = pathlib.Path(os.environ["HG_WS"])
WORK.mkdir(parents=True, exist_ok=True)


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
# The instruction names /workspace/answer.md as the deliverable and asks for it early, so
# a session cut short still has an answer. It wins over the finish action, which is
# absent when the session ends on a timeout or on a plain message.
answer = read(os.environ.get("HG_ANSWER_DELIVERABLE", "/workspace/answer.md"))
if not answer.strip():
    answer = answer_from_events(_ev) if _ev else ""
if not answer.strip() and os.path.exists(TRAJ):
    answer = answer_from_trajectory(TRAJ)
if not answer.strip():
    answer = read(ANSWER_FILE)

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
(WORK / "answer.md").write_text(answer, encoding="utf-8")
(WORK / "history.jsonl").write_text(
    "".join(json.dumps(event, default=str) + "\n" for event in history),
    encoding="utf-8",
)
(WORK / "agent.patch").write_text(read(PATCH), encoding="utf-8")

# The judge reads at most 1 MB per file and skips anything larger, so the raw history of
# a long session never reaches it. The trajectory criteria read this digest instead:
# every action in order, each with the head of its output.
def _digest(events: list[dict[str, Any]], limit: int = 600_000) -> str:
    outputs = {e.get("cause"): str(e.get("content") or "") for e in events
               if isinstance(e, dict) and e.get("observation") and e.get("cause") is not None}
    lines = ["# Agent actions, in order", ""]
    size = 0
    for e in events:
        if not (isinstance(e, dict) and e.get("source") == "agent" and e.get("action") in ("run", "read", "edit")):
            continue
        args = e.get("args") or {}
        what = args.get("command") if e.get("action") == "run" else args.get("path")
        block = "## %s: %s\n```\n%s\n```\n" % (
            e.get("action"), str(what)[:600], outputs.get(e.get("id"), "")[:1200])
        if size + len(block) > limit:
            lines.append("[digest truncated at %d characters]" % limit)
            break
        lines.append(block)
        size += len(block)
    return "\n".join(lines) + "\n"

(WORK / "process.md").write_text(_digest(history), encoding="utf-8")
print("[stage] answer: %d chars | history: %d events from %s" % (len(answer), len(history), src))

PYEOF
stage_rc=$?
if [ "${stage_rc}" -ne 0 ]; then
  echo "[FATAL] staging failed (rc=${stage_rc}); reward 0" >&2
  exit "${stage_rc}"
fi

# No answer, no reward: a missing or blank answer scores 0 on every channel without a judge call.
# Without this gate the negated rubric criteria credit a blank answer (the old null_floor).
if ! grep -q '[^[:space:]]' "${WS}/answer.md" 2>/dev/null; then
  echo "[gate] answer missing or empty: reward 0, judge not called"
  printf '{"reward": 0.0, "pytest": 0.0, "rubric": 0.0}\n' > "${REWARD}"
  exit 0
fi

if command -v rewardkit >/dev/null 2>&1; then
  RK=(rewardkit)
elif command -v uvx >/dev/null 2>&1; then
  RK=(uvx --from 'harbor-rewardkit==0.2.*' rewardkit)
else
  echo "[FATAL] rewardkit not available; reward 0" >&2
  exit 127
fi

if [ "${JUDGE_READY}" -eq 0 ]; then
  echo "judge_unavailable: no judge credentials (ANTHROPIC_API_KEY unset); scoring the deterministic channel only"
  NOJUDGE_DIR="$(mktemp -d)"
  cp -a "${TESTS_DIR}/." "${NOJUDGE_DIR}/"
  rm -f "${NOJUDGE_DIR}/judge.toml"
  cat > "${NOJUDGE_DIR}/reward.toml" <<'TOMLEOF'
[scoring.test_output]
aggregation = "weighted-sum"

[[reward]]
name = "reward"
aggregation = "weighted-mean"
weights = { test_output = 1.0 }

[[reward]]
name = "pytest"
aggregation = "weighted-mean"
weights = { test_output = 1.0 }
TOMLEOF
  HG_OUTPUT_JSONL="${WS}/output.jsonl" "${RK[@]}" "${NOJUDGE_DIR}" --workspace "${WS}" --output "${REWARD}"
  rk_rc=$?
  cat "${REWARD}" 2>/dev/null
  exit "${rk_rc}"
fi

src_details="$(dirname "${REWARD}")/reward-details.json"
details_bad() {
  [ -f "${src_details}" ] && python3 -c 'import json,sys
def bad(value):
    if isinstance(value, dict):
        return value.get("error") is not None or any(bad(item) for item in value.values())
    return isinstance(value, list) and any(bad(item) for item in value)
sys.exit(0 if bad(json.load(open(sys.argv[1]))) else 1)' "${src_details}"
}
# A judge endpoint can refuse a burst (HTTP 429) when several verifiers finish together;
# RewardKit does not retry, so the whole scoring is retried after a pause, at most three times.
rk_rc=1
for attempt in 1 2 3; do
  rm -f "${REWARD}" "${src_details}"
  HG_OUTPUT_JSONL="${WS}/output.jsonl" \
  "${RK[@]}" "${TESTS_DIR}" --workspace "${WS}" \
      --max-concurrent-llm 4 --output "${REWARD}"
  rk_rc=$?
  if [ "${rk_rc}" -eq 0 ] && [ -f "${REWARD}" ] && ! details_bad; then
    break
  fi
  [ "${attempt}" -lt 3 ] && { echo "[warn] scoring attempt ${attempt} failed (rc=${rk_rc}); retrying" >&2; sleep $((attempt * 60)); }
done

if [ -f "${src_details}" ] && [ "${src_details}" != "${JUDGE_DETAILS}" ]; then
  cp "${src_details}" "${JUDGE_DETAILS}" 2>/dev/null
fi

if details_bad; then
  echo "judge_unavailable: a judge or criterion call still errored after 3 attempts; reward 0" >&2
  rm -f "${REWARD}"
  exit 3
fi

if [ ! -f "${REWARD}" ]; then
  echo "judge_unavailable: scoring produced no reward on any of 3 attempts (rc=${rk_rc}); reward 0" >&2
  exit "${rk_rc}"
fi

# CTRF report of the deterministic criteria. The read-only penalty is the cheat check:
# it passes when no source was modified.
python3 - "${src_details}" "$(dirname "${REWARD}")/ctrf.json" <<'PYEOF'
import json, sys, time
try:
    details = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    details = {}
tests = []
for component in ((details.get("reward") or {}).get("components") or []):
    if component.get("name") != "test_output":
        continue
    for crit in (component.get("detail") or {}).get("criteria") or []:
        name = str(crit.get("name") or "")
        hit = float(crit.get("value", crit.get("score")) or 0.0) > 0.0
        passed = (not hit) if name == "modified_code_penalty" else hit
        tests.append({"name": name, "status": "passed" if passed else "failed", "duration": 0})
now = int(time.time() * 1000)
summary = {"tests": len(tests), "passed": sum(t["status"] == "passed" for t in tests),
           "failed": sum(t["status"] == "failed" for t in tests), "skipped": 0, "pending": 0,
           "other": 0, "start": now, "stop": now}
json.dump({"results": {"tool": {"name": "rewardkit"}, "summary": summary, "tests": tests}},
          open(sys.argv[2], "w"), indent=2)
PYEOF

cat "${REWARD}" 2>/dev/null
exit "${rk_rc}"
