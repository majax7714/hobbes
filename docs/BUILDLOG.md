# BUILDLOG

Append-only session log. One dated entry per session: what was built, what
changed from plan, open questions. Never edit old entries.

---

## 2026-08-10 — Repo scaffold + M0 (skeleton & policy semantics)

**Built:**

- Monorepo scaffolded per the D1 split: `go/`, `pipeline/`, `web/`
  (placeholder until M7), `docs/` (source docs moved here from the repo
  root), `.hobbes/` (`policies/` + `invariants/` versioned, `derived/` and
  `*.tfstate` gitignored from day one). Root README, CLAUDE.md, LICENSE,
  .gitignore.
- ADRs 001–004: policy YAML schema & file locations, resolution tie-breaks &
  defaults, the `hobbes-policy resolve` CLI contract (JSON + exit codes
  0/10/20), and M0 tooling choices (yaml.v3 + stdlib `flag`; argparse + uv).
- Go policy engine (`go/internal/policy`): strict-YAML parsing, box → repo →
  folder chain loader (nested folder policies, deepest most specific), and
  the resolution algorithm — deny wins from any scope, otherwise
  most-specific scope decides, escalate beats allow within a scope, unmatched
  commands fall back to the most specific `default:` (engine fallback:
  escalate). 52 test cases covering shadowing, deny-wins,
  folder-over-repo-over-box precedence, the escalate tier, defaults, glob
  matching, loading, and CLI exit codes. `go vet` clean.
- `hobbes-policy resolve` CLI (`go/cmd/hobbes-policy`) per ADR-003.
- Python `hobbes` CLI skeleton (`pipeline/`): `init`/`ingest`/`diff` stubs
  that name their delivering milestone, plus `hobbes policy resolve`
  passthrough (binary via `$HOBBES_POLICY_BIN` then `$PATH`). 17 hermetic
  pytest cases (fake binary — no Go toolchain needed to run them).
- Dogfood `.hobbes/policies/repo.policy` for this repo (tfstate deny,
  force-push deny, build/test allows, `git push` escalate). Verified
  end-to-end: Python CLI → Go binary → this repo's policy returns
  allow/deny/escalate with exit 0/10/20.

**Changed from plan:**

- Nothing substantive. Housekeeping: the two source docs moved from the repo
  root into `docs/`. Toolchain installed user-locally (no passwordless sudo
  on this box): Go 1.26.5 at `~/.local/go/bin`, uv 0.12.3 at `~/.local/bin`.
- One reconciliation, recorded in ADR-001: architecture §5.1 sketches the
  repo policy at `.hobbes/repo.policy` while §10's layout puts hand-reviewed
  policy under `.hobbes/policies/`; went with §10
  (`.hobbes/policies/repo.policy`). Folder policies stay
  `<folder>/.hobbes/folder.policy` per §5.1.

**Open questions for Max:**

1. LICENSE defaulted to MIT (you asked for a LICENSE file but didn't name
   one) — swap if you want something else.
2. ADR-002: engine fallback for a command no rule matches is **escalate**
   (not deny) — deliberate, since escalation itself expires to deny at the
   enforcement layer. Confirm or overturn.
3. ADR-002: escalate is shadowable by a more specific scope's allow; only
   deny is absolute. That's my reading of §5.1 — confirm.
4. Commits were made directly on `main` (matching the repo's existing
   history). Say the word if you'd rather have milestone branches + PRs.

**M0 exit criteria:** policy merge tests green (shadowing, deny-wins,
precedence, escalate tier) ✔ · repo scaffolded ✔ · docs written ✔.
Awaiting review before M1.

---

## 2026-08-10 (second session) — M1: Python extractor

M0 review passed (ADRs confirmed); commits pushed by Max.

**Built:**

- ADRs 005–007: tree-sitter packages over stdlib `ast` (uniformity with
  M3/M6), the three artifact schemas + id conventions + no-timestamp
  determinism, and the static resolution strategy (what resolves, what is
  deliberately omitted).
