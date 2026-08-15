# Hobbes constraints — the register of what Hobbes cannot tell you

**Status: load-bearing.** This is not a caveats page. Principle **P8**
(architecture v2 §1) makes an entry here part of the definition of done
for any decision that concedes information.

## Why this file exists

Hobbes' value is that a human can review at the concept level instead of
reading every line. That trade only works if the graph's silence is
*legible*. A gap that is known and stated costs a little trust. A gap the
artifact conceals while presenting a confident surface costs all of it:

> Hobbes is unusable if it's a known liar, even less usable if it's fake
> honest. — Max, 2026-08-15

So every place Hobbes drops, approximates, or cannot recover information
gets an entry below, and an entry is **not finished when it is written
here**. It is finished when it names the place a user meets the limit at
the moment it matters. ADR-029's resolution coverage is the model: 403
unaccounted call sites went from invisible to a per-file number a
reviewer can rank on, and it only got built because someone asked a
question that exposed the hole.

## How to read an entry

| field | means |
|---|---|
| **Cannot tell you** | the limit in a user's terms, not the implementation's |
| **Because** | the mechanism that makes it so |
| **Bites at** | the artifact, tool, or question that goes quiet |
| **You find out** | the surfacing mechanism — how a user learns it, in the moment |
| **Source** | the ADR or session that conceded it |

**Surfacing status** is the field that matters:

- **surfaced** — a real mechanism tells the user, where they are standing.
- **partial** — something says it, but not at the point of use, or not in
  terms the user can act on.
- **unsurfaced** — documented only. **This is the fake-honest case**, and
  it is debt, not a decision. Every `unsurfaced` row is a bug waiting for
  a milestone that can afford it.

Entries are numbered `C-n`, sequential and stable, and are never renumbered
or deleted — a constraint that stops being true is marked **lifted** with
the commit that lifted it, because "we used to lie about this" is itself
worth knowing.

This file is not `docs/future_additions.md`. That one parks deferred
*work*. This one registers conceded *information*. A deferral that loses
information appears in both, and the entries cross-reference.

---

## Extraction — the call graph

### C-1 — An absent call edge never means "this does not happen"
- **Cannot tell you:** whether code Hobbes shows no edge into is actually
  uncalled.
- **Because:** the symbol graph deliberately under-approximates. An edge
  is emitted only when a callee resolves; dynamic dispatch, higher-order
  calls, and calls through values are omitted rather than guessed, because
  a false edge is worse than a missing one.
- **Bites at:** `who_calls`, `tests_guarding`, dead-code intuitions, and
  any invariant phrased as "nothing calls X".
- **You find out:** *partial.* Resolution coverage (C-2) gives the
  denominator per file since ADR-029, but nothing states the rule at the
  point where a reviewer would draw the wrong conclusion.
- **Source:** ADR-007.

### C-2 — Some call sites resolve to nothing, and the count is the honest form
- **Cannot tell you:** where 13.1% of this repo's call sites go (403 of
  3,070 at the ADR-029 measurement).
- **Because:** the remainder are dominated by builtins (`len`,
  `isinstance`) and by dynamically typed test fixtures
  (`capsys.readouterr`, `monkeypatch.setenv`) — receivers whose type
  Pyright cannot know at the call site. That is a real limit of static
  semantics, not a bug to be fixed.
- **Bites at:** trust in any one module's call graph. `review.py` is 56%
  accounted; `policy.py` is 100%.
- **You find out:** **surfaced** — `graph.json.resolution_coverage`, per
  file: sites, resolved, external, unresolved.
- **Note:** deliberately counts, never a confidence score. An edge with no
  named target cannot be drawn, checked, or cited — it is C-1's false edge
  wearing a probability.
- **Source:** ADR-029.

### C-3 — Standard-library dependencies are invisible
- **Cannot tell you:** that a module depends on `subprocess`, `os`, or
  `json`.
- **Because:** stdlib imports are dropped as noise at resolution; only
  third-party imports become `ext:` nodes.
- **Bites at:** any question of the form "what does this module touch" —
  notably security-shaped ones, where `subprocess` is exactly the import
  a reviewer wants flagged.
- **You find out:** **unsurfaced.** The graph simply has no such nodes and
  says nothing. A reader cannot distinguish "imports no stdlib" from
  "stdlib not modelled".
- **Source:** ADR-007.

### C-4 — Pytest fixtures do not appear in test reach
- **Cannot tell you:** that a test exercises code reached only through a
  fixture.
- **Because:** fixtures are dynamic injection; reach is the static closure
  over call edges from the test symbol.
- **Bites at:** `tests_guarding`, behavioral coverage, and `hobbes review`'s
  "unguarded new code" verdict — a fixture-heavy suite looks thinner than
  it is.
