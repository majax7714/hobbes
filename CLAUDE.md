# CLAUDE.md — working notes for Claude Code sessions

## What this project is

Hobbes: an agentic development environment that ingests a repo and produces a
policy-governed environment where agents do line-level work and humans review
at the concept level.

**Source of truth:** `docs/hobbes-architecture-v2.md` — read it fully before
writing code. It supersedes the v1 extraction layer and restates every other
subsystem, so it is self-contained. `docs/hobbes-architecture.md` and
`docs/hobbes-build-plan.md` remain as the v1 record: still accurate for the
carried subsystems, historical for extraction. Deviations from v2 need an ADR
*and* a patch to that document in the same commit.

Locked decisions (not open for relitigation): **D1** Python + Go + TS split by
focus, **D2** Podman rootless for session isolation, **D3** Cytoscape.js for
the interactive graph.

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
  get_module_doc/list_invariants over `.hobbes/derived/`, ADR-017/019/024).
  `cmd/hobbes-session/` + `internal/sandbox/` launch a session in rootless
  Podman (ADR-018); the **reviewer** role mounts the worktree ro and drops
  Edit/Write/exec, and every role gets `.hobbes/derived/` mounted ro so the
  knowledge tools have something to read (M8).
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
  joins the tsextract helper's facts (M6, ADR-021). M8 adds
  `src/hobbes/invariants/` (ADR-024: record loading/validation,
  graph-computed verdicts, and the four CI-config emitters) and
  `src/hobbes/review.py` (ADR-025: `hobbes review`).
  Test fixture repos: `tests/fixtures/miniapp/`
  (Python) and `tests/fixtures/minits/` (TS/JS), both excluded from
  pytest collection via `norecursedirs`.
- `tsextract/` — Node helper (ADR-021): ts-morph walk emitting facts
  JSON for the Python join; own `node --test` suite (`npm test`);
  `node_modules/` gitignored, lockfile committed. Only external dep:
  ts-morph.
- `scip/` — **v2 lane B** (ADR-027): the SCIP indexers, pinned
  (`scip-python`, `scip-typescript`), plus `analyze.mjs` / `compare.mjs`
  — V2.M0 spike tooling kept because they are the reproducible evidence
  for ADR-027's numbers, and `compare.mjs` prototypes §3.4's
  lane-agreement report. No tests until the real helper lands at V2.M2.
  One-time: `cd scip && npm install`.
- `web/` — the M7 surface (Vite + React + TS, Cytoscape.js per D3).
  `src/lib/` holds the pure layer and all the vitest cases (graph model
  and focus neighborhood, §4.2 index joins, patch parsing); `src/tabs/`
  is one component per tab. `npm run build` typechecks, then bundles
  into the Go embed dir — **rebuild `hobbes-web` after**, or it serves
  the previous bundle. `npm run dev` proxies `/api` to a running server.
- `docs/` — the two source docs, `docs/adr/` (numbered ADRs),
  `docs/constraints.md` (the P8 register of what Hobbes cannot tell you,
  ADR-030), `docs/BUILDLOG.md` (append-only session log), `docs/first-run.md`
  (bringing Hobbes up on a new app, in the order the system is meant to
  be used), and `docs/m9-application-mode.md` (a *proposal*, not a
  decision — see Current status).
- `.hobbes/` — dogfooding: `policies/` + `invariants/` versioned, `derived/`
  gitignored. `invariants/` holds six confirmed records (ADR-024);
  `derived/compiled/` is where `hobbes invariants compile` writes CI
  configs.

## Build & test

Go, uv, and Node are user-local installs: `~/.local/go/bin` and
`~/.local/bin` (ensure both are on `PATH`). `go.mod` requires **Go
≥ 1.26**, and a distro Go in `/usr/bin` is older — `~/.local/go/bin`
must come *first*, or `go build` fails on the toolchain line rather
than on anything real. One-time: `cd tsextract && npm install` (TS
extraction) and `cd web && npm install` (the surface).

