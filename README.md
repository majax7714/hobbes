# Hobbes

**Hobbes** (based on hobbes the hilarious tiger) is an agentic development environment: it
ingests a repo and produces a policy-governed environment where agents do the
line-level work and humans review at the concept level — docs, test behavior,
and architecture, not diffs.

Joern(github.com/joernio/joern) is a code property graph software that accomplishes a lot of the things Hobbes looks to solve
though not directly related as joerns focus is on vulnerability discovery and research for static program analysis.
While hobbes looks to provide a usable environment for devs and agents. I will be releasing a comparison doc between their graphing functionalities soon

The comic (calvin and hobbes) is a wonderful masterpiece by bill waterson i recommend everyone take a read once, anyone is allowed to use hobbes
though my only request is please keep some reference to the funny tiger in your uses of hobbes.

![Calvin and Hobbes asleep on a tree branch, by Bill Watterson](hobbesncalvin.jpg)

<sub>*Calvin and Hobbes* © Bill Watterson. Used here in affection, not ownership.</sub>

---

## What it actually does

Point it at a repo and it builds a **derived layer** — a typed graph of
modules and symbols, a test↔code map, and SHA-pinned module docs — then
serves that to two audiences from one set of artifacts: a human web surface
and an MCP tool server for agents. Agents work inside rootless Podman
sandboxes where a Go policy engine sits below the model, so what an agent
may run is enforced by the OS and a proxy rather than by a prompt.

Five ideas do most of the work:

- **The repo stays canonical.** Everything in `.hobbes/derived/` is
  regenerable from a commit SHA. Nothing derived is hand-maintained.
- **One knowledge layer, two renderers.** The same artifacts serve the UI
  and the agent tools. Never docs-for-humans and context-for-agents built
  separately.
- **Provenance on every claim.** Narrative statements cite `file:line @
  SHA`; graph edges cite their producing lane and evidence.
- **Policy is enforced below the model.** Prompt-level rules are advisory;
  the sandbox and the tool proxy are load-bearing.
- **Degrade visibly, and register what you cannot know.** A failed indexer
  leaves the graph standing at lower confidence and says so; a limit that
  is *structural* gets an entry in [`docs/constraints.md`](docs/constraints.md)
  naming where a user meets it. Hobbes is unusable as a known liar and
  worse as a fake-honest one.

### Extraction is two lanes

The part most worth knowing. **tree-sitter** knows a call site *is* a call
and where it sits; **SCIP indexers** (`scip-python`, `scip-typescript`)
know what an occurrence *resolves to*. Neither is asked a question it would
have to guess at, and the two meet on file:line ranges **before any graph
exists** — so an edge can be a call *because* tree-sitter saw one and point
where it points *because* SCIP resolved it.

Every edge then carries a **tier**: `semantic` (proven), `syntactic` (lane
A's own resolution, kept as a labelled floor when the indexer could not
answer), or `dynamic` (reserved). Consumers treat tier as trust — a
violation proven on semantic edges is a finding, the same on syntactic
edges is a suspicion, and the reviewer flow says which.

Because "how much did you miss" matters as much as "what did you find",
`graph.json` also carries per-file **resolution coverage**: call sites,
how many resolved in-repo, how many to an external package, and how many
to nothing at all.

## Status

**v1 is complete — M0–M8 built and reviewed.** Policy engine, extractors,
Mermaid + graph diff, Terraform layer, sandbox and tool proxy, narrative
pass, TS/JS extraction, web surface, invariants and the reviewer flow.

**v2 (the extraction rebuild) is underway — V2.M0–V2.M3 done and
reviewed.** Two lanes over SCIP, graph schema v4 with tiers and evidence
lanes, semantic edges for Python and TypeScript, and a lane-agreement
self-test that runs clean on all three test repos. Next is V2.M4
(enrichment packs).

Current detail lives in the "Current status" section of
[`CLAUDE.md`](CLAUDE.md); the session-by-session record is
[`docs/BUILDLOG.md`](docs/BUILDLOG.md).

## The design docs

