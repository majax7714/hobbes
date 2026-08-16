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

### C-3 — Standard-library dependencies are invisible — **LIFTED by ADR-038**
- **Was:** stdlib imports were dropped as noise at resolution for Python
  (`sys.stdlib_module_names`, ADR-007) and JS/TS (Node builtins, M6), so
  "imports no stdlib" and "stdlib not modelled" looked identical — and the
  question is usually a security one, where `subprocess` is exactly the
  import a reviewer wants flagged. V2.M5 made it worse without touching
  it: Go's layer never had the filter, so `ext:os` on Go modules taught
  the reader stdlib *was* modelled and a Python module's silence read as
  positively clean. The asymmetry was found by the 2026-08-15 register
  audit, unregistered by ADR-037.
- **Lifted by:** ADR-038 (same day) — every syntax provider now emits
  `ext:` nodes for stdlib like any other dependency. Python drops the
  skip; TS keeps builtins normalised to a `node:`-prefixed name
  (`ext:node:fs`, one node however the import is spelled, never shared
  with an npm package of the same name); Go was already right, just alone.
  Externals stay hidden by default in the surface (ADR-023) — a view
  choice, where the old rule was an information choice.
- **Source:** ADR-007 (the rule), ADR-038 (the lift), Max's call:
  "no need to hide what hobbes does capture."

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
- **You find out:** **surfaced** (2026-08-15, the pre-M6 register sweep) —
  each HTTP pack now emits one `extraction_errors` record per declined
  registration, naming file:line and saying the route is absent rather
  than guessed. The constraint itself stands: the route still cannot be
  reported, only its absence is now legible. Surfacing it also fixed a
  quiet inversion in the Nest reader, which had been *emitting* a route
  with the computed segment dropped — a path the app does not serve, worse
  than C-5's absence; computed Nest arguments now decline like the rest.
- **Source:** ADR-007 (the rule). The mechanism lives in the enrichment
  packs since V2.M4 (ADR-035) — `http-python`, `http-ts`, and V2.M5's
  `http-go` each cite this entry and skip computed paths the same way, so
  the constraint now spans five frameworks across three languages.
  Surfaced 2026-08-15 (tsextract helper v3).

### C-6 — A semantic index cannot say what a reference syntactically was
- **Cannot tell you:** from lane B alone, whether an occurrence is a call,
  a type annotation, an `except` clause, or a Go type conversion.
- **Because:** SCIP carries a `syntax_kind` that would separate them, and
  **no indexer populates it**. `scip-python` leaves it unset for 0 of
  8,575 occurrences; `scip-go` for **0 of 18,682** (V2.M5, ADR-037). Two
  independent implementations, the same omission — and the field is
  optional in SCIP, so this is the state of the ecosystem rather than one
  tool's gap. Registered first as a `scip-python` limitation and
  **generalised at V2.M5**, when measuring a second indexer showed the
  original framing was too narrow.
- **Bites at:** it would have made `who_calls` silently become
  `who_references`. This is the whole reason the lanes join on ranges
  before a graph exists rather than merging finished edges.
- **You find out:** **surfaced** — resolutions that no call site claimed
  are typed `uses`, not `calls`, so the two questions stay separable in
  the artifact.
- **Provider (P9):** inherited from **every** indexer measured —
  `@sourcegraph/scip-python` 0.6.6 and `scip-go` 0.2.7. **Not liftable by
  upgrading one of them**, which is what changed at V2.M5: it would have to
  be fixed by all of them, and a language whose indexer still omitted it
  would silently lose its call graph. This is why the add-a-language
  checklist requires a syntax provider (§3.7) rather than suggesting one.
  Re-check per indexer on any version bump; a single fix lifts nothing on
  its own.
- **Source:** ADR-029 (registered), ADR-037 (generalised); owned as ours
  under P9 (ADR-034).

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