- **You find out:** **unsurfaced.** Reach lists are short and give no
  reason.
- **Source:** ADR-007. See also `future_additions.md` → test-reach trimming.

### C-5 — Routes with computed paths are skipped
- **Cannot tell you:** that an endpoint exists when its path is an
  f-string or a variable rather than a literal.
- **Because:** a route that cannot be pinned to a literal cannot be cited
  at evidence, and inventing the path would be a false interface.
- **Bites at:** `interfaces.json`, the Tests and Docs tabs' sense of the
  app's surface area.
- **You find out:** **unsurfaced.** The route is absent with no record
  that a decorator was seen and declined.
- **Source:** ADR-007.

### C-6 — A semantic index cannot say what a reference syntactically was
- **Cannot tell you:** from lane B alone, whether an occurrence is a call,
  a type annotation, or an `except` clause.
- **Because:** SCIP carries a `syntax_kind` that would separate them, and
  `scip-python` populates it for **0 of 8,575** occurrences.
- **Bites at:** it would have made `who_calls` silently become
  `who_references`. This is the whole reason the lanes join on ranges
  before a graph exists rather than merging finished edges.
- **You find out:** **surfaced** — resolutions that no call site claimed
  are typed `uses`, not `calls`, so the two questions stay separable in
  the artifact.
- **Source:** ADR-029.

### C-7 — Lane A's fallback edges are guesses, and say so
- **Cannot tell you:** with proof, where a call goes when the indexer
  could not resolve it (131 edges on this repo at the M2 exit).
- **Because:** lane A's resolver runs on four static rules and can be
  wrong — the M2 measurement found a real false positive, a local
  variable named `write` bound to a module-level function.
- **Bites at:** any consumer that treats all call edges as equally true.
- **You find out:** **surfaced** — `tier: syntactic` on the edge, drawn
  thinner, dimmer and dashed in the graph (ADR-023 styling, M2).
- **Source:** ADR-029.

### C-8 — With no working indexer, the entire symbol layer is approximate
- **Cannot tell you:** anything semantic about a repo whose language has
  no indexer wired, whose indexer is missing, or whose environment is not
  installed. The call graph falls back to lane A's four rules wholesale.
- **Because:** semantics come from a batch indexer that has to be present
  and has to be able to resolve. Lane A is the floor, by design (P6).
- **Bites at:** every symbol-level question, on any box without `scip/`
  installed, and on every language v2 has not reached yet.
- **You find out:** **surfaced** — `extraction_errors` plus an ingest
  WARNING when a lane degrades, and the tier on every edge when it does
  not.
- **Source:** architecture v2 §3.2/P6, ADR-029. Registered at V2.M3, when
  demoting lane A's resolver made the floor explicit rather than incidental.

### C-9 — Only four descriptor kinds become graph symbols
- **Cannot tell you:** about parameters, locals, or meta symbols; roughly
  **86%** of what an indexer defines is dropped.
- **Because:** the graph models namespaces, types, methods and terms.
  kbet's frontend alone offers 6,696 definitions against 949 graph-worthy;
  the whole v1 dogfood graph has 834 symbols.
- **Bites at:** any expectation that the symbol layer is a complete index
  of the code. It is an architectural view, not an IDE.
- **You find out:** **partial.** The filter is stated in ADR-027 and the
  omission is uniform, so it does not mislead about *specific* code — but
  nothing in the artifact declares the modelled vocabulary.
- **Source:** ADR-027, Decision 3.

### C-10 — Node ids carry no version, so cross-version merging is out
- **Cannot tell you:** which version of a package a symbol belongs to.
- **Because:** `--project-version` is pinned to a constant, since its
  default is the git revision and would re-key every node on every commit
  — which would make `hobbes diff` report the whole repo as
  removed-and-re-added, destroying the thing v2 exists to sharpen.
- **Bites at:** a future multi-repo graph merge, which must key on package
  identity alone. Nothing today.
- **You find out:** **n/a — no user-visible effect yet.** Registered
  because it is a paid cost with a deferred bill.
- **Source:** ADR-027, Decision 1.

## Extraction — TypeScript and JavaScript

### C-11 — JS/TS test reach is per *file*, not per test case
- **Cannot tell you:** which specific `it()` case guards which code. Every
  case in a test file shares the file's whole imports-plus-calls closure.
- **Because:** JS test bodies are anonymous closures, not symbols, so
  there is nothing to attribute a call to.
- **Bites at:** `tests_guarding` and behavioral coverage **over-report**
  for JS — the one place in the system where a limit inflates a number
  rather than shrinking it, which makes it the most dangerous kind.
- **You find out:** **unsurfaced.** A JS test row looks exactly like a
  pytest row, whose reach is per-case and precise.