| Document | What |
|---|---|
| [`docs/hobbes-architecture-v2.md`](docs/hobbes-architecture-v2.md) | **Source of truth.** Supersedes v1's extraction layer and restates every other subsystem, so it stands alone |
| [`docs/hobbes-build-plan-v2.md`](docs/hobbes-build-plan-v2.md) | The active programme, V2.M0–V2.M7, with exit criteria |
| [`docs/hobbes-architecture.md`](docs/hobbes-architecture.md) | v1 design — accurate for the carried subsystems, historical for extraction |
| [`docs/hobbes-build-plan.md`](docs/hobbes-build-plan.md) | v1 milestones M0–M8 and the locked decisions |
| [`docs/adr/`](docs/adr/) | 32 numbered ADRs — one per decision the source docs don't make |
| [`docs/constraints.md`](docs/constraints.md) | **What Hobbes cannot tell you**, and where you find that out |
| [`docs/first-run.md`](docs/first-run.md) | Bringing Hobbes up on a new app, in the order the system is meant to be used |
| [`docs/future_additions.md`](docs/future_additions.md) | Deliberately deferred work, with the reasoning kept |

Locked decisions, not open for relitigation: Python + Go + TS split by
focus, Podman rootless for session isolation, Cytoscape.js for the
interactive graph.

## Layout

| Path | What | Language |
|---|---|---|
| `go/` | Policy engine, session tool proxy + flight recorder, sandbox launcher, and the web surface server | Go (≥1.26) |
| `pipeline/` | Extractors, the two-lane join, invariant compiler, review, and the `hobbes` CLI | Python (uv) |
| `web/` | Human surface — five-tab SPA, embedded into `hobbes-web` | TypeScript + React |
| `tsextract/` | TS/JS syntax provider (ts-morph), invoked as a subprocess | Node |
| `scip/` | Lane B — the pinned SCIP indexers and the facts helper | Node |
| `sandbox/` | Session container image and the exit-check harness | Containerfile + Python |
| `docs/` | Source docs, ADRs, the constraint register, and the append-only BUILDLOG | — |
| `.hobbes/` | Hobbes dogfooding itself: `policies/` and `invariants/` versioned, `derived/` gitignored | — |

## Getting started

Go, uv and Node are expected on `PATH`. `go.mod` needs **Go ≥ 1.26**, so a
user-local install must come before any distro Go.

```sh
# one-time
cd go   && go build -o bin/hobbes-policy  ./cmd/hobbes-policy \
        && go build -o bin/hobbes-web     ./cmd/hobbes-web \
        && go build -o bin/hobbes-session ./cmd/hobbes-session \
        && CGO_ENABLED=0 go build -o bin/hobbes-proxy ./cmd/hobbes-proxy
cd ../web && npm install && npm run build   # then rebuild hobbes-web
cd ../tsextract && npm install              # TS/JS extraction
cd ../scip      && npm install              # lane B indexers
cd ../pipeline  && uv sync
```

> `hobbes-proxy` **must be statically linked** — `hobbes-session` mounts it
> into the sandbox, where a dynamic binary fails as a confusing
> `No such file or directory` (the loader is missing, not the binary).

Then, in the repo you want to work on:

```sh
hobbes up          # init if needed, re-ingest if stale, serve, and hold
                   # until you have settled intent and invariants
```

That is the whole first run. [`docs/first-run.md`](docs/first-run.md)
walks the same path step by step and explains what each one is *for*.

### The commands

```sh
hobbes init                    # scaffold .hobbes/ in a repo
hobbes ingest                  # run the extractors -> .hobbes/derived/*.json
hobbes lanes                   # where the two extraction lanes disagree (exit 1)
hobbes render > graph.mmd      # module graph as Mermaid
hobbes diff main..HEAD         # architecture delta between two refs
hobbes narrate                 # module docs + behaviors (spends Claude quota)
hobbes docs status             # which narrative artifacts are stale
hobbes invariants check        # validate .hobbes/invariants/
hobbes invariants compile      # -> import-linter / dep-cruiser / semgrep / rego
hobbes review main..HEAD       # concept-level gate (exit 1 if it needs you)
hobbes policy resolve "cmd"    # ask the Go engine what a command may do

hobbes-web serve --repo .      # the surface, loopback only, port 7777
hobbes-session start --repo . --role implementer   # sandboxed agent session
```

`hobbes ingest && hobbes lanes && hobbes review $BASE..HEAD` is the CI
shape: extract, let the lanes check each other, then gate on the concepts.

## Tests

```sh
cd go        && go test ./...     # 188 cases across 12 packages
cd pipeline  && uv run pytest     # 429 cases
cd web       && npm test          # 52 vitest cases (the pure layer)
cd tsextract && npm test          # 20 node --test cases
cd scip      && npm test          # 12 node --test cases
```

Tests accompany the code they test in the same commit; the pytest suite
runs lane-A-only by default (`HOBBES_SCIP=0`) so it stays hermetic and
fast, which also means the degraded path is exercised on every run.

## License

MIT — see [`LICENSE`](LICENSE). Keep a reference to the tiger.
