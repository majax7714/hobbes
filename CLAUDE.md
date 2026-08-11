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
  folder, deny overrides allow, allow|deny|escalate).
  `cmd/hobbes-proxy/` is the per-session M4 daemon (`serve` = MCP over
  stdio, ADR-013/014): `internal/proxy/` (policy-checked `exec` tool) +
  `internal/recorder/` (append-only JSONL flight log at
  `~/.hobbes/sessions/<session>/flight.jsonl`, ADR-015). Only external Go
  deps: `yaml.v3`, `modelcontextprotocol/go-sdk`.
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
go build -o bin/hobbes-proxy  ./cmd/hobbes-proxy

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
- **Hobbes files are personal (ADR-012):** in Max's repos, the entire
  `.hobbes/` directory is gitignored — `ingest`/`init` enforce it
  automatically. Only this repo (dogfooding §10) versions its `.hobbes/`.

## Current status

**Active milestone: M4 (policy proxy + sandbox + flight recorder), split
into three review-gated chunks (Max-approved plan). Chunk 2 — escalation
queue — built, pending Max's review.** Do not start chunk 3 until that
review has happened.

- Chunk 1 (reviewed, passed): `hobbes-proxy serve` (ADR-013/014/015) —
  per-session stdio MCP server, one `exec` tool resolved through
  `internal/policy` (allow runs via `sh -c` with timeout+output caps;
  deny refuses), every call logged to the flight recorder.
- Chunk 2 (this): escalation queue (ADR-016) — escalated commands park
  as atomic JSON records under `~/.hobbes/sessions/<session>/escalations/`,
  blocking the exec call (MCP progress notifications keep it alive);
  `hobbes-proxy escalations list|approve|deny` resolves them (approver =
  OS user); approved commands run inside the original call; unanswered
  parks expire to deny (`--escalation-timeout`, default 30m §9); park +
  resolution flight lines joined by `escalation.id`. 114 Go test cases;
  hand-verified on the hobbes repo (approve→ran / deny / expiry;
  sessions `S-handcheck-m4c2*`).
- Chunk 3 (next, after review): session wrapper + Podman rootless
  sandbox (D2) + knowledge-layer MCP query tools + secret brokering;
  then the full M4 exit check.

- M0: policy YAML format (ADR-001/002), Go merge engine +
  `hobbes-policy resolve` CLI (ADR-003), Python CLI skeleton with policy
  passthrough, dogfood repo policy.
- M1: deterministic Python extractor (ADR-005/006/007;
  **tree-sitter pinned <0.26**, 0.26.0 core segfaults). `hobbes ingest` /
  `hobbes init`.
- M2: Mermaid export (`hobbes render`, ADR-008), graph
  diff (`hobbes diff <base>..<head>`, ADR-009). Deferred ideas live in
  `docs/future_additions.md`.
- M3: Terraform/HCL extractor (`extract/terraform.py`, ADR-010) —
  `tf:` nodes (resource/data/tf-module), `references` edges,
  cross-layer joins (`env-set` → `env:VAR` ← `env-read`, and `packages`
  path joins onto discovered modules), optional `--tf-plan` enrichment
  (tfstate lookalikes refused). graph.json schema v2 (`languages` list).
  Builtin tfstate deny floor in the Go engine (ADR-011). Test repos
  (Max-sanctioned): `~/SELENEX` (Py+JS+TF; cross-layer `packages` edge
  verified by hand at infra-core/lambda.tf:5 → handler.py) and
  `~/qwen-pathology` (Python).
- ADR-012: Hobbes files are personal — `ingest`/`init` gitignore the
  whole `.hobbes/` in target repos (tracked-content guard keeps this
  repo's dogfood versioning). 124 pytest cases.