- **Source:** ADR-021, deferred at M6. `future_additions.md` → per-test JS
  reach. V2.M3 is the milestone that can afford it, since SCIP occurrences
  carry ranges.

### C-12 — Imports across tsconfig zones do not resolve
- **Cannot tell you:** that package A imports package B in a monorepo,
  when each has its own `tsconfig.json`.
- **Because:** each zone is a separate ts-morph Project (and a separate
  indexer run), and cross-program resolution is not attempted.
- **Bites at:** monorepo module edges — the highest-level architectural
  fact, missing exactly where the architecture is most interesting.
- **You find out:** **unsurfaced.** The edge is simply absent.
- **Source:** M6, `future_additions.md` → per-package tsconfigs.

### C-13 — Test files using injected globals report framework `unknown`
- **Cannot tell you:** whether a test file with no framework import is
  jest or vitest.
- **Because:** framework detection reads imports, and globals-style suites
  import nothing.
- **Bites at:** the per-test `framework` field only; the tests are still
  inventoried.
- **You find out:** **surfaced** — the field literally says `"unknown"`
  rather than guessing.
- **Source:** ADR-021, M6.

### C-14 — CLI entry points come from `pyproject.toml` only
- **Cannot tell you:** about a JS package's `bin` entry points.
- **Bites at:** `interfaces.json` on TS/JS repos.
- **You find out:** **unsurfaced.** The list is empty and reads as "no CLI".
- **Source:** M6, `future_additions.md`.

## Extraction — cross-layer

### C-15 — A node-id collision across languages drops a file from the graph
- **Cannot tell you:** anything about the losing file — a repo-root
  `widget.py` and `widget.ts` both want the id `widget`, and merge order
  (Python, HCL, TS) decides.
- **Because:** ids are path-derived per layer and are not namespaced on
  collision. Fixing it properly means rewriting ids across a whole layer's
  nodes, edges, symbols, tests and routes.
- **Bites at:** the graph's completeness, by an accident of pipeline order.
- **You find out:** **surfaced** — one `extraction_errors` record per
  collision, naming both paths and the fix, plus an ingest WARNING. It was
  data loss decided by ordering *in silence* before M8 review.
- **Source:** M8 review, `future_additions.md` → cross-language namespacing.

### C-16 — Dependency-degradation detection reads only the repo root's manifest
- **Cannot tell you:** that an environment is uninstalled when the
  manifest lives in a subdirectory — this repo's own Python deps are in
  `pipeline/pyproject.toml`, so its own degradation check is inert.
- **Because:** `declared_dependencies` looks at `<repo>/pyproject.toml`.
- **Bites at:** ADR-027 Decision 4's check, on exactly the repo Hobbes
  dogfoods against.
- **You find out:** **unsurfaced**, and worse than unsurfaced — the check
  *appears* to run and reports nothing.
- **Source:** BUILDLOG 2026-08-14 (seventh), found via SELENEX.

## Narrative, invariants, and review

### C-17 — Narrative claims are pinned, not proven
- **Cannot tell you:** that a module doc's sentence is true — only which
  line it was written from, at which SHA.
- **Because:** narrative is LLM-written over the deterministic skeleton
  (P5). Pins make a claim checkable by a human; they do not check it.
- **Bites at:** the Docs tab and `get_module_doc`.
- **You find out:** **surfaced** — every claim carries `{text, pins}` and
  the UI resolves a pin to its source line, so disbelief is one click.
  Staleness badges on SHA drift.
- **Source:** ADR-019.

### C-18 — Soft invariant verdicts judge the delta, not the source
- **Cannot tell you:** whether a change violates a `soft` invariant in a
  way that needs the diff hunks — the reviewer session sees the
  architecture delta and the changed-file list, not the files.
- **Because:** soft verdicts run through the tool-less ADR-020 runner.
  The M8 exit-check sessions said so unprompted.
- **Bites at:** `hobbes review --soft`.
- **You find out:** **partial** — the sessions tend to disclose it in
  their own reasoning, which is honesty by accident rather than by
  mechanism.
- **Source:** M8, `future_additions.md`. V2.M6 is the fix.

### C-19 — The compiled CI configs have never been executed
- **Cannot tell you:** that a generated import-linter `.ini`,
  dependency-cruiser config, semgrep rule, or Rego policy actually runs.
- **Because:** compilation is pure text generation by design (no target
  toolchain needed), and none of the four tools is installed here. The
  emitters are asserted against documented formats.
- **Bites at:** `hobbes invariants compile` output, the first time anyone
  runs it in real CI.
- **You find out:** **unsurfaced.** The files look finished.
- **Source:** M8, `future_additions.md`. V2.M6's exit finally runs one.

