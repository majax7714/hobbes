# CLAUDE.md — working notes for Claude Code sessions

## What this project is

Hobbes: an agentic development environment that ingests a repo and produces a
policy-governed environment where agents do line-level work and humans review
at the concept level. **Source of truth:** `docs/hobbes-architecture.md` and
`docs/hobbes-build-plan.md` — read them before writing code. Locked decisions
(not open for relitigation): **D1** Python + Go + TS split by focus, **D2**
Podman rootless for session isolation, **D3** Cytoscape.js for the interactive
graph.

## Project map

- `go/` — Go module (`github.com/majax7714/hobbes/go`). `cmd/hobbes-policy/`
  is the policy CLI; `internal/policy/` is the merge engine (box → repo →
  folder, deny overrides allow, allow|deny|escalate). The M4
  proxy/supervisor/recorder daemon will live here too and import the same
  package.
- `pipeline/` — Python package `hobbes` (uv-managed, src layout). The `hobbes`
  CLI (`src/hobbes/cli.py`) and the shell-out wrapper for the Go policy binary
  (`src/hobbes/policy.py`). Extractors and invariant compiler land here in
  M1+.
- `web/` — empty until M7 (Vite + React + Cytoscape.js).
- `docs/` — the two source docs, `docs/adr/` (numbered ADRs), and
  `docs/BUILDLOG.md` (append-only session log).
- `.hobbes/` — dogfooding: `policies/` + `invariants/` versioned, `derived/`
  gitignored.

## Build & test

Go and uv are user-local installs: `~/.local/go/bin` and `~/.local/bin`
(ensure both are on `PATH`).

```sh
# Go
cd go
go test ./...
go build -o bin/hobbes-policy ./cmd/hobbes-policy

# Python
cd pipeline
uv sync
uv run pytest
uv run hobbes policy resolve "some command"   # needs hobbes-policy built;
                                              # set HOBBES_POLICY_BIN or PATH
```

## Conventions

- **Milestone order is strict.** Never start milestone N+1 in a session where
  milestone N's exit criteria haven't been met *and reviewed by Max*.
- Tests accompany the code they test **in the same commit**.
- Conventional commits, scoped: `feat(policy): ...`, `fix(cli): ...`,
  `test/docs/chore`.
- One short ADR (`docs/adr/NNN-title.md`) for every design decision the two
  source docs don't already make. Number sequentially.
- `docs/BUILDLOG.md` is append-only; one dated entry per session. Never edit
  old entries.
- Every package/module gets doc comments explaining purpose and contract;
  public functions documented. No orphan code.
- No speculative abstraction — build what the current milestone needs.
- **Never read or write `.tfstate` files. Never commit anything under
  `.hobbes/derived/`.**

## Current status

**Active milestone: M0 (skeleton + policy semantics) — complete, pending
Max's review.** Do not start M1 until that review has happened.

Done in M0:
- Monorepo scaffolded (`go/`, `pipeline/`, `web/` placeholder, `docs/`,
  `.hobbes/`), docs moved to `docs/`, ADRs 001–004 written.
- Policy file YAML format defined (ADR-001) and the Go merge engine
  implemented in `go/internal/policy/` with the table-driven battery covering
  shadowing, deny-wins, folder-over-repo-over-box precedence, and the
  escalate tier.
- `hobbes-policy resolve` CLI (exit codes: 0 allow / 10 deny / 20 escalate,
  JSON on stdout — ADR-003).
- Python `hobbes` CLI skeleton: `init`/`ingest`/`diff` stubs plus
  `hobbes policy resolve` shelling out to the Go binary.
- Dogfood `.hobbes/policies/repo.policy` for this repo.

Next (after review): M1 — Python extractor (tree-sitter symbols, module
graph, routes, pytest inventory → `derived/graph.json` etc.).
