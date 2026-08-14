# Hobbes — v2 build plan (extraction architecture)

**Status: approved by Max 2026-08-14, including all six deviations.** Written
against `docs/hobbes-architecture-v2.md` §7 and the code as it stands at
`c3b479c`. The deviations are now folded into §7.

**Progress: V2.M0 done (ADR-027).** Next is V2.M1.

This elaborates §7 into file-level work with exit criteria. Where it
**deviates** from §7 it says so and gives the reason; those deviations are
collected in the last section.

Sequencing rules carry from v1: deterministic before generative, one
milestone active at a time, each milestone exits on a real repo, stop at
exits for human review.

---

## 0. What the code says, before planning anything

Six facts established by reading the tree, not from memory. They shape the
plan:

1. **The artifact schema is already at v3**, not v1. §7 calls the target
   "graph schema v2"; the thing to build is **schema v4**.
2. **Nothing gates on the graph's schema version.** ADR-006 states that
   consumers reject versions they don't know. They don't — the only version
   checks in the tree are the policy file's (`policy.go:93`) and the
   tsextract facts helper's (`tssource.py:97`). `artifacts.go` passes
   `schema_version` straight through to the UI. A v4 graph would today be
   silently half-read by every consumer rather than refused, so §7's
   "migration shim so v1 consumers keep working" has nothing to hang on
   until the gate exists.
3. **Test reach is derived from lane A's symbol edges.**
   `extract/__init__.py:62` calls
   `collect_tests(modules, parsed, graph["symbol_edges"])`. Stripping call
   resolution from lane A regresses `tests.json` unless reach moves to lane
   B in the same milestone.
4. **`hobbes.yaml` does not exist.** §3.5/§3.7 register indexers and packs
   in it. Today all repo config lives under `.hobbes/policies/` (ADR-001),
   and ADR-012 gitignores the whole `.hobbes/` in target repos.
5. **Both key indexers install from npm** — `@sourcegraph/scip-python`
   0.6.6 and `@sourcegraph/scip-typescript` 0.4.0. Lane B needs no new
   package manager; it is the `tsextract/` pattern (ADR-021) again.
   `scip-go` is a Go binary, and the Go toolchain is already here.
6. **Hobbes cannot see its own Go.** The dogfood graph's languages are
   `hcl, javascript, python, typescript` — the 9.4k lines of policy engine,
   proxy, sandbox, and web server are invisible to it. V2.M5 closes that.

---

## V2.M0 — Spike: see real SCIP before freezing anything (1) — **DONE**

**Outcome: go on monikers-as-node-ids, with three conditions** — see
`docs/adr/027-consuming-scip.md`. A pinned `--project-version` (the default
embeds the git revision, so ids would change every commit); per-repo indexer
config (a src-layout Python repo silently loses *every* test→source edge
without it — recall 0.500 → 0.948 on this repo, 0.625 → 1.000 on
qwen-pathology); and descriptor filtering (only ~14% of SCIP definitions are
graph-worthy). All three are silent when wrong, which is exactly why the
spike was worth an evening. One knock-on: the indexer-config registry moves
from M4 to **M2**, because lane B cannot land usefully without it.

**Deviation from §7 — a new milestone.** §7 opens with a moniker-keyed
schema, but monikers are produced by lane B, which is M2. Designing the
contract before seeing the data is the one avoidable risk in the order, and
it is the same shape as M6's tsconfig-zoning surprise — caught same-day only
because kbet was run early rather than late.

Work:

- New `scip/` helper directory on the `tsextract/` conventions: lockfile
  committed, `node_modules/` gitignored, own test suite later.
- Run `scip-python` and `scip-typescript` over all four sanctioned repos —
  this one, kbet, SELENEX, qwen-pathology.
- Answer, with real output pasted into the ADR:
  1. **What does a moniker actually look like** for a repo-local module, a
     repo-local symbol, a third-party symbol, and a stdlib symbol? Are they
     usable as node ids directly, or do they need a projection to stay
     legible in the UI (ADR-023 already had to strip shared path prefixes
     to keep labels readable)?
  2. **How does Hobbes read the index?** SCIP is protobuf. Three
     candidates: the `scip` CLI's JSON output (one Go binary, no new
     language bindings, no new Python dep); Python `protobuf` + generated
     bindings; or a Node helper over SCIP's TS bindings (the ADR-021
     pattern). Prior: the CLI, because it adds the least. Decide on
     evidence.
  3. **Cost** — wall-clock cold and warm on each repo.
  4. **Degradation** — what does each indexer do on a repo that does not
     typecheck? Partial index, or nothing? P6 depends on the answer.

**Exit:** an ADR (`027-consuming-scip.md`) with real output in it, and a
go/no-go on monikers-as-node-ids. If the answer is no-go, §7 §3.3 needs
revisiting before M1 rather than after M2.

---

## V2.M1 — Graph schema v4 and the version gate (3–4)

**Deviation from §7 — scope widened** by two items (tests.json, and the
gate). §7 budgets 2–3 for graph.json alone.

Work:

- **Node identity** — moniker-keyed; lane-A-only nodes in a distinct
  namespace per §3.3, upgraded in place when an indexer lands.
- **Edge shape** — add `tier` (`semantic | syntactic | dynamic`); extend
  `evidence` (today `[{path, line}]`) to carry the producing lane and pack.
- **`tests.json` is part of the contract.** Its `symbol` and `reaches`
  fields are symbol ids, which become monikers. §7 names only graph.json;
  this is an omission, not a disagreement.
- **The version gate ADR-006 already promises.** Consumers that need one:
  `go/internal/web/artifacts.go`, `go/internal/knowledge/knowledge.go` (all
  five MCP tools read graph.json), `pipeline/src/hobbes/graphdiff.py`,
  `render.py`, `review.py`, `invariants/verdict.py`, `invariants/compile.py`,
  and `web/src/lib/graphModel.ts`.
- **Migration shim** — a v4 → v3 projection so the SPA, the knowledge
  tools, and the invariant emitters keep working untouched through M2–M4.

**Exit:** the v1 graph regenerates under v4; the web surface renders it
unchanged; every consumer refuses a version it does not know, with a test
per consumer proving the refusal.

---

## V2.M2 — Lane B: SCIP integration (4–5)

**Hard requirement before anything else in this milestone:** the staging
and safety contract in ADR-027 ("Lane B never writes to the target repo").
Seven clauses, each a quiet failure if skipped — copy-never-hardlink, a
derived staging path, removal that refuses anything outside the cache root,
staging lane A's discovered file set rather than `git ls-files`, and the
`.scip` file treated as an intermediate whose `project_root` never reaches
an artifact. Tests for the removal guard land in the same commit as the
removal code, not after.

Work:

- Run the indexers per language zone (the tsconfig-zoning lesson from M6
  applies directly), cache partial indexes by content hash, merge (§3.6).
- SCIP → graph adapter: occurrences to symbols, definitions and references
  to symbol edges at `tier: semantic`.
- **Degrade visibly (P6)** — indexer missing, indexer crashed, or repo does
  not typecheck ⇒ `extraction_errors` plus an ingest WARNING, and the graph
  still exists at syntactic tier. M6 already established this pattern for
  the ts-morph checker crash; reuse its shape.