```sh
# Go
cd go
go test ./...
go build -o bin/hobbes-policy ./cmd/hobbes-policy
go build -o bin/hobbes-web    ./cmd/hobbes-web   # after `cd web && npm run build`
go build -o bin/hobbes-session ./cmd/hobbes-session
# The proxy must be STATIC: hobbes-session mounts the binary sitting next
# to it into the sandbox, and a dynamically-linked one fails there as a
# confusing "No such file or directory" (the loader is missing, not the
# binary). Static works host-side too.
CGO_ENABLED=0 go build -o bin/hobbes-proxy ./cmd/hobbes-proxy
CGO_ENABLED=0 go build -o ../sandbox/hobbes-proxy ./cmd/hobbes-proxy  # image build

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

# Bring-up (ADR-026) — one command, blocks until decisions are made
uv run hobbes up                              # or --no-serve to just report

# Invariants and review (M8)
uv run hobbes invariants check                # validate .hobbes/invariants/
uv run hobbes invariants compile              # → .hobbes/derived/compiled/
uv run hobbes review main..my-branch          # exits 1 if it needs attention
uv run hobbes review main..my-branch --soft   # + reviewer sessions (quota)
```

## Conventions

- **Milestone order is strict.** Never start milestone N+1 in a session where
  milestone N's exit criteria haven't been met *and reviewed by Max*.
- Tests accompany the code they test **in the same commit**.
- Conventional commits, scoped: `feat(policy): ...`, `fix(cli): ...`,
  `test/docs/chore`.
- One short ADR (`docs/adr/NNN-title.md`) for every design decision the two
  source docs don't already make. Number sequentially.
- **Every decision that concedes information gets a `C-n` entry in
  `docs/constraints.md`, in the same commit** (P8, ADR-030). An entry is
  not done when written — it carries a *surfacing status* naming where a
  user meets the limit; `unsurfaced` means documented only, and is debt.
  Hobbes is unusable as a known liar and worse as a fake-honest one.
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
- **Never `git push`.** Sessions commit to a branch; Max publishes after
  review. The repo policy denies `git push*` outright rather than
  escalating it — an escalation is for commands a human might reasonably
  approve. This also applies when testing the escalation queue: pick
  read-only commands, because an *approved* escalation really runs.

## Current status

**v1 is complete — M0–M8 all built and reviewed. v2 is underway.**

**Active: the v2 extraction architecture.** Source of truth is
`docs/hobbes-architecture-v2.md`; the file-level plan with exit criteria
is `docs/hobbes-build-plan-v2.md` (approved 2026-08-14, all six
deviations folded into §7). **V2.M0 (ADR-027), V2.M1 (ADR-028), V2.M2\* (ADR-029) done. V2.M3 is
next.**

Artifacts are at **schema v4** (ADR-028): every edge carries a `tier`
(`semantic`|`syntactic`|`dynamic`) and every evidence entry a `lane`.
v4 is *additive* over v3, so consumers declare a version **range** —
`hobbes/artifacts.py`, `go/internal/derived`, and `api.ts` are the three
gates, and they refuse rather than half-read. Lane A emits everything as
`syntactic`/`tree-sitter`; nothing claims `semantic` until lane B lands.

Lane B (ADR-029) runs for **Python only**. Two providers, never one:
**tree-sitter knows a call site is a call**, **SCIP knows what it resolves
to**, and they meet in the evidence IR (`extract/evidence.py`) before any
graph exists. SCIP alone cannot answer "is this a call" — it populates
`syntax_kind` for none of its occurrences — so lane A keeps call-site
*detection* and loses only call *resolution*. A resolution no call site
claimed becomes a `uses` edge (not `references`, which ADR-010's Terraform
layer already owns).

