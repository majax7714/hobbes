# ADR 027: Consuming SCIP — node identity, indexer config, and the reader

Date: 2026-08-14
Status: accepted

Milestone V2.M0 (the spike). Grounds architecture v2 §3.2/§3.3 in what the
indexers actually emit. Every number below was produced by
`scip/analyze.mjs` and `scip/compare.mjs` against `scip-python` 0.6.6 and
`scip-typescript` 0.4.0 on the four sanctioned repos, and is reproducible.

## Context

§3.3 says SCIP monikers "are globally unique (they encode package and
version) and become the graph's node IDs", with the consequence that "node
identity is stable across re-indexes." M1 was to freeze a moniker-keyed
schema on that basis. The spike existed to check the claim before the schema
depended on it.

## What the indexers actually emit

A moniker is `<scheme> <manager> <package> <version> <descriptors>`:

```
scip-python python hobbes 0 `src.hobbes.cli`/__init__:
scip-python python hobbes 0 `src.miniapp.api`/read_item().
scip-python python hobbes 0 `src.miniapp.api`/read_item().(item_id)
scip-python python python-stdlib 3.11 builtins/ValueError#
scip-typescript npm betchat-frontend 1.0.0 src/api/`axios.ts`/api.
```

## Decision 1 — pin `--project-version`, or node identity is not stable

**The version field is part of every symbol, and it defaults to the git
revision.** Indexing a two-commit scratch repo with no declared version:

```
commit 1:  scip-python python vertest c9b3bbd… mod/hello().
commit 2:  scip-python python vertest 5d87e72… mod/hello().
```

`hello()` did not change. Its moniker did. Left alone, **every node id in
the graph changes on every commit** — which would make `hobbes diff` report
the entire repo as removed-and-re-added at each commit, destroying the one
thing v2 is meant to sharpen.

Precedence is `--project-version` > a version declared in
`pyproject.toml`/`package.json` > the git revision. So the behaviour also
*varies by repo*: the miniapp fixture picked up `0.1.0` from its pyproject
and was stable; a repo without one was not. Uniformly bad would be better
than this.

**Hobbes always passes an explicit constant `--project-version`.** The cost
is that monikers stop carrying real version information, which trims §3.3's
multi-repo aside: a future graph merge keys on package identity, not on
package version. That is the right trade — stable ids are load-bearing
today, cross-version merging is not on any milestone.

§3.3's stability claim is therefore true only under this ADR, not inherently.

## Decision 2 — indexer config is per *repo*, and getting it wrong is silent

§3.7 frames configuration as per *language*. It is also per repo, and the
failure mode is quiet.

`scip-python` on this repo's `pipeline/`, compared against lane A's current
module edges:

| | recall vs lane A | lane-A-only | scip-only |
|---|---|---|---|
| no config | **0.500** | 48 | 3 |
| `pyrightconfig.json` → `extraPaths: ["src"]` | **0.948** | 5 | 11 |

The cause: under a src layout, `src/hobbes/cli.py` is indexed as module
`src.hobbes.cli`, while `tests/test_cli.py` imports it as `hobbes.cli`
through the editable install. Those are two different monikers for one file,
so the reference dangles — `scip-python python hobbes 0 hobbes/__init__:` is
referenced and never defined. **Every test→source edge was lost.** One line
of Pyright config unifies them.

It generalises: qwen-pathology (src layout) went **0.625 → 1.000**, zero
lane-A-only edges remaining. Two of the three Python repos needed it.

The residual 5 on this repo are fully explained and are not misses: 3 are
`minits` TS/JS fixture files that `scip-python` correctly does not index,
and 2 are the nested `miniapp` fixture, a project-inside-a-project whose own
`src/` the outer config does not cover — the multi-zone problem M6 already
solved for tsconfig, recurring for Python. SELENEX's 0.637 is the same
language-partition effect: its JS half is lane B's typescript indexer's job.

The 11 scip-only edges are **SCIP being more precise than lane A**:
`cli.py → invariants/schema.py` where lane A says `invariants/__init__.py`,
because SCIP follows a re-export to the real definition site. These are the
first real instances of the §3.4 lane-disagreement report, and they favour
lane B.

**Consequences:** the indexer-config registry is needed at **M2**, not M4 —
lane B cannot land usefully without it. And Hobbes must *detect* a degraded
index rather than trust the exit code (Decision 4).

