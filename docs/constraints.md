# Hobbes constraints — the register of what Hobbes cannot tell you

**Status: load-bearing.** This is not a caveats page. Principle **P8**
(`hobbes-architecture.md` §1) makes an entry here part of the definition of
done for any decision that concedes information, and **P9** extends that to
information conceded *for* us by a language provider we run — those entries
carry a `Provider` line naming the provider and pinned version, because
unlike our own concessions they can end on an upstream release (ADR-034).

This register is written for **anyone who runs Hobbes**, not for the people
who built it. Named individuals appear only as the source of a decision —
historical attribution, the same role an ADR number plays.

Its audience includes **agents** (ADR-047): what Hobbes cannot see is
itself context — it is how a single-use agent points at the work it must
do by hand — so the register's content reaches sessions through
`list_blind_spots` on the proxy, and the derivation contract
(architecture, "Where this is going") makes the stated complement a
mandatory half of any future derived context.

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

## How the register is organised

Two parts, and the split is load-bearing (ADR-043):

- **Active constraints** — limits that hold today. Grouped by the subsystem
  where a user meets them.
- **Lifted constraints** — limits that no longer hold, kept with **full
  documentation of how they were lifted**. A lift is a technique, and a
  technique has a boundary: an input the technique does not classify falls
  back to being conceded — *silently*, unless the boundary is written down.
  So a lifted entry is not archived trivia; it records the exact mechanism
  of the lift and the residual edge cases that mechanism leaves outside.
  Residue that turns out to matter becomes a new active entry — C-11 →
  C-24 is the worked example, and it happened twice: C-24's own lift left
  residue in turn.

Entries are numbered `C-n`, sequential and stable, and are **never
renumbered or deleted**. When a constraint is lifted, its entry moves to
the Lifted part keeping its number, because "we used to concede this, and
here is precisely how we stopped" is itself information — the next
constraint usually hides in a lift's edge cases.

## How to read an active entry

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

## How to read a lifted entry

| field | means |
|---|---|
| **Was** | the limit as it stood, and why it was conceded then |
| **Lifted by — the technique** | the exact mechanism of the lift — what now classifies the cases the constraint used to concede |
| **Residual edge cases** | inputs the technique does not classify, stated as the technique's boundary — where the old concession quietly survives |
| **Source** | the ADR or session for the concession *and* for the lift |

This file is not `docs/future_additions.md`. That one parks deferred
*work*. This one registers conceded *information*. A deferral that loses
information appears in both, and the entries cross-reference.

---

# Active constraints

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
  file: sites, resolved, external, unresolved — and since ADR-045 each
  row's `tail` object classifies the unresolved remainder by
  observation, so the composition this entry asserted from one
  measurement is measured on every ingest instead of remembered. The
  ingest summary prints the per-language rollup: *seen, not modelled by
  design* (builtin-named calls, below-floor local bindings) versus
  *cannot resolve* — always as a share **of detected sites**, never "of
  the repo". On this repo's 2026-08-16 measurement the fixture claim
  held: 45.5% of the Python tail is builtin-named, 44.4% attribute
  calls on untypable receivers. One ledger subtlety the tail makes
  visible: a site lane A's *fallback* resolved still counts as
  unresolved here (the count is the semantic ledger) and carries class
  `fallback-resolved` — it has an edge, at syntactic tier. Since
  ADR-047 the same decomposition reaches **agents** where they work:
  `list_blind_spots` on the session proxy serves the scoped rollup with
  each class naming its register entry, so an in-sandbox agent can
  point at the verification work that is its own.
- **Note:** deliberately counts, never a confidence score. An edge with no
  named target cannot be drawn, checked, or cited — it is C-1's false edge
  wearing a probability. The tail classes keep that rule: each is an
  observation about the site, never a probability about the edge
  (ADR-045; their boundaries are C-32).
- **Source:** ADR-029; tail classification added by ADR-045.

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
  8,575 occurrences; `scip-go` for **0 of 18,682** (V2.M5, ADR-037);
  `rust-analyzer` for **0 of 169** (V2.M7, ADR-040). Three independent
  implementations, the same omission — and the field is optional in SCIP,
  so this is the state of the ecosystem rather than one tool's gap.
  Registered first as a `scip-python` limitation, **generalised at
  V2.M5** when measuring a second indexer showed the original framing was
  too narrow, and confirmed by the third.
- **Bites at:** it would have made `who_calls` silently become
  `who_references`. This is the whole reason the lanes join on ranges
  before a graph exists rather than merging finished edges.
- **You find out:** **surfaced** — resolutions that no call site claimed
  are typed `uses`, not `calls`, so the two questions stay separable in
  the artifact.
- **Provider (P9):** inherited from **every** indexer measured —
  `@sourcegraph/scip-python` 0.6.6, `scip-go` 0.2.7, and `rust-analyzer`
  1.97.1. **Not liftable by
  upgrading one of them**, which is what changed at V2.M5: it would have to
  be fixed by all of them, and a language whose indexer still omitted it
  would silently lose its call graph. This is why the add-a-language
  checklist requires a syntax provider (§3.7) rather than suggesting one.
  Re-check per indexer on any version bump; a single fix lifts nothing on
  its own.
- **Source:** ADR-029 (registered), ADR-037 (generalised), ADR-040
  (third confirmation); owned as ours under P9 (ADR-034).

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
  rust-analyzer is the one exception that changes nothing: it has no
  version flag and needs none, because its moniker version is the crate's
  `Cargo.toml` version — constant per commit by itself (ADR-040).
- **Bites at:** a future multi-repo graph merge, which must key on package
  identity alone. Nothing today.
- **You find out:** **n/a — no user-visible effect yet.** Registered
  because it is a paid cost with a deferred bill.
- **Source:** ADR-027, Decision 1.

