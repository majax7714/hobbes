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

- **Per-package tsconfigs in monorepos** (from M6, deferred 2026-08-11).
  The helper honors a repo-root `tsconfig.json` or supplies allowJs
  defaults (ADR-021); nested per-package configs (path aliases per
  workspace) are ignored. Revisit when a real repo's aliases fail to
  resolve — the fix lives entirely in `tsextract/extract.mjs` project
  setup.

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
