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
  (`src/hobbes/policy.py`), the deterministic extractors
  (`src/hobbes/extract/`: discover → pysource (tree-sitter walk) → graph /
  interfaces / testmap → emit), the Mermaid export (`src/hobbes/render.py`),
  and the graph-diff engine (`src/hobbes/graphdiff.py`). The invariant
  compiler lands at M8. Test fixture repo: `tests/fixtures/miniapp/`
  (excluded from pytest collection via `norecursedirs`).
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

**Active milestone: M2 (graph render + diff) — built, pending Max's exit
review** (build-plan exit bar: a real PR/commit range produces a correct
edge-level delta). Do not start M3 until that review has happened.

Done through M2:
- M0 (reviewed, passed): policy YAML format (ADR-001/002), Go merge engine +
  `hobbes-policy resolve` CLI (ADR-003), Python CLI skeleton with policy
  passthrough, dogfood repo policy. 52 Go test cases.
- M1 (reviewed, passed): deterministic extractor in
  `pipeline/src/hobbes/extract/` — tree-sitter walk (ADR-005;
  **tree-sitter pinned <0.26**, 0.26.0 core segfaults), typed module/symbol
  graph (`imports`/`env-read`/`calls`, rules in ADR-007), route inventory,
  pytest inventory with static reach, SHA+dirty-stamped deterministic
  artifacts (ADR-006). `hobbes ingest` / `hobbes init`.
- M2: Mermaid module-graph export (`hobbes render`, ADR-008) and the graph
  diff (`hobbes diff <base>..<head> [--json]`, ADR-009 — git-archive ref
  extraction, exit codes mirroring diff(1)). Validated against this repo's
  real history (extractor-introduction and CLI-wiring ranges hand-checked;
  docs-only range exits 0). 99 pytest cases total.

Next (after review): M3 — Terraform/HCL extractor with cross-layer
env-var joins; `.tfstate` deny in the default box policy.