### C-32 — The tail view's classes are observations with boundaries
- **Cannot tell you:** *why* a call is unresolved beyond what its class
  observes — and three boundaries shape what the classes can say.
  **Origin classes carry two proof grades** (narrowed by ADR-046, which
  applied this entry's candidate fix): for TS/JS, `local-binding` /
  `nested-decl` / `external-origin` are **declaration-proven** — the
  checker resolved where the callee lives. For Python and Go,
  `local-binding` is **binding-proven with scope containment** — lane
  A recorded the binding (a parameter, a `:=` or assignment target, a
  nested def) with its enclosing function's extent, and the site
  matches only when that extent spans the call's line; `nested-decl`
  and `external-origin` do not exist for them, and Python's
  `import-binding` (ADR-045 amendment) is binding-proven the same way,
  minus the scope check — an import binds at module level. **Rust has
  no origin classes at all**: both verified Rust tails are empty, so a
  collector could not be verified against anything real, and wiring one
  on zero evidence would be the P11 mistake at class scale. **Builtin lists are
  pinned literals**, not the running interpreter's — a builtin the
  language adds later classifies `unclassified` until the pin moves.
  **Shape is read from the terminal's source line, plus one line up
  for a wrapped chain** (widened by ADR-048): in Go, Rust, and TS/JS a
  statement cannot end with `.`, so when a call opens its line and the
  previous line ends mid-chain (`.` or `::`, after cutting any trailing
  `//` comment) the site reads `attr-call`/`path-call` — dagger's
  gofmt-mandated fluent chains were thousands of real attr-calls
  reading `unclassified` before this. Python is excluded (its chains
  wrap with a leading dot, already read same-line; a trailing dot
  inside parentheses abstains). What still abstains: a terminal the
  recorded line does not contain, and a previous line whose chain
  ending hides behind a string literal containing `//` — both decline
  to `unclassified` rather than guess, the C-5 rule applied to
  classification.
- **Because:** a class must be an observation or abstain (ADR-045's
  standing rule) — inferring what a site "probably is" from a checklist
  of potentials is the fake-honest shape P8 exists to prevent. The
  boundaries are the price of that rule, and the measured tails say the
  asymmetry costs little today (Python's declared-in-file share was
  6.8% where TS's was 61–73%).
- **Bites at:** cross-language comparison of tail compositions — a TS
  tail reads richer than a Python one partly because TS is the only
  lane whose checker reports origins.
- **You find out:** **surfaced** (2026-08-21, ADR-053 — this entry's
  candidate fix applied). `graph.json` carries
  `tail_classes_available`, per tail-view language, the classes its
  providers *could* have reported (a pinned table beside the classifier,
  held against its decision tree by the test suite); the ingest capture
  line prints `classes this lane cannot report: …` under each language,
  and `list_blind_spots` prints the same line to agents. Abstention
  stays visible as `unclassified` counts. What remains conceded is the
  asymmetry itself — Python/Go/Rust tails are still poorer than TS's
  because their providers report fewer observations; the fix makes the
  boundary legible, it does not move it. Origin support from the other
  syntax providers would narrow it further.
- **Source:** ADR-045; surfacing ADR-053.

## Extraction — TypeScript and JavaScript

### C-12 — Imports across tsconfig zones do not resolve — *narrowed and surfaced 2026-08-16*
- **Cannot tell you:** that package A imports package B through a **path
  alias defined in B's zone** (or any custom resolver) — the alias map is
  another program's compiler config, which this walk does not interpret.
  The common monorepo forms resolve since ADR-041: a **relative**
  specifier resolves against the repo's own file set (zones
  notwithstanding — a path is not a compiler configuration), and a bare
  specifier matching one of the repo's **own package names** resolves to
  that package's entry or subpath, read from `package.json` like every
  other manifest fact. Both arms are lane A's alone, so cross-zone edges
  carry `syntactic` tier — the honest description of their evidence,
  since each zone's indexer still cannot see out.
- **Because:** each zone is a separate ts-morph Project (and a separate
  indexer run), and cross-program resolution through another zone's
  compiler options is still not attempted — only the two
  configuration-free forms are.
- **Bites at:** monorepo module edges behind aliases or custom
  resolvers; previously *all* cross-zone edges, ranked #1 in this
  register ("missing exactly where the architecture is most
  interesting").
- **You find out:** **surfaced** — a specifier that resolves nowhere and
  names no plausible package becomes one `imports-unresolved` record per
  file, specifiers named, in `extraction_errors` and the ingest WARNING.
  Asset imports (`./index.css`) are excluded from the records: a file
  the graph deliberately does not model is not a resolution failure, and
  the first run of the floor proved they would bury the real records.
- **Source:** M6, `future_additions.md` → per-package tsconfigs;
  narrowed and surfaced by ADR-041 (2026-08-16).

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

## Extraction — cross-layer

### C-15 — A node-id collision across languages drops a file from the graph
- **Cannot tell you:** anything about the losing file — a repo-root
  `widget.py` and `widget.ts` both want the id `widget`, and merge order
  decides: Python is the base graph, then TS, then Go (V2.M5), then Rust
  (V2.M7), then the pack layer's nodes, `tf:` among them, last (V2.M4).
- **Because:** ids are path-derived per layer and are not namespaced on
  collision. Fixing it properly means rewriting ids across a whole layer's
  nodes, edges, symbols, tests and routes.
- **Bites at:** the graph's completeness, by an accident of pipeline order.
- **You find out:** **surfaced** — one `extraction_errors` record per
  collision, naming both paths and the fix, plus an ingest WARNING. It was
  data loss decided by ordering *in silence* before M8 review.
- **Source:** M8 review, `future_additions.md` → cross-language namespacing.

## Extraction — lane B environments and staging

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

### C-23 — TypeScript semantics need an installed dependency tree — *narrowed 2026-08-18*
- **Cannot tell you:** where a call goes when its receiver's type comes
  from a package that is not installed **and cannot be provisioned**.
  Measured on kbet with no `node_modules`: **19% of internal references
  and 73% of external references disappear**, and 20 of 23 packages
  resolve to nothing.
- **Because:** the indexer's resolution is whole-program type inference,
  and an absent dependency has no types to infer from. It exits 0 and
  produces a plausible index regardless.
- **Narrowed by ADR-050:** when the repo carries a lockfile Hobbes can
  honor (`package-lock.json` → `npm ci`; v1 `yarn.lock` → pinned
  classic yarn), the tree is **provisioned into `~/.hobbes/cache`** —
  `--ignore-scripts`, never touching the repo — and symlinked into the
  stage. What remains of this entry: pnpm, Yarn Berry, and
  lockfile-less repos (each declined by name in a per-zone degradation
  record), plus the offline case, which is C-34's subject.
- **Bites at:** TS repos on pnpm/Berry or without a lockfile, ingested
  without `npm install` having been run — and partially-installed
  environments everywhere.
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

### C-34 — Dependency provisioning needs a fetchable npm registry and a supported lockfile
- **Cannot tell you:** anything better than C-23's degraded answer when
  the provisioning path (ADR-050) cannot run: no network to the npm
  registry, no `npm` on the box, a pnpm or Yarn Berry lockfile, or no
  lockfile at all.
- **Because:** the install is **lockfile-pinned or declined** — an
  unpinned `npm install` is the registry's answer of the day, and an
  artifact that changes between runs of the same commit breaks P1.
  Berry is declined because PnP does not produce the `node_modules`
  shape the indexer resolves against; pnpm because no pinned installer
  for it is wired. `--ignore-scripts` is unconditional, so a package
  whose type declarations are *generated by its postinstall* stays
  typeless — that residue is accepted, not excepted, because a
  lifecycle script is arbitrary code and no analyzer here requires
  execution (the C-29 contrast).
- **Bites at:** offline ingests of uninstalled TS repos, and the
  pnpm/Berry half of the ecosystem. The npm sibling of C-30 (crates)
  and cousin of C-27 (venvs): every language's third-party semantics
  need an environment from somewhere.
- **You find out:** **surfaced** — every zone that is declined or fails
  gets a degradation record naming the reason (`no lockfile`,
  `Berry (v2+)`, the installer's own error tail), and
  `dependency_coverage` still counts what resolved.
- **Source:** ADR-050 (2026-08-18).

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

### C-19 — Two of the four compiled CI configs have never been executed
- **Cannot tell you:** that a generated dependency-cruiser config or
  Rego policy actually runs. **import-linter left this list at V2.M6**
  (ADR-039): the agreement suite runs `lint-imports` over generated
  configs on every test run, and the first real execution found a real
  emitter bug — unmatched ignore pairs failed a clean repo. **semgrep
  left it 2026-08-16**: a dev dependency now, with the same treatment —
  a violating tree fails, a clean one passes, path exclusions actually
  exclude, and the dogfood repo's own I-5 rule runs against the real
  `narrate/` package on every test run (so a new write path in
  `narrate/` fails the suite before it fails a reviewer). The semgrep
  emitter survived its first execution clean, which is worth recording
  precisely because import-linter's did not: the argument for executing
  the remaining two stands on the one bug found, not on bugs being
  everywhere.
- **Because:** compilation is pure text generation by design (no target
  toolchain needed), and dependency-cruiser and conftest are not
  installed here. Those two emitters are asserted against documented
  formats only.
- **Bites at:** `hobbes invariants compile` output for dep-cruiser and
  rego, the first time anyone runs them in real CI.
- **You find out:** **unsurfaced** for those two. The files look
  finished.
- **Source:** M8, `future_additions.md`; narrowed at V2.M6 and again
  2026-08-16.

### C-20 — Decisions do not survive a fresh clone
- **Cannot tell you:** on a new machine or a re-clone, that you already
  approved an invariant or confirmed a policy. The whole queue asks again.
- **Because:** ADR-012 gitignores all of `.hobbes/` in target repos, so
  the ledger, invariants and policies are per-clone, per-machine.
- **Bites at:** `hobbes up`'s "set once, holds until you change it"
  promise, which holds within a workspace and silently does not across
  them.
- **You find out:** **unsurfaced.** Re-asking looks like a first run.
- **Source:** ADR-026, confirmed as a known limitation at review.

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
- **You find out:** **surfaced** (2026-08-16, ADR-042) — the fix the
  entry named, built where it named it: each pending proposal arrives
  with its nearest confirmed record when the statement overlap crosses a
  deterministic threshold (word-set Jaccard, no model), rendered as a
  "possible restatement of I-n" banner carrying the confirmed prose and
  the instruction to read it before approving. The I-9/I-3 pair — the
  observed failure — is the pinned test case: the reworded proposal
  names I-3 beside itself, an unrelated proposal names nothing, and a
  retired record is history, not a neighbour. The *constraint* stands:
  narration still does not know about `.hobbes/invariants/` and still
  re-proposes; what changed is that the reviewer now decides while
  looking at the record being reworded.
- **Honest residue:** the neighbour is lexical. A restatement sharing no
  vocabulary with its original scores below the threshold and arrives
  bare — the mechanism catches rewords, not paraphrases, and says so
  here rather than pretending otherwise.
- **Source:** ADR-026, `future_additions.md`. Instance recorded
  2026-08-15; surfaced by ADR-042 (2026-08-16).

## Derivation — the plan mapping (D1)

### C-35 — Partition quality is unvalidated
- **Cannot tell you:** that a change-spec's partition is a *good* one —
  that its units minimize rework, that its contracts hold through
  implementation, or that its budget and thresholds fit any repo but
  the ones it was sketched against. Every number the mapping runs on
  (tier and edge-type weights, the 0.55 per-hop decay, the 0.2
  threshold, the 60k budget, the 200-commit window, the 300-token
  contract overhead, the human-first threshold) is a declared guess
  from ADR-051's pinned table.
- **Because:** the design (agent-mapping §6) defines partition quality
  as a *measured* number — rework, contract failures, context-fault
  rate, tokens, wall time from the flight recorder — and nothing
  records those yet: the execution milestone that spawns per-unit
  sessions is not built. Claiming quality before measuring it would be
  the P11 mistake at mapping scale. One parameter already earned its
  place the hard way: the per-hop decay exists because the dogfood
  exit check measured its absence (one seed → 33 units, the whole
  connected component).
- **Bites at:** every `hobbes plan` run — the partition may split what
  should stay together or bundle what should split, and the spec
  cannot warn you beyond its flags (`oversize`,
  `coordination-heavy`, `human-first`).
- **You find out:** **surfaced** — every plan run prints the C-35
  statement and every change-spec carries it in its `validation`
  field; the flags name the shapes the mapping itself distrusts.
- **Source:** ADR-051 (2026-08-19); the lift path is the parked
  recorder milestone (`future_additions.md`).

### C-36 — Seed resolution is lexical, not understood
- **Cannot tell you:** what a proposal *means*. Seeds resolve by exact
  (case-insensitive) match of proposal terms against node ids, path
  stems, and symbol names — plus explicit `--seed` values. A proposal
  whose intent is clear to a human but whose words match no identifier
  seeds nothing; a prose word that happens to equal a symbol name
  seeds spuriously (stopword-guarded, not solved).
- **Because:** the mapping is deterministic and quota-free by design
  (P5): a generative planner interpreting prose would make the impact
  set a model opinion, unreproducible between runs. The honest
  deterministic reading is exact match plus a refusal to guess —
  unmatched code-shaped terms are reported, never inferred into the
  graph's nearest neighbor.
- **Bites at:** plans phrased in domain language rather than code
  names ("the checkout flow" seeds nothing unless a node is named
  that), and renamed concepts whose old name still matches something.
  *Measured on real issues (ADR-055, eight `psf/requests` SWE-bench
  instances, quota-free): all eight seeded, four seed sets touched a
  gold-patch file. The misses have three shapes — dotted
  `package.function` names (`requests.get`) match no symbol *name*;
  trailing punctuation makes prose look code-shaped (`fine:`,
  `it.`); generic words (`data`, `json`, `session`) seed spuriously.
  Candidate adjustments are in `future_additions.md`; not applied
  before verdicts exist.*
- **You find out:** **surfaced** — `hobbes plan` errors with the
  `--seed` hint when nothing resolves (exit 2), and every change-spec
  lists `unresolved_terms` with the C-36 note; resolved seeds show
  which term hit them, so a spurious seed is visible in the spec.
- **Source:** ADR-051 (2026-08-19).

### C-37 — A pinned contract is a declaration site, not a signature
- **Cannot tell you:** a cross-unit interface's parameter types,
  return type, or semantic contract. A contract pins the target's
  identity, kind, file and line range, tier, owner, and in-scope
  invariants — the graph carries no richer signature to pin
  (symbols are id/kind/range; SCIP descriptor filtering is C-9).
- **Because:** inventing a signature from source text would be a
  second parser outside the owning lane (I-4's rule) and a guess at
  exactly the moment agents need a fact — two implementers building
  against a paraphrased interface is the rework the contract exists
  to prevent. A pin that says "the function at this site, as it is"
  is smaller and true.
- **Bites at:** contract renegotiation — an agent cannot tell from
  the spec alone whether its counterpart changed a signature, only
  that the declaration site moved; the far side must be read at its
  cited lines (which the pin makes one hop away).
- **You find out:** **surfaced** — every contract entry in every
  change-spec carries `pin: declaration-site, not a type signature
  (C-37)` inline.
- **Source:** ADR-051 (2026-08-19).

### C-38 — A derived write scope is measured, not mounted
- **Cannot tell you:** that an agent *could not* have written outside
  its unit. The change-spec's policy manifest names write mounts over
  the interior and its guarding tests; the sandbox mounts the worktree
  **whole** (rw for an implementer), and the agent policy layer is
  command-pattern, which cannot express "these paths only". What the
  base does instead is observe: the orchestrator diffs the harvested
  branch against the manifest and records every file outside it as
  **rework** — §6's first loss term. Two neighbours of the same shape:
  contract **renegotiation has no approval flow** (a reflection lands
  in the orchestrator's inbox for a human; nothing re-pins both sides),
  and **tokens and wall time are unmetered** (the loss lists them as
  unobserved rather than filling them in). *(Metering amended
  2026-08-21, ADR-055: the session's default command now requests
  Claude Code's JSON result envelope and `hobbes bench` reads it per
  unit — a session that emits none is still recorded unobserved,
  never imputed.)*
- **Because:** path-grain write enforcement is mount work inside the
  session image — a per-unit overlay, or bind-mounting interior paths
  rw over a ro worktree — and the base was built to run under the
  benchmark harness first and be corrected from its errors (ADR-052,
  ADR-054). Measuring rework costs nothing and is the signal the loss
  needs; enforcing it before a run has shown where agents actually
  stray would be tuning a guess.
- **Bites at:** the policy manifest's `write_mounts` list, read as a
  guarantee; the partition record's `rework_files`, which is the
  honest form — "wrote outside", not "could not".
- **You find out:** **surfaced** — every `context.md` and brief states
  "write scope is advisory at path grain (C-38)" under its derived
  policy; `partition-record.json` carries `c38` and the per-unit
  `rework_files`; the loss lists its unobserved terms by name.
- **Source:** ADR-054 (2026-08-21).

## Verification — the benchmark harness (ADR-055)

### C-39 — Contamination is bounded, never proven
- **Cannot tell you:** whether a pure-model solve on a benchmark
  instance came from reasoning or from memory. Known benchmarks are in
  training corpora; a memorised answer needs no context, which biases
  the comparison *against* the harness, not for it. The instance
  protocol bounds the set by `created_at` against a stated cutoff and
  counts what it dropped; it cannot see inside a model's training
  data, and a post-cutoff instance can still resemble a pre-cutoff one.
- **Because:** the only honest tool is selection, and selection is a
  date. SWE-bench Verified's newest instance is 2023-08-07 — a 2025
  cutoff selects zero of 500 — so a live run on a contemporary model
  needs a continuously refreshed set (SWE-rebench, SWE-bench-Live) and
  still only *bounds* the question.
- **Bites at:** every H1–H3 rate; a pure arm that looks strong on an
  old set may be remembering, and a harness that looks weak beside it
  is being compared to recall.
- **You find out:** **surfaced** — `hobbes bench select` and `run`
  print the cutoff line first ("bounded, not proven — C-39", or "every
  instance may be in a model's training data" when none is set);
  `run.json` records the cutoff, the created range, and the drops; the
  report's notes restate it.
- **Source:** ADR-055 (2026-08-21).

### C-40 — The verdict is the evaluator's
- **Cannot tell you:** that a `resolved` verdict means the patch is
  right, or an `unresolved` one that it is wrong, beyond what the
  benchmark's own tests decide in the benchmark's own environment.
  The harness runs the pinned `swebench` evaluator as a subprocess and
  reads its report; per-repo test commands, environments, log parsers,
  and image builds are the evaluator's, and so are their failures
  (an `error` verdict is an environment that did not come up, not a
  patch that was judged).
- **Because:** reimplementing per-repo test semantics would make the
  verdict Hobbes's opinion of the benchmark rather than the benchmark;
  P9's shape — a provider we run and do not wrap.
- **Provider:** `swebench` **5.0.2** (pinned in `bench/verdict.py`;
  `HOBBES_SWEBENCH_CMD` overrides the invocation, never the meaning).
- **Bites at:** `error` and `unjudged` counts in a report; a rate is
  over *judged* records only, and the unjudged count is printed beside
  it.
- **You find out:** **surfaced** — the report's notes name the
  evaluator and version; `run.json` records it; every verdict class is
  counted in the output, none folded into another.
- **Source:** ADR-055 (2026-08-21).

### C-41 — A live session has egress, and carries the model credential
- **Cannot tell you:** that a running session could not reach the
  network. The architecture's enforcement text says a forbidden route
  is *absent*, and for every session so far it was (`--network none`).
  A session driven by a model served off-box must reach that endpoint,
  so a live session runs with a network, and the endpoint's bearer
  token rides into it as `HOBBES_LLM_API_KEY` — the one secret a
  session carries. Nothing narrows the egress to the endpoint host yet.
- **Because:** the small-model ladder is served from the owner's
  compute (ADR-056), not from a binary in the image; the model is a
  network service by construction. The shell is still only reachable
  through the policy-checked `exec`, the mounts are unchanged, and the
  loop offers no `bash` when an MCP config is present — what changed is
  one reachable host, stated rather than hidden.
- **Bites at:** a session that exfiltrates through the model endpoint
  or anywhere else reachable on the session network; a leaked endpoint
  token (scope it per run — a Modal proxy token, revocable).
- **You find out:** **surfaced** — `hobbes-session --dry-run` prints
  the network mode and the runtime line (`runtime: … → <endpoint>`)
  with the token redacted; `hobbes bench run` prints `runtime openai @
  <endpoint>`; `run.json` records the endpoint. Narrowing egress to the
  endpoint host is in `future_additions.md`.
- **Source:** ADR-056 (2026-08-21).

### C-42 — A benchmark session runs under the solo floor, not the repo's intent
- **Cannot tell you:** that a benchmark session's permissions match what
  the repo owner would allow. A benchmark checkout is a committed-only
  clone, so the repo policy and the role policies (untracked under
  `.hobbes/`, ADR-012) never reach the session's worktree — only the
  derived agent policy and the shipped **solo box policy**
  (`bench/bench.box.policy`) apply. That box grants a lone implementer
  the tests-and-commit it needs with no human to approve; it is the
  *benchmark's* floor, not the target repo's intent.
- **Because:** benchmarks run Hobbes alone (no plan-review, no
  escalation approver — ADR-054's direction), and without this a
  needed `pytest`/`git commit` escalates and expire-denies after 30
  minutes of dead time, starving the arm under test (the ADR-057
  finding). The specific guarantees still win by deny-overrides
  (`*.tfstate*`, `git push*`, `git add *.hobbes/derived*`), and the OS
  sandbox is unchanged — the real boundary is the mounts and the
  network (C-41), not this file.
- **Bites at:** reading a benchmark session's allowed commands as if
  they were the repo owner's policy; they are not, and a real
  deployment of the execution path (not the benchmark) would load the
  repo and role policies instead.
- **You find out:** **surfaced** — `run.json` records the box and the
  escalation timeout; `hobbes-session --dry-run` prints the box path;
  the policy file is committed and commented with exactly this scope.
- **Source:** ADR-057 (2026-08-21).

### C-43 — The benchmark environment is bound, not rebuilt
- **Cannot tell you:** that a candidate patch which changes a compiled
  extension (a `.pyx`, a C source, a generated module) was tested
  against that change. Both arms run in the instance's own swebench
  image (ADR-058); the worktree at `/work` shadows the image's
  installed copy through `PYTHONPATH`, and the in-place build
  artifacts (`.so` files, generated version modules) are **copied**
  from the image's `/testbed` into the worktree before the session —
  never rebuilt. A pure-python change is tested exactly; a change that
  needs a rebuild runs the old extension under the new source.
- **Because:** rebuilding per unit session is minutes of compile per
  spawn (astropy, scikit-learn), and the evaluator (C-40) does its own
  install in the same image anyway — the verdict is unaffected, only
  the agent's in-session test signal is. Four of the 45 complex
  instances are compiled repos; the other 41 are pure python.
- **Bites at:** an agent editing a compiled module and trusting a green
  in-session test run; the evaluator then disagrees.
- **You find out:** **surfaced** — `hobbes bench run` prints the binding
  in its banner (`worktree bound by PYTHONPATH + copied build
  artifacts (ADR-058, C-43)`); every record's `detail.environment`
  names the image, digest, the `PYTHONPATH` binding and the
  pre-command; `hobbes-session --dry-run` prints all of them.
- **Source:** ADR-058 (2026-08-21).

### C-44 — A capped unit was merged for count, not coupling
- **Cannot tell you:** that the modules in a `capped` unit belong
  together. The benchmark unit cap (`--max-units`, default 20,
  ADR-058) merges the budgeted partition past its context budget —
  strongest coupling first, then the lightest units regardless of
  coupling — until the count fits. A unit the cap touched may carry
  an over-budget context or unrelated modules; the number of sessions
  was the decision, not the partition.
- **Because:** one instance's plan reached 210 units on a large repo
  under lexical seeds (C-35/C-36), at ~7.5 minutes a session; the cap
  bounds the run's cost while the partition's quality is still
  unvalidated. It does not improve the partition.
- **Bites at:** reading a capped plan's unit boundaries as derived
  structure; measuring H2 (per-unit context) on capped units without
  separating them.
- **You find out:** **surfaced** — every touched unit carries a
  `capped: … (C-44)` flag in the spec; `max_units` is recorded in the
  spec and `run.json`; the record's `detail.plan.capped` counts them;
  `hobbes plan` and the bench banner print the cap.
- **Source:** ADR-058 (2026-08-21).

## The system's own claims

### C-31 — "Supported" is a verified sample, not the language
- **Cannot tell you:** that ingesting *your* repo in a supported language
  will hold to the accuracy measured on the repos in architecture §3.8.
  The verification base is asymmetric by an order of magnitude: Python
  and TS/JS were proven across multiple repos of different shapes; **Go
  on exactly one repo — this one, a shape its own builders chose**;
  **Rust on one small repo**, 33 hand-checked call edges plus a fixture.
- **Because:** hand-verification is per-repo work, and a language's long
  tail — frameworks, macro styles, build layouts, dynamic idioms — is in
  no sample. The machinery being shared (P7: zero builder lines per
  language) is precisely what lets a thin sample *look* like broad
  coverage: the sixth language ingests as smoothly as the first,
  whatever the graph then misses.
- **Bites at:** the decision to trust a graph on the first repo of a
  shape Hobbes has never seen; every sentence of the form "Hobbes covers
  X".
- **You find out:** **surfaced** (2026-08-21, ADR-053 — the candidate
  surfacing applied). §3.8's table is pinned in
  `extract/verification.py` and stamped into `graph.json` as
  `verification_base`, keyed by the artifact's own language names; the
  test suite reads §3.8 and fails if the two tables drift. Three places
  state it where a language list is read as a capability list: the
  ingest summary prints `verification base: go 1 repo, python 3 repos,
  … — a sample, not the language` directly under the language list and
  spells out every single-repo or unverified row; the surface's
  language badges carry `· N repos` with the §3.8 row as tooltip and
  badge single-repo languages in the stale colour, not as peers; and
  `list_blind_spots` prints the rows before any percentage. A language
  the table does not know is stamped `not verified on any repo`, never
  omitted. **What stays conceded** — and is now the entry's whole
  content: the systematic blind spot a thin sample never exercised
  still degrades nothing at runtime. The surfacing tells you how thin
  the base is; it cannot tell you what the base missed.
- **Source:** ADR-044; the owner's directive, 2026-08-16 — a coverage
  claim beyond its evidence is dishonest even when the machinery behind
  it is proven. Surfacing: ADR-053.

---

# Lifted constraints

A lift is a technique, and the technique — not the celebration — is what
this part documents. Each entry keeps its number, states the limit as it
stood, the exact mechanism that lifted it, and the **residual edge cases**:
inputs the technique does not classify, where the old concession quietly
survives. When a residual case turns out to bite, it becomes a new active
entry and the two cross-reference (C-11 → C-24 is the worked chain).

### C-3 — Standard-library dependencies were invisible — *lifted by ADR-038*
- **Was:** stdlib imports were dropped as noise at resolution for Python
  (`sys.stdlib_module_names`, ADR-007) and JS/TS (Node builtins, M6), so
  "imports no stdlib" and "stdlib not modelled" looked identical — and the
  question is usually a security one, where `subprocess` is exactly the
  import a reviewer wants flagged. V2.M5 made it worse without touching
  it: Go's layer never had the filter, so `ext:os` on Go modules taught
  the reader stdlib *was* modelled and a Python module's silence read as
  positively clean. The asymmetry was found by the 2026-08-15 register
  audit, unregistered by ADR-037.
- **Lifted by — the technique:** ADR-038 (same day) — every syntax
  provider now emits `ext:` nodes for stdlib like any other dependency.
  Python simply drops the skip (no list is consulted; whatever does not
  resolve in-repo is external). TS keeps builtins **normalised** to a
  `node:`-prefixed name — `fs`, `node:fs` and `fs/promises` all become
  `ext:node:fs` — so a builtin never shares a node with an npm package
  that reuses its name. Go was already right, just alone. Externals stay
  hidden by default in the surface (ADR-023) — a view choice, where the
  old rule was an information choice.
- **Residual edge cases:** the TS normalisation's boundary is
  `builtinModules` from the **running Node's** `node:module` — the list
  is the ingest box's Node version, not a pin. A builtin added in a newer
  Node than the box's classifies as a third-party `ext:` package until
  the box upgrades; a builtin imported under the explicit `node:` prefix
  always normalises regardless. Two nodes for one dependency across two
  ingest boxes on different Node versions is the shape a user would see.
- **Source:** ADR-007 (the rule), ADR-038 (the lift), owner's call
  ("no need to hide what hobbes does capture" — Max, 2026-08-15).

### C-11 — JS/TS test reach was per *file*, not per test case — *lifted at V2.M3*
- **Was:** every case in a test file shared the file's whole
  imports-plus-calls closure, so `tests_guarding` and behavioural coverage
  **over-reported** for JS — the one place in the system where a limit
  inflated a number rather than shrinking it, and unsurfaced, because a JS
  row looked exactly like a precise pytest row.
- **Lifted by — the technique:** the tsextract helper records each test
  case's source extent (the `it()` callback's range) and the join carries
  ranges, so a call is attributed to the case that encloses it. Measured
  on kbet: reach went from a flat 7.3 symbols for every case in a file to
  per-case, with cases in the same file now differing.
- **Residual edge cases:** calls outside every case — a `beforeEach`, a
  `describe` body — are attributed to **all** cases in the file. That is
  the technique's deliberate boundary, not a leak: that code really does
  run for each case. And the technique attributes only *calls*; the
  under-report that remained for render-only component tests became its
  own entry, **C-24**, lifted in turn below.
- **Source:** ADR-021 (the limit), V2.M3 (the lift). Superseded by C-24,
  which was the honest residue.

### C-14 — CLI entry points came from `pyproject.toml` only — *lifted 2026-08-16*
- **Was:** `interfaces.json` read `[project.scripts]` and nothing else,
  so a JS package's `bin` entries and every Go binary were absent — this
  repo's own four binaries (`hobbes-policy`, `hobbes-proxy`,
  `hobbes-session`, `hobbes-web`) missing while two Python console
  scripts were listed, an inventory that read as complete and was not.
  The register ranked it #2 worst ("an empty CLI list reads as 'no
  CLI'").
- **Lifted by — the technique:** three packs on the ADR-035 registry, one
  per remaining language, each reading **declared build targets** from
  the ecosystem's own manifest convention. `cli-ts` reads `package.json`
  `bin` (string and map forms, every manifest, `node_modules` pruned);
  `cli-go` reads the lane's own facts — a file in `package main`
  declaring `func main`, named after its directory, the `go build` rule;
  `cli-rust` reads cargo's three binary shapes (`[[bin]]` tables,
  `src/main.rs`, `src/bin/*`). Each pack carries the per-pack
  removability test, and the lift's exit check is this entry's own
  counter-example, pinned in `test_packs.py`: the dogfood repo's four
  binaries must appear.
- **Residual edge cases:** the technique reads *declared* targets, so a
  binary that exists only in build automation — a Makefile target, an npm
  `scripts` alias, a `go build -o` with a renamed output — is still
  invisible. `setup.py` `entry_points` remains outside too, as the
  original entry said: the Python pack still reads `pyproject.toml`
  manifests only.
- **Source:** M6, `future_additions.md`; widened to Go at the 2026-08-15
  register audit; lifted 2026-08-16.

### C-16 — Dependency-degradation detection read only the repo root's manifest — *lifted 2026-08-15*
- **Was:** `declared_dependencies` looked only at `<repo>/pyproject.toml`,
  so a repo whose manifest lives in a subdirectory — this repo's own deps
  are in `pipeline/pyproject.toml` — ran ADR-027 Decision 4's check
  against an empty list. Worse than unsurfaced: the check *appeared* to
  run and reported nothing, on exactly the repo Hobbes dogfoods against.
- **Lifted by — the technique:** the pre-M6 register sweep — the function
  now unions every `pyproject.toml` in the repo via the same pruned walk
  the CLI pack uses (`iter_pyprojects`), with the subdirectory case
  pinned by a test written in this repo's own shape. The TS half was
  already per-zone (`declared_npm_dependencies` takes the zone's
  `package.json`) and needed nothing.
- **Residual edge cases:** the technique's boundary is the manifest
  format, not the manifest's location. A Python repo declaring
  dependencies exclusively via `setup.py` or `requirements.txt` still
  presents an empty declared list, and Decision 4's check is inert there
  exactly as it was for subdirectory manifests before the lift — with the
  same failure shape: a check that appears to run and reports nothing.
- **Source:** BUILDLOG 2026-08-14 (seventh), found via SELENEX; lifted
  2026-08-15.

### C-18 — Soft invariant verdicts judged the delta, not the source — *lifted at V2.M6*
- **Was:** soft verdicts ran through the tool-less ADR-020 runner, so a
  reviewer session judged from the architecture delta and a changed-file
  list, not the files — honest but shallow, and the M8 exit-check
  sessions said so unprompted.
- **Lifted by — the technique:** ADR-039 — `--soft` runs each in-scope
  soft invariant in the M4 reviewer sandbox: worktree mounted read-only
  at the review's head ref (`hobbes-session --ref`, added for this), the
  knowledge tools, and the range's diff hunks in the prompt. A missing
  sandbox is an **error recorded on the answer**, never a silent fallback
  to the delta prompt — that fallback would have quietly recreated this
  entry, which is why the technique forbids it by construction.
- **Residual edge cases:** the technique needs podman, the session image,
  and quota; where any is absent the verdict is an error, not a shallower
  judgment — the error path *is* the surfacing. And a source-based
  verdict is still an LLM's reading of real files: better evidence, not
  proof (C-17's distinction applies to it unchanged).
- **Source:** M8, `future_additions.md`; lifted at V2.M6 (ADR-039).

### C-24 — A test that only *rendered* a component did not reach it — *lifted 2026-08-15*
- **Was:** reach is the closure over **call** edges, and `<BetCard />` was
  a JSX element, not a call site — a `uses` edge reach deliberately did
  not follow, so a render-only test showed an empty `reaches` that read
  as "nothing guards this". The entry's asymmetry argument (under-report
  rather than over-report) held while the choice was between two
  inaccuracies; the fix removes the inaccuracy instead of picking a
  direction.
- **Lifted by — the technique:** the tsextract syntax provider records a
  JSX instantiation as a call site (owner-approved, 2026-08-15) — the
  component executes when the element renders, so the site is a call in
  the sense reach cares about. The join then treats it like any other
  site: lane A's fallback where it resolves, promoted to `semantic`
  where SCIP confirms. Measured on kbet: 12 direct test→component render
  edges, **all semantic tier** (BetCard among them — this entry's own
  example), and 108 of 174 tests now reach a component, with closure
  over what the component itself renders (`ActiveBetsStrip →
  StripButton`). The lanes agree on both kbet and this repo. The
  approval carried a standing condition: "in every meaningful sense"
  keeps its outliers named — which is the next field.
- **Residual edge cases — the outliers of "a JSX instantiation is a
  call":** only component-like tags count (a capitalised identifier or a
  dotted tag; `<div>` is a string at runtime, not code the repo owns);
  the framework mediates *when* the body runs, exactly as any call
  behind a branch mediates whether its callee runs; a closing tag is not
  a second site; and a component passed as a *value*
  (`<Route component={Card}>`) is still a `uses` edge, because nothing
  at that site instantiates it. kbet's remaining 44 empty-reach tests
  are store/logic tests in plain `.ts` files — a different residual
  (calls through mocks and store indirection), not this entry's subject.
- **Source:** V2.M3; lifted 2026-08-15, after V2.M6 and before V2.M7.

### C-33 — In-repo references across indexing units did not resolve — *lifted 2026-08-18, one session after registration*
- **Was:** a language's indexing units — Go modules, cargo roots, TS
  zones — are indexed separately and merged, so an in-repo reference
  *across* units resolved in neither index. Dagger's root-module calls
  into the `replace`d `./sdk/go` produced **zero** semantic edges — the
  dominant miss on exactly the monorepo shape where cross-unit edges
  are the architecture. Two stacked mechanisms, measured on a
  two-module fixture: per-unit staging stripped the sibling's sources
  (the loader could not type the import and mis-attributed it to the
  stdlib bucket), and `decode()` binned cross-index references into
  `external_refs`, discarding the moniker there — unfixable in
  principle at the merge.
- **Lifted by — the technique (ADR-049):** external rows keep their
  moniker (helper facts v3); `join_cross_unit` runs after each
  language's units merge and promotes external rows to references on
  **exact moniker equality** — never heuristically, so this is not the
  cross-zone reconciliation C-12 rejected (nothing interprets another
  unit's compiler config; a moniker matches byte-for-byte or the row
  stays external). Go replace targets are staged beside their consumer
  (`go_replace_targets`: the consumer's own go.mod only — Go's rule —
  path replacements only, in-repo only). Verified: the reproducing
  fixture flips 0% → 100% with the edge `semantic`/`calls`; dagger
  re-ingest numbers in `docs/extraction-evidence.md`.
- **Residual edge cases:** a moniker **two units both define** abstains
  and is reported (`scip-merge` degradation — C-28's rule across
  units; dagger's generated `internal/dagger` packages are the live
  case). **Rust** path-dependencies across *separate* workspaces are
  not staged together — members already collapse to one workspace
  unit, and no verified cross-workspace case exists to build against
  (the ADR-046/P11 rule). **TS** alias- and config-mediated cross-zone
  imports remain C-12's subject. **Version skew** would silence the
  join, not corrupt it: both sides are pinned to `0` (ADR-027
  Decision 1 is what makes monikers meet), and lane agreement is the
  watchdog if an indexer ever stamps them apart. A replace escaping
  the repo is not staged — code outside the repo is not ours to copy.
- **Source:** ADR-048 (registered), ADR-049 (lifted, same week the
  register said the fix needed its own review — Max reviewed and
  directed it).

---

## Debt summary

Three of **thirty-eight** entries are **unsurfaced** (C-4, C-19 — narrowed
to two tools — and C-20). C-31 left that list on 2026-08-21 (ADR-053:
the verification base stamped into the artifact and stated wherever a
language list is read), as did C-32's `partial`. The three derivation entries (C-35..C-37,
ADR-051) landed surfaced on day one — the statement prints on every
`hobbes plan` run and rides every change-spec. **Seven are lifted**, C-33 fastest of
all: registered from the dagger measurement (ADR-048) and lifted one
session later (ADR-049) when Max reviewed the candidate fix and
directed it — the register working as intended, a finding becoming a
fix through review rather than around it. The other six —
C-14 in the 2026-08-16 register paydown (three CLI packs; the entry's
own counter-example is the pinned exit check),
C-11 at V2.M3, C-3 and C-16 in the 2026-08-15 pre-M6 sweep (which also
surfaced C-5 and C-26), C-18 at V2.M6, and C-24 the same day: the JSX
lift was approved with the standing condition that "in every meaningful
sense" keeps its outliers named, which the lifted entry does. That churn
is the point of keeping the register: none of it was knowable before
this file existed, and what remains is the backlog P8 generates.

The **2026-08-16 paydown** worked the register's own ranking, worst
first: C-14 lifted (CLI packs), C-12 narrowed and
surfaced (ADR-041 — the #1 entry's common cases now resolve, its
residue reports itself), C-19 narrowed to two tools (semgrep executes
in the agreement suite, and its emitter survived first contact clean
where import-linter's had not), and C-21 surfaced (ADR-042 — the queue
shows the record a proposal restates, with the I-9/I-3 failure as the
pinned case). Four entries, four mechanisms, each landed with its
tests in one commit.

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

V2.M7 added three entries (**C-28/29/30**) and amended two (**C-9**: macro
is the fifth graph kind; **C-6**: a third indexer confirmed the
generalisation) — and it is the first milestone whose **every new entry
arrived surfaced**: C-28 through the decode degradation record, C-29
through a stderr disclosure on every rust ingest, C-30 through
`dependency_coverage`. C-28 also replayed C-6's arc at higher speed:
written for cargo targets in the morning, generalised the same day when
the verification re-ingest showed scip-go duplicating package namespaces
too — and this time the drop *removed two false semantic edges* that had
stood in the Go graph since V2.M5, the register mechanism catching a lie
rather than only naming a silence. C-29 is also a first of its kind: an
entry registering something Hobbes **does** (execute a Rust repo's
`build.rs` and proc macros at ingest) rather than something it cannot
see — the honesty discipline pointed at a capability instead of a gap.

Ranked by how badly each remaining entry misleads, worst first:

*(The two entries that held this list are gone as of the 2026-08-16
paydown: C-12 — cross-zone edges simply absent — is narrowed to
alias-only cases and surfaced (ADR-041), and C-14 — "an empty CLI list
reads as 'no CLI'" — is lifted outright. What remains stays quiet
rather than lying, which is a real difference; the worst residue is
C-4's fixture-thin test reach and C-19's still-unexecuted emitters.)*

**Nothing left in the register inflates a number.** C-11 was the only
entry that made a claim larger than the truth, and V2.M3 lifted it; C-24,
its deliberately-under-reporting residue, was lifted in turn once the
under-report could be replaced with the true edge rather than the safer
inaccuracy. Every remaining limit under-reports or stays silent — so a
Hobbes number can now be read as a floor, which is a property worth
defending in later milestones. **C-31 is the near-exception and the
reason it was filed** (2026-08-16): not a number but a word —
"supported" — that read larger than its evidence, a language list whose
rows presented as peers while their verification bases differ by an
order of magnitude. Architecture §3.8 now scopes the claim; the entry
holds the unsurfaced remainder, deliberately taken as debt with its
candidate surfacing named, rather than pretending a table in a document
reaches a user at ingest.

**The tail view landed the same day** (ADR-045, C-2 amended, C-32
added): the unresolved count now decomposes on every ingest into
observation-based classes, and the 2026-08-16 measurement that
motivated it showed the tails were never uniformly dark — kbet's
worst-looking number (72.1% accounted) hid a tail that is 61%
below-the-floor local bindings the checker could name all along, with
**9 sites of 1,339** fitting no observation at all. The measurement
also produced the session's working vocabulary: *seen and not modelled
by design* is knowledge; *cannot resolve* is the concentrated remainder
this register exists to track; and any of it that turns out to be
**needed** for derived context is a direct entry here, never a
percentage's rounding error.

**Track record so far:** three of the four entries touched at V2.M3 were
*already true and already invisible* before the register existed — C-23 in
particular had a check written specifically to catch it that could not fire
under any circumstances, and C-11 had been honestly documented at M6 and
went on misleading for two milestones. That is the argument for P8 restated
as evidence: being written down in an ADR at the moment of decision did not
stop either of them.