Lane B never writes to the target repo: it stages a copy under
`~/.hobbes/cache` (`extract/staging.py`, ADR-027's seven-clause contract).
`HOBBES_SCIP=0` disables it, and the pytest suite sets that by default —
tests marked `lane_b` opt in.

**M2 exits with an asterisk (Max, 2026-08-15).** `scip-typescript` was in
M2's scope and is not wired, so a TS repo ingests entirely at syntactic
tier. The work folded into **M3**, which already opens `tssource.py` to
strip its symbol layer — the gap is the TS syntax provider: `tsextract`
must emit call sites with line, column and terminal name into the evidence
IR, as `pysource` now does. **M3's exit discharges the asterisk**, so M3
does not pass until kbet produces hand-verified semantic edges.

Three things ADR-027 settled that any v2 session needs to know:
`--project-version` is always pinned (its default is the git revision,
so ids would otherwise change every commit); indexer config is **per
repo**, not just per language, and a src-layout Python repo silently
loses every test→source edge without it; and only ~14% of SCIP
definitions are graph-worthy, so the descriptor filter comes before
anything else.

*(Paused 2026-08-13 for Max's move; resumed 2026-08-14 on v2.)*

**Two things still wait on Max, neither blocking v2:**

1. **ADR-026** (two decision surfaces + `hobbes up`) — built, verified
   end to end, **still pending his review**. v2 does not touch the
   decision surfaces, so the debt carries rather than conflicts.
2. **M9, "Hobbes as an application"** — his design ask of 2026-08-13,
   assessed and written up in `docs/m9-application-mode.md`. It is a
   **proposal with three open questions**, not an ADR and not started.
   Do not begin implementing it; it needs his answers on the workspace
   model, how a folder gets opened, and scope. Note it would cross
   ADR-022's "the surface never runs the pipeline" line and would want
   a launch token *before* the feature, not after. M9 sits *above* the
   extraction layer, so it and v2 do not conflict — but only one is
   active at a time, and v2 is.

**Box note (2026-08-13):** `go.mod` needs Go ≥ 1.26 and Fedora ships
1.25, so `~/.local/go/bin` must precede `/usr/bin` on `PATH` — fixed in
`~/.bashrc`. `hobbes` and the four Go binaries are symlinked into
`~/.local/bin`, so `hobbes up` works from any repo; they point at
`go/bin`, so a rebuild needs no relinking.

- Exactly two things need a human: **intent** (the repo policy) and
  **invariants**. Everything else is a natural part of the mechanism.
- `hobbes up` = init if absent → re-ingest when the artifacts' stamped
  SHA is not HEAD → serve → **block until the decision queue is empty**.
  It **never narrates**: quota is offered in the UI, never spent by a
  script someone ran to get started.
- Intent is `repo.policy` edited in the UI (not a layer compiling down
  to it), with the diff shown before writing. An unconfirmed policy is a
  pending decision, not a silent default.
- Invariants are approve / deny / edit (keys `a`/`d`/`e`). Approving
  writes a real record into `.hobbes/invariants/`.
- **Decisions key on a content hash of (statement, scope), never the
  id** — `INF-n` is positional, so an id-keyed approval would bless
  different text after the next narration. The hash lives in Go (writer)
  and Python (reader); `pipeline/tests/fixtures/decision-keys.json` pins
  both. Denials persist too.
- Amends ADR-019 (promotion is still a file, different trigger) and
  ADR-022 (the surface now writes three things, each a readable file).
- Known limitation: decisions are untracked (ADR-012), so they do not
  survive a fresh clone — see `future_additions.md`.

- M8 (reviewed, passed): reviewer flow + invariant compiler v0.

  - ADR-024: invariant records live one-per-file in `.hobbes/invariants/`.
    `statement` is the prose; **`compile.rule` is structured**, because a
    prose rule cannot compile without an LLM and enforcement must stay
    deterministic (sequencing rule 1). Three rule kinds
    (forbidden-import, pattern-absent, resource-attribute) plus `soft`.
    Only `confirmed` records compile or receive verdicts; `retired` stays
    as history; an `inferred` record here warns and stays inert.
    Compilation is text generation — **no target toolchain needed**, and
    none is installed here.
  - ADR-025: `hobbes review <base>..<head>` computes verdicts **at both
    ends**, so a regression this change introduced is distinguishable from
    breakage it inherited. Exits 1 on regressions, lost guards, or
    unguarded new code. Spends no quota unless `--soft`.
  - **Six confirmed invariants** (I-1..I-6), promoted from the M5 inferred
    set. I-3 was rewritten during promotion: the inferred wording claimed
    pushes escalate, which the push-deny made false.
  - **`git push` is denied**, not escalated (see Conventions).
  - The **reviewer role** is now enforced at the mount tier: worktree ro,
    no Edit/Write/exec, and `.hobbes/derived/` mounted ro for every role
    so the knowledge tools have something to read.
  - Exit check (2026-08-11): branch `m8-exit-check` added a plausible
    feature that duplicated the parser; review reported I-4 REGRESSED with
    both import sites cited and exited 1, and the fix flipped it to PASS.
    Replay with `hobbes review ace9a08..cdbc085` (exit 1) and
    `ace9a08..7d52f2e` (exit 0). A real rootless-Podman reviewer session
    scored 5/5. 205 Go / 297 pytest / 38 vitest / 18 node.

- M7 (reviewed, passed): the web surface — ADR-022 `hobbes-web` (a Go
  daemon serving a loopback-only JSON API plus the embedded SPA) and
  ADR-023 graph conventions. Exit check on the dogfood repo and kbet,
  including escalation approve/deny in the browser against commands
  really parked by `hobbes-proxy`.

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