### C-9 — Only five descriptor kinds become graph symbols
- **Cannot tell you:** about parameters, locals, or meta symbols; roughly
  **86%** of what a Python or TS indexer defines is dropped (**72%** for
  Go — 27.9% of `scip-go`'s definitions are graph-worthy, ADR-037).
- **Because:** the graph models namespaces, types, methods, terms and —
  since V2.M7 — macros (`macro_rules!` is architecture in Rust the way a
  function is; only rust-analyzer emits the descriptor, ADR-040).
  kbet's frontend alone offers 6,696 definitions against 949 graph-worthy;
  the whole v1 dogfood graph has 834 symbols.
- **Bites at:** any expectation that the symbol layer is a complete index
  of the code. It is an architectural view, not an IDE.
- **You find out:** **partial.** The filter is stated in ADR-027 and the
  omission is uniform, so it does not mislead about *specific* code — but
  nothing in the artifact declares the modelled vocabulary.
- **Provider (P9):** ours, not inherited — the descriptor filter
  (`GRAPH_KINDS` in the shared `scip/index.mjs` helper) is Hobbes's choice
  over what `@sourcegraph/scip-python` **0.6.6**,
  `@sourcegraph/scip-typescript` **0.4.0**, `scip-go` **0.2.7** (added
  V2.M5), and `rust-analyzer` **1.97.1** (added V2.M7) emit. Listed here
  because it is easily mistaken for a provider limit: the indexers *do*
  report these symbols and Hobbes drops them. Not liftable by an upgrade.
- **Source:** ADR-027, Decision 3. Amended by ADR-040 (macro joined the
  set).

### C-10 — Node ids carry no version, so cross-version merging is out
- **Cannot tell you:** which version of a package a symbol belongs to.
- **Because:** the indexer's version flag is pinned to a constant —
  `--project-version` for scip-python/scip-typescript, `--module-version`
  for scip-go (the same decision under a third flag name, ADR-037) —
  since its default is the git revision and would re-key every node on
  every commit, which would make `hobbes diff` report the whole repo as
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

### C-24 — A test that only *renders* a component does not reach it — **LIFTED 2026-08-15**
- **Was:** reach is the closure over **call** edges, and `<BetCard />` was
  a JSX element, not a call site — a `uses` edge reach deliberately did
  not follow, so a render-only test showed an empty `reaches` that read
  as "nothing guards this". The entry's asymmetry argument (under-report
  rather than over-report) held while the choice was between two
  inaccuracies; the fix removes the inaccuracy instead of picking a
  direction.
- **Lifted by:** the tsextract syntax provider records a JSX
  instantiation as a call site (Max-approved, 2026-08-15) — the
  component executes when the element renders, so the site is a call in
  the sense reach cares about. The join then treats it like any other
  site: lane A's fallback where it resolves, promoted to `semantic`
  where SCIP confirms. Measured on kbet: 12 direct test→component render
  edges, **all semantic tier** (BetCard among them — this entry's own
  example), and 108 of 174 tests now reach a component, with closure
  over what the component itself renders (`ActiveBetsStrip →
  StripButton`). The lanes agree on both kbet and this repo.
- **Honest residue — the outliers of "a JSX instantiation is a call":**
  only component-like tags count (a capitalised identifier or a dotted
  tag; `<div>` is a string at runtime, not code the repo owns); the
  framework mediates *when* the body runs, exactly as any call behind a
  branch mediates whether its callee runs; a closing tag is not a second
  site; and a component passed as a *value* (`<Route component={Card}>`)
  is still a `uses` edge, because nothing at that site instantiates it.
  kbet's remaining 44 empty-reach tests are store/logic tests in plain
  `.ts` files — a different residual (calls through mocks and store
  indirection), not this entry's subject.
- **Source:** V2.M3; lifted 2026-08-15, after V2.M6 and before V2.M7.

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
- **Cannot tell you:** about a JS package's `bin` entry points, or a Go
  binary — a `package main` under `cmd/` is exactly the shape this repo's
  own four binaries take, and `interfaces.json` on the dogfood repo lists
  `hobbes` and `mini` (Python console scripts) while `hobbes-policy`,
  `hobbes-proxy`, `hobbes-session` and `hobbes-web` are absent.