- `hobbes.extract` package: `discover` (import identities, collision
  disambiguation), `pysource` (tree-sitter walk: imports, symbols with
  decorators, call sites, env reads), `graph` (typed module/symbol edges —
  `imports`, `env-read`, `calls`; external `ext:` nodes for third-party,
  stdlib dropped; `env:` nodes as M3 join keys), `interfaces`
  (FastAPI/Flask routes from decorator sites only, `[project.scripts]`
  entry points), `testmap` (pytest defaults, transitive call-closure
  reach), `emit` (SHA+dirty stamp, sorted deterministic JSON).
- `hobbes ingest` and `hobbes init` wired for real; `diff` stays an honest
  M2 stub. 75 pytest cases against a committed fixture repo
  (`tests/fixtures/miniapp`), including byte-identical-rerun and
  git-integration tests.
- Dogfood: `hobbes ingest` on this repo — 35 nodes, 52 module edges,
  189 symbols, 159 call edges, 73 tests; hobbes.* edges hand-verified.

**Changed from plan:**

- `tree-sitter` pinned `<0.26`: the 0.26.0 core segfaulted mid-walk on
  ~300-line files (reproduced against this repo's own sources; same code
  and grammar clean on 0.25.x). Noted in ADR-005; revisit on a new
  upstream release.

**Open questions for Max:**

1. The M1 exit bar wants the spot-check on a *real repo of yours*. The
   dogfood run on hobbes itself gives 52 module edges / 73 tests — enough
   material, but it's code written this session. Point me at one of your
   Python repos for an independent ingest, or bless the dogfood run as the
   exit check.
2. Static reach through the CLI is honest but broad (a CLI test reaches
   every subcommand path via `main`). If that reads as noise once you see
   it in the UI, per-test reach depth or entry-point trimming is a cheap
   M5-era refinement — flagging, not proposing, for now.

**M1 exit criteria:** extractor built with tests ✔ · artifacts SHA-stamped
and deterministic ✔ · spot-check on a real repo — **pending your review**.

---

## 2026-08-10 (third session) — M2: graph render + diff

M1 review passed (derived artifacts spot-checked by Max); commits pushed.

**Built:**

- ADRs 008–009: Mermaid render conventions (flowchart LR, synthetic node
  ids, package clustering, kind shapes, type-styled edges) and graph-diff
  semantics (identity = node id / edge (from,to,type); evidence changes
  are not deltas; ref extraction via `git archive` + the pure extractor;
  exit codes mirror diff(1); `--json` for the M7/M8 consumers).
- `hobbes.render.to_mermaid` — deterministic module-level Mermaid export;
  `hobbes render` reads the ingest artifact and prints it.
- `hobbes.graphdiff` — `extract_at_ref` (git archive → scratch dir → pure
  extraction, checkout untouched), `diff_graphs` (both layers),
  `format_delta` (module-level lines + symbol-layer counts).
- `hobbes diff <base>..<head> [--json]` wired; bare `<base>` means
  `..HEAD`; three-dot ranges rejected. The last CLI stub is gone.
- 99 pytest cases total (24 new: render shape/determinism, delta
  semantics, ref extraction, CLI exit codes).

**Validated on real history** (the M2 exit bar, using this repo's own
commits in place of a PR):

- `hobbes diff 9158c43..f8a15f3` (the M1 CLI-wiring commit) →
  exactly `+ imports hobbes.cli -> hobbes.extract` and
  `-> hobbes.extract.emit` with correct evidence lines; exit 1.
- `hobbes diff 312f153..9158c43` (extractor introduction) → all new
  modules/externals/env nodes; also correctly surfaced the id
  re-disambiguation (`tests` → `pipeline:tests` +
  `pipeline/tests/fixtures/miniapp:tests`) as remove+add — the ADR-006
  collision rule made visible.
- Docs-only range → "no architectural changes", exit 0.

**Changed from plan:** nothing.

**Open questions for Max:**

1. A package *rename* (or an id re-disambiguation like the `tests` case
   above) appears as `- old` + `+ new` — identity is by id, so renames
   aren't tracked. Fine for v1? Rename detection (path-based matching)
   would be an M7-era nicety if the remove+add pairs read poorly in review.
2. `hobbes diff` sees only committed trees (`git archive`); uncommitted
   work is invisible. ADR-009 sketches a `--worktree` mode if you find
   yourself wanting `main..working-tree` diffs in practice.

**M2 exit criteria:** a real commit range produces a correct edge-level
delta ✔ (three ranges hand-verified above) — **pending your review**.
