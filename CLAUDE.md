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
  `cmd/hobbes-web/` + `internal/web/` are the M7 surface server
  (ADR-022): a loopback-only JSON API over the derived artifacts, the
  repo reads a browser cannot do (source, `git diff`), the flight-log
  tail, and the surface's only mutation — escalation approve/deny,
  delegated to `internal/escalation`. The built SPA is embedded from
  `internal/web/dist/` (gitignored but for its `.gitkeep`).
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
  behind `hobbes narrate` / `hobbes docs status`). `extract/tssource.py`
  joins the tsextract helper's facts (M6, ADR-021). The invariant
  compiler lands at M8. Test fixture repos: `tests/fixtures/miniapp/`
  (Python) and `tests/fixtures/minits/` (TS/JS), both excluded from
  pytest collection via `norecursedirs`.
- `tsextract/` — Node helper (ADR-021): ts-morph walk emitting facts
  JSON for the Python join; own `node --test` suite (`npm test`);
  `node_modules/` gitignored, lockfile committed. Only external dep:
  ts-morph.
- `web/` — the M7 surface (Vite + React + TS, Cytoscape.js per D3).
  `src/lib/` holds the pure layer and all the vitest cases (graph model
  and focus neighborhood, §4.2 index joins, patch parsing); `src/tabs/`
  is one component per tab. `npm run build` typechecks, then bundles
  into the Go embed dir — **rebuild `hobbes-web` after**, or it serves
  the previous bundle. `npm run dev` proxies `/api` to a running server.
- `docs/` — the two source docs, `docs/adr/` (numbered ADRs), and
  `docs/BUILDLOG.md` (append-only session log).
- `.hobbes/` — dogfooding: `policies/` + `invariants/` versioned, `derived/`
  gitignored.

## Build & test

Go, uv, and Node are user-local installs: `~/.local/go/bin` and
`~/.local/bin` (ensure both are on `PATH`). One-time: `cd tsextract &&
npm install` (TS extraction) and `cd web && npm install` (the surface).

```sh
# Go
cd go
go test ./...
go build -o bin/hobbes-policy ./cmd/hobbes-policy
go build -o bin/hobbes-proxy  ./cmd/hobbes-proxy
go build -o bin/hobbes-web    ./cmd/hobbes-web   # after `cd web && npm run build`

# Web surface (M7)
cd web
npm test                                          # vitest, the pure layer
npm run build                                     # bundles into go/internal/web/dist/
../go/bin/hobbes-web serve --repo /path/to/repo   # http://127.0.0.1:7777

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

**Active milestone: M7 (web surface) — built; the exit check passed on
the dogfood repo and on kbet, including escalation approve/deny in the
browser against real parked commands. Pending Max's review.** Do not
start M8 (reviewer flow + invariant compiler) until reviewed.

- ADR-022: the surface is a **Go daemon** (`hobbes-web serve --repo
  DIR`) serving a JSON API and the embedded SPA — not a Python
  `hobbes serve`, because approve/deny would otherwise reimplement the
  ADR-016 queue. Extractor artifacts pass through byte-for-byte;
  narrative artifacts are decoded only far enough to badge.
  **Loopback-only, enforced** at bind and per-request `Host` (no auth,
  and it can approve commands). `/api/source` refuses traversal,
  symlink escapes, binaries, oversize files, and `.tfstate`. Missing
  artifacts answer 404 with the command that produces them.
- ADR-023: interactive graph conventions — module level only, shape and
  colour by kind, edge style by type (unknown types drawn labelled, not
  invisible), **externals hidden by default**, and **focus mode**
  (breadthfirst over the selected neighborhood, the rest dimmed in
  place). Labels strip the directory every path-shaped id shares, or a
  TS repo renders 89 identical `betchat/frontend/sr…` labels.
- The SPA lives in `web/`, is embedded into the binary, and **must be
  rebuilt on both sides**: `npm run build` then `go build`. The pure
  layer (`web/src/lib/`) carries the vitest cases; the tabs render what
  it returns.
- Exit check (2026-08-11): five tabs real on the dogfood repo (70 nodes,
  234 tests, 37 artifacts, 9 stale); a claim's pin resolves to the line
  that supports it; two escalations parked through the real proxy —
  approve unblocked and ran it, deny refused it, both logged with the
  approver; kbet (104 nodes, 174 tests, no narrate pass) serves and
  degrades correctly. 189 Go / 226 pytest / 38 vitest / 18 node.

- M6 (reviewed, passed twice): TS/JS extraction via the `tsextract/`
  Node helper (ts-morph) invoked as a subprocess — the ADR-003 pattern;
  supersedes ADR-005's tree-sitter-for-M6 aside per the source docs.
  Facts JSON in,
  artifacts out: checker-resolved imports/calls (false edges worse than
  missing; nested declarations omitted), path-based module ids
  (`src/flow`), `ext:`/`env:` nodes on M3 conventions (env joins now
  span Py+TF+JS), Express/Nest routes, test inventory for
  vitest/jest/**node:test** with file-level static reach.
  `HOBBES_TSEXTRACT_CMD` overrides; TS files + no helper = hard error,
  never a silent skip.
  - **Schema v3**: per-test `framework` field (global one gone);
    `languages` may include typescript/javascript. Slash-bearing ids nest
    narrative artifacts under `docs/modules/`; `get_module_doc` follows,
    traversal blocked both sides.
  - Exit check (2026-08-11): SELENEX ingest (207 nodes, 602 module edges,
    hcl+javascript+python); all 11 JS module edges + 9 call edges and 9
    node:test mappings (reach exactly the 8 imported flow.js symbols) +
    1 pytest mapping verified by hand — 100%. The spot-check caught and
    fixed a nested-declaration call-edge leak.
  - Verified on **kbet** (`~/projects/kbet`, Max-sanctioned real Vite+React
    TS app): 20/20 edges + 10/10 mappings, 100%. Forced real fixes:
    **tsconfig zoning** (nearest tsconfig per file, one Project per zone —
    `@/*` aliases resolve; un-deferred same day), checker-crash
    resilience (per-file/stage degradation → `extraction_errors` +
    ingest WARNING), `process.exitCode` (64KB stdout truncation),
    call-initialized consts as `kind: const` symbols (zustand/axios;
    require handles excluded), `require()`/dynamic imports via
    `ts.resolveModuleName`, test `reaches_modules` unions resolved
    imports, TS-only repos no longer claim python. 226 pytest / 147 Go /
    18 node --test cases. Still deferred: per-test JS reach,
    jest-globals detection, package.json bin, cross-zone imports
    (future_additions).

- M5 (reviewed, passed): narrative pass — ADR-019 artifacts
  (`.hobbes/derived/docs/`: module docs, behavior indexes,
  `invariants.inferred.yaml`; claims `{text, pins}` validated before
  write; blob-level staleness, uncommitted edits count), ADR-020
  `hobbes narrate` (headless tool-less `claude -p`, one call per unit,
  incremental missing-or-stale, one corrective retry;
  `HOBBES_CLAUDE_BIN` override) + `hobbes docs status`, and
  `get_module_doc` on the proxy. Exit 3/3 on the dogfood repo: 37/37
  units (396 pinned claims), 10/10 sampled claims resolve, a deliberate
  edit flips exactly the right badge. 6 inferred invariants await Max's
  confirmation (inert until moved into `.hobbes/invariants/`);
  `list_invariants` still deferred to M8. Sandboxed cartographer
  sessions + system narrative parked in future_additions.

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
