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
  `internal/knowledge/` (graph_neighborhood/who_calls/tests_guarding/
  get_module_doc over `.hobbes/derived/`, ADR-017/019). `cmd/hobbes-session/` +
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
  the graph-diff engine (`src/hobbes/graphdiff.py`), and the M5 narrative
  pass (`src/hobbes/narrate/`: ADR-019 artifact schema + blob-level
  staleness, ADR-020 headless tool-less `claude -p` runner, orchestrator
  behind `hobbes narrate` / `hobbes docs status`). The invariant
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

**Active milestone: M5 (narrative pass) — built; the M5 exit check
passed 3/3 on the dogfood repo. Pending Max's review** (including the
6 inferred invariants awaiting confirmation). Do not start M6
(TypeScript extractor) until reviewed.

- ADR-019: narrative artifacts under `.hobbes/derived/docs/` — module
  docs (one per source-backed module/package node), per-test-file
  behavior indexes, `invariants.inferred.yaml` (§10 shape, ids +
  `status: inferred` assigned at write time; confirmation = Max moves a
  record into versioned `.hobbes/invariants/`). Claims are
  `{text, pins}` validated against the working tree before anything is
  written. Artifacts stamp repo SHA + per-cited-file git blob SHAs;
  **staleness is blob-level** (any cited blob changed/gone — uncommitted
  edits count; deliberately stricter than the build plan's graph-node
  trigger).
- ADR-020: `hobbes narrate` = one headless `claude -p --output-format
  json --tools ""` call per unit (no tools — no I/O surface; the
  pipeline is the only writer). Parse → validate → one corrective retry
  carrying the problem list → or unit fails, run continues. Incremental
  (missing-or-stale) by default; `--all`/`--only`/`--exclude`/
  `--dry-run`; `--model`; `HOBBES_CLAUDE_BIN` overrides the binary.
  `hobbes docs status` prints stale badges. Sandboxed cartographer
  sessions + system narrative deferred to `future_additions.md`
  (Max-confirmed).
- `get_module_doc` joined the proxy's knowledge tools (ADR-017 deferral
  due with its data); blob-level stale warnings, logged
  `builtin:knowledge-read`. Still deferred to its data:
  `list_invariants` (M8).
- Exit check (2026-08-11): 37/37 units, 0 failed — 396 pinned claims on
  the hobbes repo (fixture tree excluded); 10/10 sampled claims resolve
  to supporting lines; an uncommitted `render.py` edit flips exactly the
  `hobbes.render` badge. 197 pytest / 146 Go test cases.

- M4 (reviewed, passed): the policy proxy + sandbox + flight recorder —
  `hobbes-proxy serve` (per-session stdio MCP, policy-checked `exec`,
  ADR-013/014/015), escalation queue with CLI approve/deny and
  expire-to-deny (ADR-016), knowledge tools (ADR-017), and
  `hobbes-session start` (fresh local clone, rootless Podman, empty-env
  baseline, ADR-018). M4 exit check passed 5/5 in a real sandbox with a
  scripted implementer (quota-free); per-command secret brokering layers
  on later.

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