### C-20 — Decisions do not survive a fresh clone
- **Cannot tell you:** on a new machine or a re-clone, that you already
  approved an invariant or confirmed a policy. The whole queue asks again.
- **Because:** ADR-012 gitignores all of `.hobbes/` in target repos, so
  the ledger, invariants and policies are per-clone, per-machine.
- **Bites at:** `hobbes up`'s "set once, holds until you change it"
  promise, which holds within a workspace and silently does not across
  them.
- **You find out:** **unsurfaced.** Re-asking looks like a first run.
- **Source:** ADR-026, Max-confirmed as a known limitation.

### C-21 — Narration re-proposes invariants that are already confirmed
- **Cannot tell you:** that an inferred invariant is a reworded duplicate
  of a record you settled months ago — decisions key on a content hash of
  (statement, scope), so a rewording does not match.
- **Because:** the inference unit is told about the repo but not about
  `.hobbes/invariants/`.
- **Bites at:** the decision queue's signal-to-noise. All six of this
  repo's inferred records correspond 1:1 to I-1..I-6 and none match by key.
- **You find out:** **partial** — the queue is noisy in a way an attentive
  user will recognise, which is not the same as being told.
- **Source:** ADR-026, `future_additions.md`.

### C-22 — Lane B links the repo's `node_modules`, and trusts it not to be written
- **Cannot tell you:** with structural certainty that indexing a TypeScript
  repo cannot modify its dependency tree. The staging tree symlinks
  `node_modules` rather than copying it (222 MB on kbet), so for the
  duration of an index there is a live handle into the user's tree.
- **Because:** copying is infeasible at that size, and the alternative that
  preserves the copy — an absolute `paths` fallback — measured a **6.4%
  loss of semantic references**, which is the lane's whole output.
- **Bites at:** nothing observed. Two properties were verified rather than
  assumed: a full index modified **0 files** under the real
  `node_modules`, and `shutil.rmtree` unlinks a symlinked directory instead
  of recursing into it, so removing a stage cannot delete the target.
- **You find out:** **surfaced by test, not by artifact** — both properties
  carry regression tests (`test_staging.py`), so a change that breaks
  either fails the suite rather than a user's machine. This is the correct
  surfacing for a constraint whose audience is a future maintainer rather
  than a reviewer.
- **Honest residue:** measured, not structurally enforced. A future indexer
  that emits, or a dependency with a build step run during indexing, would
  invalidate it and the tests are what would catch it.
- **Source:** ADR-032.

### C-23 — TypeScript semantics need an installed dependency tree
- **Cannot tell you:** where a call goes when its receiver's type comes
  from a package that is not installed. Measured on kbet with no
  `node_modules`: **19% of internal references and 73% of external
  references disappear**, and 20 of 23 packages resolve to nothing.
- **Because:** the indexer's resolution is whole-program type inference,
  and an absent dependency has no types to infer from. It exits 0 and
  produces a plausible index regardless.
- **Bites at:** any TS repo ingested without `npm install` having been run
  — a fresh clone, a CI job that skips install, a monorepo package the user
  never built.
- **You find out:** **surfaced** — `dependency_coverage: {declared,
  resolved, missing[]}` is reported on every run, plus an
  `extraction_errors` entry and an ingest WARNING below a ratio.
  Previously **unsurfaced and actively misleading**: the old all-or-nothing
  test could never fire for TypeScript, because the indexer bundles
  `typescript` itself and that one always-resolving package kept the
  "everything missing" condition false forever. 1 of 23 resolved, and it
  said nothing.
- **Honest residue:** a *partially* installed environment still degrades in
  proportion, and the ratio is a threshold rather than a proof.
- **Source:** ADR-032, found by the control variant in the V2.M3 spike.

---

## Debt summary

Nine of twenty-three entries are **unsurfaced** (C-3, C-4, C-5, C-11, C-12,
C-14, C-16, C-19, C-20). That number is the point of keeping the register:
it was not knowable before this file existed, and it is the backlog P8
generates.

Ranked by how badly each misleads, worst first:

1. **C-11** — inflates JS test coverage; a file-level reach row is
   indistinguishable from a precise pytest one.
2. **C-16** — a degradation check that appears to run and reports nothing,
   on the repo Hobbes dogfoods against.
3. **C-3** — "imports no stdlib" and "stdlib not modelled" look identical,
   and the question is usually a security one.

The rest stay quiet rather than lying, which is a real difference.

**Track record so far:** two of the three entries added at V2.M3 were
*already true and already invisible* before the register existed — C-23 in
particular had a check written specifically to catch it that could not fire
under any circumstances. That is the argument for P8 restated as evidence:
both were documented honestly in an ADR at the moment of decision, and both
went on to mislead anyway.
