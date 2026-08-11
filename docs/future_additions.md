# Future additions

Reviewed-and-deferred ideas: things flagged in a BUILDLOG entry, looked at
by Max, and consciously parked — with the context needed to pick them up
later. Not a wishlist; everything here was deferred *on purpose*.

- **Graph-diff rename detection** (from M2, deferred 2026-08-10).
  Node identity is by id (ADR-009), so a package rename — or an id
  re-disambiguation like `tests` → `pipeline:tests` — shows as
  remove+add pairs. Path-based matching could pair them. Revisit if the
  pairs read poorly in real PR review (likely surface: M7 UI or M8
  `hobbes review`).

- **`hobbes diff --worktree` mode** (from M2, deferred 2026-08-10).
  Diff currently sees only committed trees (`git archive`, ADR-009). Max
  develops mostly on main, so `base..working-tree` comparisons haven't
  been needed. If they are, extract the live tree with the pure extractor
  instead of an archive — the plumbing already allows it.

- **Test-reach trimming** (from M1, deferred 2026-08-10).
  Static reach through a CLI entry point is broad — every CLI test
  reaches every subcommand handler via `main`. Honest, but noisy. Options
  when it hurts (likely at M5's behavioral index): depth limits,
  entry-point-aware trimming, or fixture-resolution to sharpen pytest
  reach.

- **System narrative — user-journey walkthroughs** (from M5, deferred
  2026-08-11, Max-confirmed). Architecture §3.2 lists data-flow
  walkthroughs of the top 3–5 user journeys alongside the M5 artifacts,
  but the build plan's M5 line and exit criteria don't need them, and
  picking "top journeys" wants either a heuristic (entry points ranked
  by reach?) or a human list. Natural surface: M7's docs tab, where a
  walkthrough would actually render; the ADR-019 claim/pin schema
  already fits it (a walkthrough is an ordered list of pinned claims).

- **Cartographer sessions in the M4 sandbox** (from M5, ADR-020's
  "deferred, not rejected"). v1 narrative units are single-shot
  tool-less `claude -p` calls. If skeleton gaps show up as shallow docs
  (the cartographer can't follow a chain the extractor missed), move
  narrative generation into sandboxed sessions with the role mounts
  ADR-018 already supports (ro source, rw .hobbes/), and flight-log it.

- **Per-package tsconfigs in monorepos** — *picked up 2026-08-11, same
  day*: kbet's `@/*` aliases un-deferred this immediately; the helper
  now zones files by nearest tsconfig.json, one ts-morph Project per
  zone (see BUILDLOG tenth-session addendum). Remaining edge: imports
  *across* zones don't resolve (separate programs) — revisit if a real
  monorepo has package-to-package imports.

- **Per-test JS reach** (from M6, deferred 2026-08-11). JS test reach
  is file-level: every case in a test file shares the file's
  imports+calls closure, because test bodies are anonymous closures,
  not symbols. Per-case reach would need walking each `it()` callback's
  body for its own call set — doable in the helper if the coarseness
  ever hurts the behavioral index or `tests_guarding`.

- **jest-globals detection and package.json bin entry points** (from
  M6, deferred 2026-08-11). Test files using injected globals (no
  framework import) are inventoried as framework `unknown`; a jest
  config file in the repo could sharpen the label. `interfaces.json`
  CLI entry points still come from pyproject only — package.json `bin`
  is the JS analog when a repo needs it.

- **PR mode over the interactive graph** (from M7, deferred
  2026-08-11). ADR-023 leaves room for it: colouring added/removed edges
  over the same view rather than a second graph surface. It waits on M8,
  which is where `hobbes review` computes the diff the surface would
  render — the M2 graph-diff engine already exists in Python, so the
  open question is only whether the Go server shells out to it or M8
  materializes the delta as an artifact.

- **Compound nodes and layout extensions** (from M7, deferred
  2026-08-11). ADR-023 groups packages by colour and filter, not by
  Cytoscape compound nodes — they fight force layouts at 100–200 nodes
  and make edge endpoints ambiguous. Likewise `cytoscape-dagre`/`fcose`
  are better layered layouts than the built-ins, but the
  breadthfirst-on-focus rule covers the case dagre would serve. Revisit
  if a repo arrives with few, large packages, or if focus mode stops
  being enough.

- **Push transport for the Sessions tab** (from M7, deferred
  2026-08-11). The surface polls (ADR-022) because a push transport
  would still need the server to watch the filesystem, or take a watcher
  dependency, to know when to push. If a long session makes the 2.5s
  poll feel laggy or costly, SSE over an fsnotify watch is the upgrade;
  the `?after=` line cursor already gives it an incremental protocol.

- **Symbol-level graph rendering** (from M7, deferred 2026-08-11).
  Both renderers draw modules only (§10: store symbol-level, render
  module-level) — the dogfood repo alone has 537 symbols and 657 call
  edges. The inspector and `who_calls` answer symbol questions today.
  Revisit only if a review question turns out to need the call graph
  drawn rather than queried.

- **Soft verdicts are delta-based, not source-based** (from M8, deferred
  2026-08-11). The reviewer session for a `soft` invariant runs through
  the ADR-020 tool-less runner, so it judges from the architecture delta
  and the changed-file list rather than from the files themselves — the
  sessions said so unprompted during the M8 exit check. That is honest
  but shallow: "does this change violate the invariant" often needs the
  diff hunks. The fix is the same one ADR-020 already parks — run these
  in the M4 sandbox with a reviewer role, which now has read-only mounts
  and the knowledge tools (M8). Revisit when a soft verdict is wrong in
  a way source access would have caught.

- **The compiled configs are verified by shape, not by execution** (from
  M8, deferred 2026-08-11). None of import-linter, dependency-cruiser,
  semgrep, or conftest is installed on the dev box, which is exactly why
  ADR-024 makes compilation pure text generation. The emitters are
  asserted against the formats' documented shapes; nothing has run
  `lint-imports` over the generated `.ini`. First CI run that executes
  them is the real test, and any mismatch is an emitter fix plus a
  regression case.

- **import-linter `layers` contracts** (from M8, deferred 2026-08-11).
  ADR-024 ships three rule kinds because three records needed them.
  Layered-architecture contracts ("nothing below may import above") are
  the obvious fourth, and import-linter and dependency-cruiser both
  support them natively — but no invariant has wanted one yet, and
  building the emitter first is the speculative abstraction the
  conventions forbid.

- **Cross-language module-id namespacing** (from M8 review, deferred
  2026-08-11, Max-raised). Language *selection* is already right —
  discovery is by extension, so each language has exactly one parser and
  no parser sees another's files (I-4). What is not right is what
  happens when two layers want the same node id: a repo-root `widget.py`
  and `widget.ts` both derive the id `widget`, and the merge resolves it
  by pipeline order (Python, then HCL, then TS). That is now **loud** —
  the loser is recorded in `extraction_errors` and warned at ingest —
  but the file is still omitted from the graph, which is data loss
  decided by an accident of ordering.

  The principled fix is to namespace the incoming layer's ids on
  collision, the way `discover.py` already disambiguates Python-internal
  clashes into `root:name`. It was deferred because doing it properly
  means rewriting ids across a whole layer's nodes, module edges,
  symbols, symbol edges, tests, and routes — a change to the M6 contract
  that deserves its own ADR rather than a corner of M8. Pick it up when
  a real repo hits the collision, or before the fourth language lands,
  whichever comes first; the extraction_errors record already names
  every case that would have been affected.

- **Decisions do not survive a fresh clone** (from ADR-026, deferred
  2026-08-11, Max-confirmed as a known limitation). ADR-012 gitignores
  the whole `.hobbes/` in target repos, so `.hobbes/decisions.yaml`,
  `.hobbes/invariants/`, and `.hobbes/policies/` are untracked there.
  Every approval, denial, and intent confirmation is therefore *this
  clone on this machine* — recloning, or moving to another box, asks the
  whole queue again. The "set once, holds until you change it" promise
  holds within a workspace and silently does not across them.

  The fix ADR-012 already allows: opt `.hobbes/policies/` and
  `.hobbes/invariants/` (and the ledger) into git per repo, keeping
  `derived/` ignored — the "repos that already track .hobbes/ content"
  path, which this repo uses. That also makes decisions reviewable in a
  PR and shared with collaborators, which may or may not be wanted.
  Deferred until the re-asking actually costs something.
