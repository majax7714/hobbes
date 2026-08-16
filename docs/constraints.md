# Hobbes constraints — the register of what Hobbes cannot tell you

**Status: load-bearing.** This is not a caveats page. Principle **P8**
(`hobbes-architecture.md` §1) makes an entry here part of the definition of
done for any decision that concedes information, and **P9** extends that to
information conceded *for* us by a language provider we run — those entries
carry a `Provider` line naming the provider and pinned version, because
unlike our own concessions they can end on an upstream release (ADR-034).

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
| **Provider** | *(inherited limits only, P9)* the provider and pinned version, and whether an upgrade could lift it |
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
- **Provider (P9):** inherited from `@sourcegraph/scip-python` **0.6.6**.
  `syntax_kind` is optional in the SCIP schema, so this is a gap in the
  indexer rather than in SCIP. **Liftable on upgrade** — if a future
  release populates it, lane A's call-site detection becomes a choice
  rather than a necessity. Re-check on any version bump.
- **Source:** ADR-029; owned as ours under P9 (ADR-034).

### C-7 — Lane A's fallback edges are guesses, and say so
- **Cannot tell you:** with proof, where a call goes when the indexer
  could not resolve it (131 edges on this repo at the M2 exit).
- **Because:** lane A's resolver runs on four static rules and can be
  wrong — the M2 measurement found a real false positive, a local
  variable named `write` bound to a module-level function.
- **Bites at:** any consumer that treats all call edges as equally true.
- **You find out:** **surfaced** — `tier: syntactic` on the edge, drawn
  thinner, dimmer and dashed in the graph (ADR-023 styling, M2), and
  marked `(syntactic — approximate)` per caller in `who_calls`, so an
  agent reading the tool output sees it too and not only a human reading
  the graph (V2.M3).
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
- **Source:** architecture §3.2/P6, ADR-029. Registered at V2.M3, when
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
- **Provider (P9):** ours, not inherited — the descriptor filter is
  Hobbes's choice over what `@sourcegraph/scip-python` **0.6.6** and
  `@sourcegraph/scip-typescript` **0.4.0** emit. Listed here because it is
  easily mistaken for a provider limit: the indexers *do* report these
  symbols and Hobbes drops them. Not liftable by an upgrade.
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

### C-11 — JS/TS test reach is per *file*, not per test case — **LIFTED at V2.M3**
- **Was:** every case in a test file shared the file's whole
  imports-plus-calls closure, so `tests_guarding` and behavioural coverage
  **over-reported** for JS — the one place in the system where a limit
  inflated a number rather than shrinking it, and unsurfaced, because a JS
  row looked exactly like a precise pytest row.
- **Lifted by:** the helper now records each case's extent and the join
  carries ranges, so a call is attributed to the `it()` that encloses it;
  calls outside every case (a `beforeEach`, a `describe` body) are shared
  by all cases in the file, because that code really does run for each.
  Measured on kbet: reach went from a flat 7.3 symbols for every case in a
  file to per-case, with cases in the same file now differing.
- **Source:** ADR-021 (the limit), V2.M3 (the lift). Superseded by C-24,
  which is the honest residue.

### C-24 — A test that only *renders* a component does not reach it
- **Cannot tell you:** that a React component test guards the component it
  renders. Reach is the closure over **call** edges, and `<BetCard />` is a
  JSX element, not a call site — it lands in the graph as a `uses` edge
  (182 of them on kbet), which reach deliberately does not follow.
- **Because:** distinguishing "renders this component" from "names this
  type in an annotation" needs the `syntax_kind` SCIP does not populate
  (C-6). Both are `uses`.
- **Bites at:** `tests_guarding` on component-heavy repos, and `hobbes
  review`'s unguarded-new-code verdict.
- **Direction is deliberate.** This *under*-reports, where C-11
  over-reported, and that asymmetry is the point: under-reporting makes
  `review` flag code as unguarded and a human looks; over-reporting lets
  code claim guarding it does not have. Given a choice between two
  inaccuracies, reach takes the one that fails toward attention. It also
  keeps JS reach computed exactly as pytest reach is (ADR-007's closure
  over calls), which is what C-11 was really about.
- **You find out:** **unsurfaced.** A render-only test row shows an empty
  `reaches` and gives no reason.
- **Candidate fix:** record JSX elements as call sites in the syntax
  provider — a JSX instantiation *is* a call in every meaningful sense —
  or seed a case's reach from the `uses` edges inside its own range.
  Deferred to V2.M6, where the reviewer flow is the consumer that would
  feel it.
- **Source:** V2.M3.

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
- **Bites at:** originally filed as a signal-to-noise cost — all six of this
  repo's inferred records correspond 1:1 to I-1..I-6 and none match by key.
  **The observed cost is worse than that, and the evidence is now in.**