**Exit (§7's bar, kept):** spot-check 20 semantic edges on the dogfood
repos — the bar is correctness of the join, ≥95%. Plus kbet and SELENEX
both ingest without regression.

**Recommended addition:** surface `tier` in the UI here — edge styling
already exists (ADR-023), so it is cheap, and it puts the first
human-visible v2 improvement at M2 instead of M6. See §"Visible value".

---

## V2.M3 — Lane A refactor + self-test (2–3)

Work:

- **Delete call resolution from `extract/graph.py`** — `_resolve_call`,
  `_SymbolTable`, and the symbol-edge production, i.e. ADR-007 rules 1–4:
  roughly 110 of the file's 256 lines. **Keep** `_Index`, `_NameEnv`, and
  module-level import resolution — §3.1 keeps approximate module edges in
  lane A on purpose, and they are exactly what the agreement self-test
  compares against.
- **Move test reach to lane B.** `collect_tests` consumes
  `graph["symbol_edges"]`; once those come from SCIP, reach gets more
  precise for free — and the deferred *per-test JS reach* item
  (`future_additions.md`) is subsumed rather than built.
- **`tssource.py` loses its symbol layer too.** §3.1 says lane A no longer
  resolves symbols, which retires M6's checker-resolved call edges in
  favour of `scip-typescript`. Naming it plainly: **M3 deletes working,
  hand-verified M6 code.** That is the intent of the architecture, but it
  should be a deliberate call rather than a discovery mid-milestone.
- **Lane-agreement report** as a CI check: wherever both lanes can produce
  the same module-level edge they must agree.

**Exit:** the disagreement report runs clean on the dogfood repos, or every
disagreement is an explained, filed bug.

---

## V2.M4 — Enrichment packs (3–4)

Work:

- Pack interface and registry. **`hobbes.yaml` needs an ADR before it is
  written** — where it lives, and whether it is personal. ADR-012
  gitignores all of `.hobbes/` in target repos, but an indexer/pack
  registry is a property of the *repo*, not of one person's environment, so
  it probably wants to be tracked. That is a genuine tension with ADR-012,
  not a detail.
- Port the existing framework knowledge into packs: FastAPI/Flask routes
  and CLI entry points (`extract/interfaces.py`), Express/Nest routes
  (`tsextract/extract.mjs`), and the Terraform cross-layer join
  (`extract/terraform.py`, 372 lines — the largest port, and the one with
  the most hand-verified behaviour behind it).
- Packs declare the tier their edges carry.

**Exit:** deleting a pack removes exactly its edges and nothing else;
adding it back restores them byte-for-byte.

---

## V2.M5 — Go language support (2–3)

First real test of P7. `scip-go` config plus a small Go enrichment pack
(`net/http` or chi routes).

**Test on this repo.** Hobbes currently cannot see its own runtime — 9.4k
lines of policy engine, proxy, sandbox, and web server, all invisible to
the graph it builds of itself. M5 closes the dogfood loop for the first
time, which makes it both the P7 proof and the most motivating milestone
in the plan.

**Exit:** a Go repo ingests with zero builder changes — checklist §3.7 was
literally sufficient, and the diff proves it.

---

## V2.M6 — Unified invariant checker (4–6)

Work:

- `check: graph` evaluation with tier-aware verdicts (proven vs suspected).
  **The seed exists**: `invariants/verdict.py` already judges
  forbidden-import in-process against `module_edges` and refuses to guess
  where the graph cannot see — "never a false pass". v2 generalises that
  and adds the tier distinction.
- **Migrate the six confirmed records.** They carry `compile.target` plus a
  structured `compile.rule`; v2 adds `check: graph | emit | soft`. I-4 is
  the awkward one: its statement is about parser ownership, and M3 changes
  which parsers exist, so it needs restating a third time.
- Retain and test `check: emit`. **Fold in a deferred item here:** the
  compiled CI configs have never actually been executed, because none of
  import-linter, dependency-cruiser, semgrep, or conftest is installed.
  M6's exit already requires graph verdicts to agree with emitted-tool
  verdicts where both exist — that agreement test is the natural place to
  finally run `lint-imports` for real.
- **Fold in a second deferred item:** soft verdicts are delta-based rather
  than source-based (deferred at M8). Reviewer sessions now have read-only
  mounts and the knowledge tools, so this is the milestone where that gets
  fixed.

**Exit:** the I-series invariants run under `check: graph` on a dogfood repo
and agree with the emitted-tool verdicts wherever both exist.

---

## V2.M7 — Rust proof (1–2)

rust-analyzer's native `scip` output on any Rust repo. **Exit:** ingestion
with zero new builder code — P7 demonstrated on a language nobody planned
for.

---

## Total and shape

**20–28 evenings** (§7 says 18–26; M0 adds one and M1's widened scope adds
one). Seven milestones plus a spike.

### Visible value — the one structural warning

**M0–M5 is roughly 15–19 evenings during which nothing a human sees
changes.** v1 never did that: every milestone from M0 to M8 ended in
something runnable, and that is a large part of why each one got a real
exit check. Two cheap mitigations, both already noted above:

- tier badges in the UI at **M2** (edge styling exists; it is a stylesheet
  and a legend),
- the lane-agreement report as a real command at **M3**, not just a CI
  artifact.

With those, M2 and M3 both end in something to look at.

---

## Risks

| Risk | Where it bites | Mitigation |
|---|---|---|
| Monikers unusable as node ids | M1 schema, then everything | M0 spike answers it before the schema freezes |
| SCIP is protobuf; reading it adds a dependency | M0/M2 | ADR-027 decides; the `scip` CLI adds least |
| Lane B needs a resolvable build; quality on messy real repos unknown | M2 | P6 degradation, plus four real repos at M0 |
| Two indexer version pins become a compatibility surface | M2 onward | §3.7 already requires a version pin in config |
| `hobbes.yaml` cuts against ADR-012 ("all of `.hobbes/` is personal") | M4 | ADR before the file exists |
| M3 deletes verified M6 code | M3 | Deliberate, stated up front; M2's ≥95% bar must pass first |
| Backlog rot while a 20-evening programme runs | throughout | Two one-line papercuts cleared before M0 |

---

## What v2 subsumes — do not build these first

From `future_additions.md`, these are **dissolved** by the architecture and
would be wasted work if done now:

- **Cross-language module-id namespacing** (the largest deferred item,
  Max-raised at M8 review) — moniker-keyed ids make `widget.py` vs
  `widget.ts` a non-question. Building the namespacing rewrite now means
  throwing it away at M1.
- **Per-test JS reach** — SCIP occurrences carry ranges; reach stops being
  file-level at M3.
- **Graph-diff rename detection** — stable monikers change the problem
  rather than solving it, but any path-matching heuristic built now is
  built against ids that are about to be replaced.

Everything else in `future_additions.md` sits **above** the extraction layer
(UI, narrative, decisions-in-git) and is unaffected either way.

---

## Deviations from architecture §7, collected

**All six approved and patched into §7 (commit alongside ADR-027).** A
seventh arrived from the spike itself: the indexer-config registry moves
from M4 to M2 (ADR-027, Decision 2).

1. **New V2.M0 spike** (+1 evening) — see real SCIP before freezing the
   schema.
2. **"Graph schema v2" is really schema v4** — the artifact schema is
   already at v3.
3. **V2.M1 widened** (+1 evening) — `tests.json` joins the contract change,
   and the version gate ADR-006 promises has to be built before a migration
   shim can mean anything.
4. **V2.M3 dependency made explicit** — test reach must move to lane B in
   the same milestone that strips lane A, or `tests.json` regresses. §7's
   ordering is right; the coupling was unstated.
5. **`hobbes.yaml` needs its own ADR** before M4 — it is a new artifact in
   tension with ADR-012.
6. **Tier in the UI at M2** and the agreement report as a command at M3, so
   the programme is not fifteen evenings of invisible work.
