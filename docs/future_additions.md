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
