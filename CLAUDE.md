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
  CLI (`src/hobbes/cli.py`), the shell-out wrapper for the Go policy binary
  (`src/hobbes/policy.py`), and the deterministic extractors
  (`src/hobbes/extract/`: discover → pysource (tree-sitter walk) → graph /
  interfaces / testmap → emit). The invariant compiler lands at M8. Test
  fixture repo: `tests/fixtures/miniapp/` (excluded from pytest collection
  via `norecursedirs`).
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

**Active milestone: M1 (Python extractor) — built, pending Max's exit
review** (the build-plan exit bar: spot-check 20 edges + 10 test mappings by
hand on a real repo, ≥90% correct at module level). Do not start M2 until
that review has happened.

Done through M1:
- M0 (reviewed, passed): policy YAML format (ADR-001/002), Go merge engine +
  `hobbes-policy resolve` CLI (ADR-003), Python CLI skeleton with policy
  passthrough, dogfood repo policy. 52 Go test cases.
- M1: deterministic extractor in `pipeline/src/hobbes/extract/` —
  tree-sitter walk (ADR-005; **tree-sitter pinned <0.26**, 0.26.0 core
  segfaults), typed module/symbol graph with `imports`/`env-read`/`calls`
  edges (resolution rules ADR-007), FastAPI/Flask route inventory, pytest
  inventory with static reach, SHA+dirty-stamped deterministic JSON
  artifacts (schemas ADR-006). `hobbes ingest` and `hobbes init` are real;
  `hobbes diff` stays stubbed until M2. 75 pytest cases; dogfood ingest of
  this repo verified by hand.

Next (after review): M2 — graph render (Mermaid) + graph diff
(`hobbes diff <base>..<head>`).