- **Because:** the `cli-python` pack (ADR-035, which owns this mechanism
  since V2.M4) reads `[project.scripts]` from every `pyproject.toml`, and
  it is the only CLI source; nothing reads `package.json` `bin` or Go
  main packages.
- **Bites at:** `interfaces.json` on TS/JS and Go repos.
- **You find out:** **unsurfaced.** The list is empty and reads as "no CLI".
- **Source:** M6, `future_additions.md`; widened to Go at the 2026-08-15
  register audit.

## Extraction — cross-layer

### C-15 — A node-id collision across languages drops a file from the graph
- **Cannot tell you:** anything about the losing file — a repo-root
  `widget.py` and `widget.ts` both want the id `widget`, and merge order
  decides: Python is the base graph, then TS, then Go (V2.M5), then the
  pack layer's nodes, `tf:` among them, last (V2.M4).
- **Because:** ids are path-derived per layer and are not namespaced on
  collision. Fixing it properly means rewriting ids across a whole layer's
  nodes, edges, symbols, tests and routes.
- **Bites at:** the graph's completeness, by an accident of pipeline order.
- **You find out:** **surfaced** — one `extraction_errors` record per
  collision, naming both paths and the fix, plus an ingest WARNING. It was
  data loss decided by ordering *in silence* before M8 review.
- **Source:** M8 review, `future_additions.md` → cross-language namespacing.

### C-16 — Dependency-degradation detection reads only the repo root's manifest — **LIFTED 2026-08-15**
- **Was:** `declared_dependencies` looked only at `<repo>/pyproject.toml`,
  so a repo whose manifest lives in a subdirectory — this repo's own deps
  are in `pipeline/pyproject.toml` — ran ADR-027 Decision 4's check
  against an empty list. Worse than unsurfaced: the check *appeared* to
  run and reported nothing, on exactly the repo Hobbes dogfoods against.