- **Observed 2026-08-15 — a duplicate was approved carrying a claim its
  original had been corrected to remove.** Promoting from the inferred set
  through the surface produced **I-9**, whose statement ends "all other
  pushes escalate". That is false: `.hobbes/policies/repo.policy` denies
  `git push*` outright. It is false in *exactly* the way the M5 inferred
  wording of I-3 was false, which the M8 promotion caught and rewrote —
  I-3's file still carries the note explaining why. Narration re-proposed
  the uncorrected text, the queue could not show that a corrected record
  already existed, and the approval versioned the false claim on a record
  Hobbes will now compile and check against.
- **You find out:** **partial, and now known to be insufficient.** The queue
  is noisy in a way an attentive user will recognise — but recognising
  *noise* is not recognising that this particular reword reverses a
  correction. Nothing shows the reviewer the neighbouring confirmed record,
  so the decision surface is where this has to be fixed: an inferred
  statement should arrive next to the confirmed records that overlap its
  scope.
- **Source:** ADR-026, `future_additions.md`. Instance recorded
  2026-08-15.

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
- **Provider (P9):** inherited from `@sourcegraph/scip-typescript`
  **0.4.0**. **Not liftable by an upgrade** — whole-program type inference
  cannot infer from types that are not on disk, so this is a property of
  the approach rather than of the release. The surfacing is the permanent
  answer here, not a placeholder for a fix.
- **Source:** ADR-032, found by the control variant in the V2.M3 spike;
  owned as ours under P9 (ADR-034).

## Extraction — enrichment packs

### C-25 — A pack cannot be turned off for a repo where it misfires
- **Cannot tell you:** nothing, directly. What it costs you is the ability
  to *stop* a pack whose edges are wrong for your repo — an Express route
  matched on a receiver that only looks like a router, a `packages` edge to
  a path that is a coincidence.
- **Because:** packs are registered in code and activated by detection
  (ADR-035). There is deliberately no `hobbes.yaml`, so there is no place
  to write "not this one, not here". The alternative — a per-repo registry
  file — collides with ADR-012's "all of `.hobbes/` is personal", and
  inventing that file before anyone had hit this was the speculative
  abstraction the decision avoided.
- **Bites at:** any repo where a framework heuristic guesses wrong. Nothing
  observed yet on the four sanctioned repos, which is the honest reason
  this is a registered cost rather than a solved problem.
- **You find out:** **partial** — `graph.json`'s `packs` list names every
  pack that ran, so a wrong edge is *attributable* to the pass that made
  it. Attributable is not suppressible: you can see which pack to blame and
  you cannot stop it.
- **Candidate fix:** a per-repo disable list. It must live somewhere that
  survives a clone, which makes it the ADR-012 question this milestone
  deferred rather than answered — a pack set is a property of the repo, and
  ADR-012 says the repo's `.hobbes/` is not.
- **Source:** ADR-035, V2.M4.

---

## Debt summary

Nine of twenty-five entries are **unsurfaced** (C-3, C-4, C-5, C-12, C-14,
C-16, C-19, C-20, C-24). One entry — C-11 — has been **lifted**. That
churn is the point of keeping the register: none of it was knowable before
this file existed, and what remains is the backlog P8 generates.

V2.M4 added one entry (**C-25**) and it is *partial* rather than
unsurfaced, because `graph.json`'s `packs` list was added in the same
commit as the pack layer. Attributing a layer to the pass that produced it
was the cheap half of the answer; suppressing it is the half that is
deferred.

Ranked by how badly each misleads, worst first:

1. **C-16** — a degradation check that appears to run and reports nothing,
   on the repo Hobbes dogfoods against.
2. **C-3** — "imports no stdlib" and "stdlib not modelled" look identical,
   and the question is usually a security one.
3. **C-24** — an empty `reaches` on a component test reads as "nothing
   guards this", though it fails in the safe direction by design.

The rest stay quiet rather than lying, which is a real difference.

**Nothing left in the register inflates a number.** C-11 was the only
entry that made a claim larger than the truth, and V2.M3 lifted it; C-24,
its residue, was deliberately chosen to fail toward attention instead.
Every remaining limit under-reports or stays silent — so a Hobbes number
can now be read as a floor, which is a property worth defending in later
milestones.

**Track record so far:** three of the four entries touched at V2.M3 were
*already true and already invisible* before the register existed — C-23 in
particular had a check written specifically to catch it that could not fire
under any circumstances, and C-11 had been honestly documented at M6 and
went on misleading for two milestones. That is the argument for P8 restated
as evidence: being written down in an ADR at the moment of decision did not
stop either of them.