## Decision 3 — a moniker is a node id only after filtering

Taking SCIP definitions as graph nodes 1:1 does not work. On kbet's
frontend:

| definitions | count |
|---|---|
| meta (`:`) | 5054 |
| term (`.`) | 601 |
| local | 532 |
| method (`()`) | 187 |
| parameter (`(x)`) | 160 |
| namespace (`/`) | 85 |
| type (`#`) | 76 |
| **total** | **6696** |
| **graph-worthy** (namespace/type/method/term) | **949 — 14%** |

For scale: the entire current dogfood graph has 834 symbols; kbet's frontend
alone offers 6,696. **The graph builder keeps namespace, type, method and
top-level term descriptors and drops the rest**, and stdlib packages stay
dropped as they are under ADR-007. Filtering happens in the helper, before
the process boundary — see Decision 5.

## Decision 4 — a successful exit is not a successful index

`scip-typescript` on kbet with **no `node_modules` installed** exited 0 in
1.5s and produced a 2.4MB index that looks entirely plausible. It declared
`external_symbols: 0`, and its most-referenced package was
`npm:typescript@5.9.3` (2,643 references) — TypeScript's own bundled lib,
because the declared dependencies were not there to resolve against. Every
third-party edge was simply absent, and nothing said so.

P6 says degrade visibly. So the SCIP adapter computes its own degradation
signal rather than trusting the process:

- declared dependencies (`package.json`, `pyproject.toml`) that the index
  references **zero** symbols from ⇒ degraded,
- `external_symbols` empty while imports of non-stdlib packages exist ⇒
  degraded,
- indexer missing, non-zero exit, or crash ⇒ degraded.

Degraded lanes record into `extraction_errors` and warn at ingest, exactly
as M6 does for the ts-morph checker crash, and the graph stands at syntactic
tier.

## Decision 5 — the reader is a Node helper, on the ADR-021 pattern

SCIP is protobuf. Three ways to read it were considered:

- **the `scip` CLI's JSON output** — no bindings, but another external
  binary to install and pin, and it emits the whole index as JSON when we
  keep 14% of it;
- **Python `protobuf` + generated bindings** — a new pipeline dependency and
  a generated-code checkin, to read a format only lane B touches;
- **a Node helper** (chosen) — `scip/` already exists and already has the
  indexers, because both install from npm. It runs them, decodes, filters
  per Decision 3, and emits facts JSON for the Python join.

The third is what ADR-003 and ADR-021 already established for `tsextract`,
and it puts the Decision-3 filter *before* the process boundary rather than
shipping seven times the data across it. The Python side's shape does not
change: it consumes facts JSON from a Node subprocess, as it already does.

Bindings come from `@sourcegraph/scip-typescript`'s bundled generated
`scip.js`, which we already depend on at an exact pin. That is an undeclared
internal path, so a test asserts the import resolves; if a future version
moves it, the fallback is vendoring the 1,896-line generated file plus a
`google-protobuf` dependency. Reuse first because it is reversible and
lighter, not because it is prettier.

## Cost

Cold, single-threaded, on this box: miniapp 1.9s · qwen-pathology 2.8s ·
hobbes/pipeline 4.5s · SELENEX 5.5s · kbet frontend (TS) 1.5s. Well inside
what §3.6's debounced-local, per-PR-in-CI plan assumes; the content-hash
cache is an optimisation, not a rescue.

## Verdict on §3.3: go, with conditions

Monikers work as node ids **given** a pinned project version (Decision 1),
per-repo indexer config (Decision 2), and descriptor filtering (Decision 3).
None of the three is inherent to SCIP and all three are silent when wrong,
which is why they are decided here rather than discovered at M2. V2.M1 may
proceed on a moniker-keyed schema.

## Consequences

- §3.3's stability claim holds only under Decision 1; §7's V2.M1 gets the
  pinned-version rule as an explicit requirement.
- The indexer-config registry moves from M4 into **M2**. `hobbes.yaml` still
  needs its own ADR (the ADR-012 "personal files" tension is unchanged), but
  it is now on M2's critical path.
- The graph builder needs a descriptor filter before it needs anything else.
- `scip/{analyze,compare}.mjs` are spike tooling, kept because they are the
  reproducible evidence for these numbers and because `compare.mjs` is a
  working prototype of §3.4's lane-agreement report. They are replaced by
  the real helper at M2 and carry no tests until then.