- **Lifted by:** the pre-M6 register sweep — the function now unions
  every `pyproject.toml` in the repo via the same pruned walk the CLI
  pack uses (`iter_pyprojects`), with the subdirectory case pinned by a
  test written in this repo's own shape. The TS half was already
  per-zone (`declared_npm_dependencies` takes the zone's `package.json`)
  and needed nothing.
- **Source:** BUILDLOG 2026-08-14 (seventh), found via SELENEX; lifted
  2026-08-15.

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

### C-18 — Soft invariant verdicts judge the delta, not the source — **LIFTED at V2.M6**
- **Was:** soft verdicts ran through the tool-less ADR-020 runner, so a
  reviewer session judged from the architecture delta and a changed-file
  list, not the files — honest but shallow, and the M8 exit-check
  sessions said so unprompted.
- **Lifted by:** ADR-039 — `--soft` runs each in-scope soft invariant in
  the M4 reviewer sandbox: worktree mounted read-only at the review's
  head ref (`hobbes-session --ref`), the knowledge tools, and the range's
  diff hunks in the prompt. A missing sandbox is an error recorded on the
  answer, never a silent fallback to the delta prompt — that would have
  quietly recreated this entry.
- **Honest residue:** needs podman, the session image, and quota; the
  error path is the surfacing when they are absent.
- **Source:** M8, `future_additions.md`; lifted at V2.M6 (ADR-039).

### C-19 — Three of the four compiled CI configs have never been executed
- **Cannot tell you:** that a generated dependency-cruiser config,
  semgrep rule, or Rego policy actually runs. **import-linter is no
  longer on this list** (V2.M6, ADR-039): it is a dev dependency, the
  agreement suite runs `lint-imports` over generated configs on every
  test run, and the first real execution found a real emitter bug —
  unmatched ignore pairs failed a clean repo — which is the argument for
  narrowing this entry rather than lifting it: the other three emitters
  are exactly as untested as that one was.
- **Because:** compilation is pure text generation by design (no target
  toolchain needed), and the other three tools are not installed here.
  Those emitters are asserted against documented formats only.
- **Bites at:** `hobbes invariants compile` output for dep-cruiser,
  semgrep, and rego, the first time anyone runs them in real CI.
- **You find out:** **unsurfaced** for those three. The files look
  finished.
- **Source:** M8, `future_additions.md`; narrowed at V2.M6.

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

### C-27 — Python third-party semantics need a discoverable venv
- **Cannot tell you:** where a call into a third-party package goes, when
  the repo's environment is not a venv Hobbes can find — a conda env,
  system-installed packages, or a venv living somewhere unconventional.
- **Because:** two mechanisms both need the environment, and both were
  quietly broken until the C-16 fix exposed it (2026-08-15). *Resolution*:
  Pyright needs `venvPath`, which was hardcoded to `<root>/.venv` — this
  repo's venv is `pipeline/.venv`, so it resolved nothing; now discovered
  (`find_venv`: `.venv`/`venv` at the root, then beside each manifest,
  `pyvenv.cfg` required). *Attribution*: scip-python maps resolved files
  to packages by asking the first `pip3` on PATH which environment is
  installed — the **system** one, and a uv venv has no pip at all — so
  every third-party reference was attributed to the local project and the
  dependency vanished; now Hobbes pre-computes the listing with the
  venv's own interpreter (stdlib `importlib.metadata`) and hands it over
  via `--environment`. Names are matched PEP-503-style (`pyyaml` ==
  `PyYAML`), Python only.
- **Bites at:** third-party `uses`/`calls` edges on any Python repo whose
  environment the discovery conventions miss. On this repo the fix took
  resolution from **0 of 5 declared packages to 5 of 5**.
- **You find out:** **surfaced** — `dependency_coverage` counts plus the
  ingest WARNING below the threshold, the same mechanism as C-23. The
  degradation had existed since lane B landed and was invisible until
  C-16's manifest walk gave the check its denominator; three days of
  "semantic" Python graphs carried no third-party edges and nothing said
  so.
- **Honest residue:** discovery is convention-bound. An environment
  without `pyvenv.cfg` under `.venv`/`venv` at the root or beside a
  manifest is not searched for, and the coverage counts are the answer
  there, not a fix.
- **Provider (P9):** inherited from `@sourcegraph/scip-python` **0.6.6**
  — its environment discovery (PATH's pip) is the part Hobbes routes
  around, and `--environment` is the indexer's own escape hatch, marked
  experimental. Re-check on any version bump: an upgrade that fixes its
  discovery could retire our listing; one that drops the flag would
  break it loudly (the helper passes it only when computed).
- **Source:** found 2026-08-15 by C-16's first real run; fixed and
  registered the same day. The Python sibling of C-23.

## Extraction — Go

### C-26 — A Go file outside any module gets no semantics
- **Cannot tell you:** where a call goes, for a `.go` file that sits under
  no `go.mod` — a scratch file, a snippet directory, a partially-migrated
  tree.
- **Because:** a Go module is the unit the loader resolves against, so lane
  B runs once per `go.mod` and files under none are skipped rather than
  guessed at. Inventing a `go.mod` for them would invent their dependency
  versions too, and the index would resolve against a module that does not
  exist.
- **Bites at:** those files' call edges, which fall to lane A's fallback —
  correct within their own directory, and blind to anything imported.
- **You find out:** **surfaced** (2026-08-15, the pre-M6 register sweep) —
  one `extraction_errors` record per orphan directory names the files, the
  missing `go.mod`, and the tier their edges fall to. Before that it was
  *partial*: the `syntactic` tier said the answer was lane A's, but nothing
  said why this file in particular got no semantics. The constraint itself
  stands — the files still have no semantics, and inventing a `go.mod`
  would still invent their dependencies — what changed is that the skip is
  visible where a user meets it.
- **Source:** ADR-037, V2.M5; surfaced 2026-08-15.

## Extraction — Rust

### C-28 — A symbol defined in two files is unattributed, not guessed
- **Cannot tell you:** which file a reference lands in, when the symbol's
  moniker is emitted as a definition by more than one file. Rust: every
  cargo target of a package gets the same `crate/`, `main().`, `tests/`
  monikers. Go: a package's namespace is declared in **every one of its
  files** (`package proxy` in each). References to such symbols produce
  no edge at all.
- **Because:** the decode's definitions map can hold one file per
  moniker, and first-wins fabricates edges: `decode()` therefore drops
  any moniker defined in more than one document and lets its references
  fall to `external_refs`, unattributed rather than guessed. *(This
  entry was first written for cargo targets only — the ADR-037 lesson
  that a register entry can be wrong by being too specific, caught the
  same day this time: the V2.M7 verification re-ingested the dogfood
  repo and the drop removed two Go module edges that had been **false
  since V2.M5** — `hobbes-proxy/main → internal/proxy/knowledge` and
  `hobbes-web/main → internal/web/artifacts`, both semantic-tier
  attributions of a duplicated package namespace to an arbitrary
  same-named file in the wrong package. Zero symbol edges changed for
  any language; the real member-level edges all survive.)*
- **Bites at:** module edges whose only evidence is a reference to a
  duplicated symbol — a bare `use mylib;` with no call behind it, a Go
  package qualifier. The function and type monikers that carry the call
  graph are unique, so edges are still raised wherever a real call
  resolves.
- **You find out:** **surfaced** — the `scip-decode` degradation record
  counts the dropped symbols and names a sample, landing in
  `extraction_errors` and the ingest WARNING like every other decode
  degradation.
- **Provider (P9):** inherited from `rust-analyzer` **1.97.1** and
  `scip-go` **0.2.7** alike. An upstream release that scoped these
  monikers per target/file would make the drop a no-op.
- **Source:** ADR-040, V2.M7 spike; generalised by the V2.M7
  verification (2026-08-15).

### C-29 — Ingesting a Rust repo executes that repo's code
- **Cannot tell you:** nothing — this entry registers something Hobbes
  *does*, not something it misses: `hobbes ingest` on a Rust repo runs
  that repo's `build.rs` and proc macros **on this machine**, because
  rust-analyzer's loader compiles and executes them to expand the code it
  indexes. No other lane B provider executes repo-authored code.
- **Because:** running the indexer as its ecosystem ships it is the §3.2
  trade, and rust-analyzer without build scripts and proc-macro expansion
  cannot resolve the derive- and macro-generated code that real Rust is
  made of. All writes stay in the staging tree and the user-global cargo
  registry (verified on the spike); the execution itself is the fact.
- **Bites at:** security posture. Ingesting an untrusted Rust repo is
  running it — the same trust decision as opening it in any
  rust-analyzer-backed editor, but Hobbes makes it during a command whose
  name says "read".
- **You find out:** **surfaced** — a `NOTE:` line on stderr every time
  the rust lane runs, not only the first: the posture fact does not wear
  off. (`extract_scip_rust`, printed before the indexer starts.)
- **Provider (P9):** inherited from `rust-analyzer` **1.97.1**. Upstream
  knobs exist to disable build scripts and proc macros, at the price of
  gutting resolution for macro-heavy code; a future release that
  sandboxes expansion would soften this entry without Hobbes changing.
- **Source:** ADR-040, finding 6.

### C-30 — Rust third-party semantics need a fetchable crate registry
- **Cannot tell you:** where a call into a third-party crate goes, when
  the crate's sources are not already in `~/.cargo/registry` and the box
  cannot fetch them — the first ingest of a dependency-heavy repo
  downloads its tree (51 MB for the spike repo's single dev-dependency).
- **Because:** cargo resolves and fetches dependency sources at index
  time. The registry is user-global, which is why Rust needs none of
  ADR-032's symlink machinery — and why an offline box or a cold cache
  degrades resolution instead of erroring.
- **Bites at:** third-party `uses`/`calls` edges, and ingest latency on
  first contact with a new dependency set. In-repo edges survive: they
  resolve from the staged sources alone.
- **You find out:** **surfaced** — `dependency_coverage` counts plus the
  ingest WARNING below the resolve floor, the same mechanism as C-23 and
  C-27, now covering its fourth language.
- **Provider (P9):** inherited from `rust-analyzer` **1.97.1** and the
  cargo toolchain it drives.
- **Source:** ADR-040, finding 6. The Rust sibling of C-23/C-27.

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

Five of twenty-seven entries are **unsurfaced** (C-4, C-12, C-14, C-19 —
narrowed to three tools at V2.M6 — and C-20). Five have been **lifted** —
C-11 at V2.M3, C-3 and C-16 in the 2026-08-15 pre-M6 sweep (which also
surfaced C-5 and C-26), C-18 at V2.M6, and C-24 the same day: Max
approved JSX instantiations as call sites with the standing condition
that "in every meaningful sense" keeps its outliers named, which the
lifted entry does. That churn is the point of keeping the register: none
of it was knowable before this file existed, and what remains is the
backlog P8 generates.

C-27 arrived the way the register says entries should: C-16's first
working run produced a number (0 of 5 resolved), the number was
investigated rather than explained away, and the investigation found
*two* stacked causes — a hardcoded venv path and an indexer asking the
wrong environment entirely. Both fixed same-day, and the entry records
what remains: discovery is convention-bound, and `dependency_coverage`
is the answer for environments the conventions miss.

V2.M4 added one entry (**C-25**) and it is *partial* rather than
unsurfaced, because `graph.json`'s `packs` list was added in the same
commit as the pack layer. Attributing a layer to the pass that produced it
was the cheap half of the answer; suppressing it is the half that is
deferred.

V2.M5 added **C-26** (also partial) and **widened C-6**, which is the more
interesting event: measuring a second indexer showed the original entry was
filed too narrowly. C-6 was written as "scip-python does not populate
`syntax_kind`" and read as a gap one upgrade could close; `scip-go` omits
it too, so the entry now says no indexer populates it and an upgrade of one
lifts nothing. **A register entry can be wrong by being too specific**, and
nothing catches that except measuring the next case.

The 2026-08-15 audit (before V2.M6) found the complementary failure: **a
register entry can be made wrong by a milestone that never touched it.**
Six entries had drifted, all by M4/M5 side-effects — C-3 materially (Go
emitted stdlib `ext:` nodes where Python and TS dropped them, an asymmetry
no ADR registered), C-15's merge order predated both the pack layer and
Go, and C-5/C-9/C-10/C-14 named mechanisms or providers that had since
moved or multiplied. Nothing detects this today: the register is prose,
and no milestone exit re-reads entries it did not write.

The same day's sweep then paid down the worst of what the audit ranked:
C-3 was lifted outright (ADR-038 — stdlib everywhere, rather than
re-hiding what Go already showed), C-16 was lifted (the manifest walk),
and C-5 and C-26 went from silent to one degradation record per declined
route and per orphan Go directory. C-5's surfacing also caught the Nest
reader *emitting* a computed route with the segment dropped — the one
shape worse than absence, found only because surfacing forced the decline
path to be written down.

Ranked by how badly each remaining entry misleads, worst first:

1. **C-12** — a monorepo's cross-zone import edge is simply absent, at
   exactly the altitude the graph exists to show.
2. **C-14** — an empty CLI list reads as "no CLI" on TS/JS and Go repos.

The rest stay quiet rather than lying, which is a real difference.

**Nothing left in the register inflates a number.** C-11 was the only
entry that made a claim larger than the truth, and V2.M3 lifted it; C-24,
its deliberately-under-reporting residue, was lifted in turn once the
under-report could be replaced with the true edge rather than the safer
inaccuracy. Every remaining limit under-reports or stays silent — so a
Hobbes number can now be read as a floor, which is a property worth
defending in later milestones.

**Track record so far:** three of the four entries touched at V2.M3 were
*already true and already invisible* before the register existed — C-23 in
particular had a check written specifically to catch it that could not fire
under any circumstances, and C-11 had been honestly documented at M6 and
went on misleading for two milestones. That is the argument for P8 restated
as evidence: being written down in an ADR at the moment of decision did not
stop either of them.
