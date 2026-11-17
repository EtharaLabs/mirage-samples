<p align="center"><img src="images/hero.svg" alt="Mirage" width="720"></p>

# Mirage Hybrid-Gym: Samples

<p align="center"><b>Five sample tasks from Mirage, a Harbor benchmark of coding-agent tasks at the Hybrid-Gym task mix.</b></p>

<p align="center"><a href="#summary"><img src="https://img.shields.io/badge/tasks-5-845EF7" alt="tasks: 5"></a> <a href="#summary"><img src="https://img.shields.io/badge/harbor_schema-1.4-845EF7" alt="harbor schema: 1.4"></a> <a href="#rollouts"><img src="https://img.shields.io/badge/opus_5.5_mean_reward-0.3107-845EF7" alt="opus 5.5 mean reward: 0.3107"></a></p>

<p align="center"><sub><a href="#abstract">Abstract</a> | <a href="#summary">Summary</a> | <a href="#tasks">Tasks</a> | <a href="#rollouts">Rollouts</a> | <a href="#coverage">Coverage</a> | <a href="#dataset-structure">Dataset structure</a> | <a href="#reproduction">Reproduction</a> | <a href="#cite">Cite</a> | <a href="#contact">Contact</a></sub></p>

## Abstract

Mirage is a benchmark of coding-agent tasks in [Harbor](https://www.harborframework.com/) format, built on [Hybrid-Gym](https://arxiv.org/abs/2602.16819) (arXiv:2602.16819). Hybrid-Gym, from researchers at Carnegie Mellon University and All Hands AI, is a training environment of scalable synthetic tasks, such as function localization and dependency search, designed to teach coding agents skills that transfer across tasks. Agents trained on it improve a base model by 25.4% absolute on SWE-Bench Verified, 7.9% on SWT-Bench Verified and 5.1% on Commit-0 Lite.

Every task gives the agent a real upstream checkout in a container whose network allowlist names only `docs.python.org`, and carries a reference solution, deterministic tests and an LLM-judged rubric. A separate verifier container scores the investigation twice. The deterministic channel replays the agent's own tool calls and credits only definitions and files it actually displayed from the checkout, plus searches and citation grounding, with a penalty for any source change. The rubric scores the written explanation against a reference built from the upstream fixes and a reproduction of every reported pipeline. The reward is continuous from 0 to 1, with the rubric weighted four to one over the deterministic channel.

This repository holds the five-task sample. All five are read-only, multi-cause issue-localization tasks, two on pandas and three on polars. Each ticket reports four or five pipelines that return quietly wrong results, and the agent must find how many root causes there are, the routine and file behind each, why each harmless variant behaves, and how each wrong result comes out of the routines that trust the faulty decision. Each checkout is pinned before the upstream fixes, with comments, docstrings and tests stripped and its history replaced by a single commit. Each task declares difficulty `hard` and has an AHT of 960 minutes.

## Summary

| Property | Value |
| --- | --- |
| Tasks | 5 |
| Domain | Software engineering |
| Task family | Issue localization: read-only, multi-cause |
| Projects | pandas (2 tasks), polars (3 tasks) |
| Languages | Python, Cython, Rust |
| Format | Harbor task, schema 1.4 |
| Platform | linux |
| AHT | 960 minutes per task |
| Reward | continuous from 0 to 1, the judged rubric weighted four to one over the deterministic tests |
| Judge | Claude Fable 5.1 (`anthropic/claude-fable-5-1`) |
| Agent | OpenHands 0.62.0 with `claude-opus-5-5` (Claude Opus 5.5) |
| Runs | 1 per task |
| Mean reward | 0.3107 |
| Rubric criteria met | 58 of 237 |

## Tasks

| Task | Project | Root causes | Objective | Rubric |
| --- | --- | --- | --- | --- |
| [`00e686b1`](00e686b1-9a02-5c13-9c3a-fa5824129971/) | pandas at `03e5d938adbd` | 4 | Find why four pipelines return quietly wrong results: `sort_index` on a multi-level index whose tier level is an ordered categorical, lookups of a missing label after `stack`, grouped `max`, `min`, `cummax` and `cummin` over not-a-number values in a nullable float column, and an `Int64` array assigned to a label that matches two columns. | 46 criteria |
| [`0d205e9a`](0d205e9a-9537-5ba9-817a-1132725ee409/) | polars at `3a8b583f8b34` | 5 | Find why five pipelines that trust sortedness give quietly wrong summaries: a positional lookup, a rolling first over empty windows, a rolling per-window slice, an aggregated constant column, and a join on a sorted float key. | 62 criteria |
| [`6ffc6d6d`](6ffc6d6d-0988-58ef-8129-c72093f48bf5/) | pandas at `03e5d938adbd` | 4 | Find why four steps of a reporting job return wrong rows and dtypes: lookups by tuple keys of another length on a two-level index, in-place arithmetic with a partner that has extra labels, `DataFrame.compare` on large integers, and `pivot` with a list of value columns. | 37 criteria |
| [`78de1d0b`](78de1d0b-9e9d-584d-aeea-b34efee7cc2a/) | polars at `5eaa75417658` | 5 | Find why five operations return quietly wrong values: scatter of a timestamp into a nanosecond column, `sum_horizontal` over `Int8` columns, a number floor-divided by a Series, a strict cast of a struct column in a lazy query, and an asof join on a sorted `Categorical` key. | 46 criteria |
| [`d5a207d9`](d5a207d9-6e08-5c5c-99c1-e0f8e306b11d/) | polars at `5eaa75417658` | 4 | Find why four lazy queries return quietly wrong rows: a filter for missing values with a negated membership, a when/then/otherwise flag after a sort, a left `join_where` followed by a selection, and SQL over a `VALUES` list with `ORDER BY`. | 46 criteria |

## Rollouts

Each task was run once with OpenHands 0.62.0 driving Claude Opus 5.5 and scored by the task's own verifier. Rollouts are stored in each task's `trajectories/claude-opus-5-5/run-01/`.

| Task | Model | Agent | Reward | Cost (USD) | Agent time |
| --- | --- | --- | --- | --- | --- |
| [00e686b1-9a02-5c13-9c3a-fa5824129971](00e686b1-9a02-5c13-9c3a-fa5824129971/trajectories/claude-opus-5-5/run-01/) | claude-opus-5-5 | openhands 0.62.0 | 0.3575 | 5.80 | 37m 50s |
| [0d205e9a-9537-5ba9-817a-1132725ee409](0d205e9a-9537-5ba9-817a-1132725ee409/trajectories/claude-opus-5-5/run-01/) | claude-opus-5-5 | openhands 0.62.0 | 0.2249 | 11.73 | 90m 0s (timeout) |
| [6ffc6d6d-0988-58ef-8129-c72093f48bf5](6ffc6d6d-0988-58ef-8129-c72093f48bf5/trajectories/claude-opus-5-5/run-01/) | claude-opus-5-5 | openhands 0.62.0 | 0.4189 | 7.26 | 60m 0s (timeout) |
| [78de1d0b-9e9d-584d-aeea-b34efee7cc2a](78de1d0b-9e9d-584d-aeea-b34efee7cc2a/trajectories/claude-opus-5-5/run-01/) | claude-opus-5-5 | openhands 0.62.0 | 0.2151 | 9.98 | 60m 0s (timeout) |
| [d5a207d9-6e08-5c5c-99c1-e0f8e306b11d](d5a207d9-6e08-5c5c-99c1-e0f8e306b11d/trajectories/claude-opus-5-5/run-01/) | claude-opus-5-5 | openhands 0.62.0 | 0.3373 | 14.21 | 90m 0s (timeout) |

Four runs reached the task's agent timeout of 60 or 90 minutes and were scored as they stood, so their agent time is that limit. Cost is the list price of each run's tokens.

Reward channels per task, where `pytest` is the deterministic channel, `rubric` the judged one, and reward is 0.8 × rubric + 0.2 × pytest:

| Task | pytest | rubric | Rubric criteria met | Reward |
| --- | --- | --- | --- | --- |
| 00e686b1-9a02-5c13-9c3a-fa5824129971 | 0.9706 | 0.2042 | 13 of 46 | 0.3575 |
| 0d205e9a-9537-5ba9-817a-1132725ee409 | 0.9024 | 0.0556 | 9 of 62 | 0.2249 |
| 6ffc6d6d-0988-58ef-8129-c72093f48bf5 | 0.9615 | 0.2832 | 14 of 37 | 0.4189 |
| 78de1d0b-9e9d-584d-aeea-b34efee7cc2a | 0.7568 | 0.0797 | 11 of 46 | 0.2151 |
| d5a207d9-6e08-5c5c-99c1-e0f8e306b11d | 1.0000 | 0.1716 | 11 of 46 | 0.3373 |
| **mean** | **0.9183** | **0.1589** | | **0.3107** |

Each rollout folder is Harbor's trial output:

| Path | Contents |
| --- | --- |
| `config.json`, `lock.json` | Trial configuration and resolved run settings, including the task digest |
| `result.json` | Agent, model, token usage, cost, timings, and verifier reward |
| `trial.log`, `exception.txt` | Harbor's trial log, and the timeout error in the four runs that hit it |
| `agent/` | Agent trajectory (`trajectory.json`), OpenHands log (`openhands.txt`), model completions and session files |
| `verifier/` | `reward.json`, `reward-details.json` with every rubric verdict, `ctrf.json`, and test output |
| `artifacts/` | Files collected from the paths declared in `task.toml`: the agent's `answer.md`, its trajectory and sessions, and `agent.patch`, its diff against the checkout |

`trajectories/summary.json` holds each task's score statistics per model, and `trajectories/claude-opus-5-5/summary.json` its runs, token counts and list-price cost.

## Coverage

| Keyword | Tasks |
| --- | --- |
| casting | 1 |
| copy-on-write | 1 |
| cython | 2 |
| dtypes | 2 |
| groupby | 1 |
| issue_localization | 5 |
| joins | 1 |
| multi-cause | 5 |
| multiindex | 2 |
| pandas | 2 |
| polars | 3 |
| python | 5 |
| query-optimizer | 1 |
| read-only | 5 |
| reshape | 1 |
| rust | 3 |
| sorted-flag | 1 |
| sql | 1 |

## Dataset structure

Each task is one Harbor task in a directory named by its uuid.

| Task | Keywords |
| --- | --- |
| [`00e686b1-9a02-5c13-9c3a-fa5824129971`](00e686b1-9a02-5c13-9c3a-fa5824129971/) | copy-on-write, cython, groupby, issue_localization, multi-cause, multiindex, pandas, python, read-only |
| [`0d205e9a-9537-5ba9-817a-1132725ee409`](0d205e9a-9537-5ba9-817a-1132725ee409/) | issue_localization, multi-cause, polars, python, read-only, rust, sorted-flag |
| [`6ffc6d6d-0988-58ef-8129-c72093f48bf5`](6ffc6d6d-0988-58ef-8129-c72093f48bf5/) | cython, dtypes, issue_localization, multi-cause, multiindex, pandas, python, read-only, reshape |
| [`78de1d0b-9e9d-584d-aeea-b34efee7cc2a`](78de1d0b-9e9d-584d-aeea-b34efee7cc2a/) | casting, dtypes, issue_localization, joins, multi-cause, polars, python, read-only, rust |
| [`d5a207d9-6e08-5c5c-99c1-e0f8e306b11d`](d5a207d9-6e08-5c5c-99c1-e0f8e306b11d/) | issue_localization, multi-cause, polars, python, query-optimizer, read-only, rust, sql |

```
<uuid>/
├── task.toml         runner manifest
├── instruction.md    objective the agent reads
├── environment/      sandbox image that fetches and strips the upstream checkout
├── tests/            verifier and judged rubric, hidden from the agent
├── solution/         reference solution
└── trajectories/
    ├── summary.json  scores per model
    └── claude-opus-5-5/
        ├── summary.json  runs, tokens and cost
        └── run-01/       run with Claude Opus 5.5
```

## Reproduction

Each task directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image, which fetches the upstream project at the task's base commit and strips it, `tests/` the verifier, and `solution/` the reference solution. The rollouts above were produced with:

```bash
harbor run -p <uuid> -a openhands -m anthropic/claude-opus-5-5 --ak version=0.62.0
```

Building an image fetches the upstream checkout from GitHub, so the build needs network access. The verifier's judged rubric calls Claude Fable 5.1 and needs `ANTHROPIC_API_KEY`; without it the verifier scores the deterministic channel alone.

## Cite

```bibtex
@misc{mirage2026,
  title        = {Mirage: Harbor-format terminal tasks at the Hybrid-Gym task mix},
  author       = {{Ethara.AI}},
  year         = {2026}
}

@inproceedings{xie2026hybridgymtrainingcodingagents,
  title     = {Hybrid-Gym: Training Coding Agents to Generalize Across Tasks},
  author    = {Xie, Yiqing and Liu, Emmy and Zhang, Gaokai and Kotalwar, Nachiket and Gandhi, Shubham and Acharya, Sathwik and Wang, Xingyao and Ros{\'e}, Carolyn and Neubig, Graham and Fried, Daniel},
  booktitle = {Forty-third International Conference on Machine Learning},
  year      = {2026},
  url       = {https://arxiv.org/abs/2602.16819}
}
```

## Contact

Mirage is built by [Ethara.AI](https://github.com/Ethara-Ai).

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
