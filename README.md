<p align="center"><img src="images/hero.svg" alt="mirage" width="720"></p>

# mirage: samples

<p align="center"><b>The samples lane: 5 of 30 Harbor task bundles.</b></p>

<p align="center"><a href="#summary"><img src="https://img.shields.io/badge/bundles-5_of_30-845EF7" alt="bundles: 5 of 30"></a> <a href="#evidence-status"><img src="https://img.shields.io/badge/sealed-0-845EF7" alt="sealed: 0"></a> <a href="#difficulty-tiers"><img src="https://img.shields.io/badge/difficulty-measured-845EF7" alt="difficulty: measured"></a></p>

<p align="center"><sub><a href="#abstract">Abstract</a> | <a href="#summary">Summary</a> | <a href="#difficulty-tiers">Difficulty tiers</a> | <a href="#evidence-status">Evidence status</a> | <a href="#coverage">Coverage</a> | <a href="#dataset-structure">Dataset structure</a> | <a href="#verification-and-quality-assurance">Verification and quality assurance</a> | <a href="#reproduction">Reproduction</a> | <a href="#cite">Cite</a> | <a href="#license">License</a> | <a href="#contact">Contact</a></sub></p>

## Abstract

The curated lane of this corpus: at most 30 Harbor task bundles, every anchor seated first and every other bundle in seal order. Bundles past that ceiling live in `delivery/`.

Each bundle is one Harbor task in a directory named by its content-derived uuid5, so the name doubles as an integrity check. This page is rendered from the resident bundles on every reconcile; a value a bundle does not carry reads `absent`, and the page never fills one in.

## Summary

| Property | Value |
| --- | --- |
| Bundles | 5 of 30 |
| Sealed | 0 of 5 |
| Registrations | unregistered (5) |
| Audit verdicts | none (5) |
| Harbor schema | 1.4 (5) |

## Difficulty tiers

Difficulty is measured by the signed pilot alone and never declared in a bundle, so this page states no tier a bundle claims.

## Evidence status

The verdict is the audit outcome recorded at the sealed digest, and `none` means no verdict has landed for that digest yet. Only an authoring run removes a bundle from this lane, so removal waits for the next one.

| uuid | Verdict | Sealed digest | Stream |
| --- | --- | --- | --- |
| 00e686b1-9a02-5c13-9c3a-fa5824129971 | none | absent | none |
| 0d205e9a-9537-5ba9-817a-1132725ee409 | none | absent | none |
| 6ffc6d6d-0988-58ef-8129-c72093f48bf5 | none | absent | none |
| 78de1d0b-9e9d-584d-aeea-b34efee7cc2a | none | absent | none |
| d5a207d9-6e08-5c5c-99c1-e0f8e306b11d | none | absent | none |

## Coverage

| Keyword | Bundles |
| --- | --- |
| issue_localization | 5 |
| multi-cause | 5 |
| python | 5 |
| read-only | 5 |
| polars | 3 |
| rust | 3 |
| cython | 2 |
| dtypes | 2 |
| multiindex | 2 |
| pandas | 2 |
| casting | 1 |
| copy-on-write | 1 |
| groupby | 1 |
| joins | 1 |
| query-optimizer | 1 |
| reshape | 1 |
| sorted-flag | 1 |
| sql | 1 |

## Dataset structure

| Bundle | Task | Keywords | Registration | Sealed at | Tier |
| --- | --- | --- | --- | --- | --- |
| [`00e686b1-9a02-5c13-9c3a-fa5824129971`](00e686b1-9a02-5c13-9c3a-fa5824129971/) | `mirage/00e686b1-9a02-5c13-9c3a-fa5824129971` | copy-on-write, cython, groupby, issue_localization, multi-cause, multiindex, pandas, python, read-only | unregistered | unsealed | - |
| [`0d205e9a-9537-5ba9-817a-1132725ee409`](0d205e9a-9537-5ba9-817a-1132725ee409/) | `mirage/0d205e9a-9537-5ba9-817a-1132725ee409` | issue_localization, multi-cause, polars, python, read-only, rust, sorted-flag | unregistered | unsealed | - |
| [`6ffc6d6d-0988-58ef-8129-c72093f48bf5`](6ffc6d6d-0988-58ef-8129-c72093f48bf5/) | `mirage/6ffc6d6d-0988-58ef-8129-c72093f48bf5` | cython, dtypes, issue_localization, multi-cause, multiindex, pandas, python, read-only, reshape | unregistered | unsealed | - |
| [`78de1d0b-9e9d-584d-aeea-b34efee7cc2a`](78de1d0b-9e9d-584d-aeea-b34efee7cc2a/) | `mirage/78de1d0b-9e9d-584d-aeea-b34efee7cc2a` | casting, dtypes, issue_localization, joins, multi-cause, polars, python, read-only, rust | unregistered | unsealed | - |
| [`d5a207d9-6e08-5c5c-99c1-e0f8e306b11d`](d5a207d9-6e08-5c5c-99c1-e0f8e306b11d/) | `mirage/d5a207d9-6e08-5c5c-99c1-e0f8e306b11d` | issue_localization, multi-cause, polars, python, query-optimizer, read-only, rust, sql | unregistered | unsealed | - |

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#131a33","primaryTextColor":"#e8ecff","primaryBorderColor":"#845EF7","lineColor":"#22d3ee","fontFamily":"monospace"}}}%%
flowchart LR
    bundle["&lt;uuid&gt;/"]
    bundle --> n0["task.toml<br/>runner manifest"]
    bundle --> n1["instruction.md<br/>objective the agent reads"]
    bundle --> n2["environment/<br/>agent sandbox image"]
    bundle --> n3["tests/<br/>verifier, hidden from the agent"]
    bundle --> n4["solution/<br/>private oracle"]
    bundle --> n5["trials/"]
```

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#131a33","primaryTextColor":"#e8ecff","primaryBorderColor":"#845EF7","lineColor":"#22d3ee","fontFamily":"monospace"}}}%%
flowchart LR
    staging["staging/"]
    staging --> samples["samples/<br/>5 of 30"]
    samples --> delivery["delivery/<br/>0 of 10000"]
    delivery --> stock["stock/<br/>0 of 10000"]
```

## Verification and quality assurance

Each bundle's signed provenance carrier holds its screening roots, screening instant, and absolute expiry. Placement moves that carrier into the private derivation set, which this page never reads, so reconcile lists no root it cannot verify here.

## Reproduction

Each bundle directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image, and `tests/` the verifier. Point a Harbor runner at one bundle directory to reproduce it; `solution/` stays private.

## Cite

```bibtex
@misc{mirage2026,
  title        = {mirage: Harbor-format terminal tasks at the Hybrid-Gym task mix},
  author       = {{Green Rider Technology LLP (Ethara AI)}},
  year         = {2026},
  howpublished = {\url{https://github.com/Ethara-Ai}},
  note         = {Difficulty measured, never claimed}
}
```

## License

No licence file stands in this parent, so no licence is granted here. Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.

## Contact

[Ethara AI on GitHub](https://github.com/Ethara-Ai), [SECURITY.md](SECURITY.md) for a private security report, and [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
