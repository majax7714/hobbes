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
  stdio, ADR-013/014; `escalations` = the approve/deny CLI, ADR-016):
  `internal/proxy/` (policy-checked `exec` + read-only knowledge tools) +
  `internal/recorder/` (append-only JSONL flight log at
  `~/.hobbes/sessions/<session>/flight.jsonl`, ADR-015) +
  `internal/escalation/` (park/approve/expire queue, ADR-016) +
  `internal/knowledge/` (graph_neighborhood/who_calls/tests_guarding over
  `.hobbes/derived/`, ADR-017). `cmd/hobbes-session/` +
  `internal/sandbox/` launch a session in rootless Podman (ADR-018).
  Only external Go deps: `yaml.v3`, `modelcontextprotocol/go-sdk`.
- `sandbox/` — the M4 session image (`Containerfile`), the static proxy it
  copies (gitignored build artifact), and the exit-check harness
  (`driver.py` scripted implementer, `exitcheck.py` orchestrator).
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

**Active milestone: M4 (policy proxy + sandbox + flight recorder) —
all three chunks built; the full M4 exit check passed. Pending Max's
review.** M4 is the last enforcement milestone; do not start M5 (narrative
pass — the first subscription-quota milestone) until reviewed.

- Chunk 1 (reviewed, passed): `hobbes-proxy serve` (ADR-013/014/015) —
  per-session stdio MCP server, `exec` resolved through `internal/policy`
  (allow runs via `sh -c` with timeout+output caps; deny refuses), every
  call logged to the flight recorder.
- Chunk 2 (reviewed, passed): escalation queue (ADR-016) — escalated
  commands park as atomic JSON under
  `~/.hobbes/sessions/<session>/escalations/`, blocking the exec call;
  `hobbes-proxy escalations list|approve|deny` resolves them (approver =
  OS user); approved commands run in place; unanswered parks expire to
  deny; park + resolution flight lines joined by `escalation.id`.
- Chunk 3 (this): knowledge tools (ADR-017 —
  graph_neighborhood/who_calls/tests_guarding, read-only, logged,
  provenance + staleness) + session wrapper & sandbox (ADR-018 —
  `hobbes-session start` clones a fresh worktree, mounts it rw with
  session state, clean env, Claude Code wired to the proxy; `--dry-run`
  prints the plan). 140 Go test cases. **M4 exit check passed 5/5 in a
  real rootless-Podman sandbox on the hobbes repo** (`sandbox/exitcheck.py`,
  session `S-exitcheck-m4`): injected AWS/GitHub secrets absent from the
  session env; knowledge query answered; task file written + seen via
  allowed exec; `cat prod.tfstate` refused+logged; `id` parked → approved
  from the CLI → ran. The exit-check implementer was scripted (ADR-018)
  to keep M4 quota-free; the wrapper's default target is live Claude Code.
- Deferred to their data: `get_module_doc` (M5), `list_invariants` (M8);
  per-command secret brokering (the ajax-manager pattern) layers onto the
  proxy later — v1's guarantee is the empty-env baseline.

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
