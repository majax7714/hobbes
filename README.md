# Hobbes

**Hobbes** (based on hobbes the hilarious tiger) is a **multilingual,
deterministic code graphing environment**: it ingests a repo and derives a
policy-governed environment where agents do the line-level work and humans
review at the concept level — docs, test behavior, and architecture, not
diffs.

Three properties, in order of precedence. **Accurate** — the job; a graph
that is wrong is worse than no graph, because it gets believed. **Deterministic**
— parsers and indexers build the skeleton, never a model; same commit in,
same artifacts out. **Honest** — determinism only promises the same answer
twice, not a true one, so every edge carries a tier, every concession is
registered, and the limits of the third-party indexers Hobbes runs are
owned as Hobbes's own. Abstraction is the product; accuracy is the
precondition.

The graph is not the goal, though. It is the thing that makes **single-use
agents under derived, systematic context** possible — see [where this is
going](#where-this-is-going).

SCIP the code intelligence protocol is used as a semantic maper throughout hobbes- scip-code/scip

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

Six ideas do most of the work:

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
- **A provider's limits are Hobbes's limits.** Semantics come from
  third-party indexers Hobbes runs and doesn't wrap. Their blind spots land
  in the graph, so they're written down as *ours* — never disowned as the
  indexer's problem. You ran `hobbes ingest`, not `scip-python`, and a
  missing edge reads as an absent call either way.

### Extraction is two lanes

The part most worth knowing. **tree-sitter** knows a call site *is* a call
and where it sits; **SCIP indexers** (`scip-python`, `scip-typescript`,
`scip-go`, `rust-analyzer`'s native export) know what an occurrence
*resolves to*. Neither is asked a
question it would have to guess at, and the two meet on file:line ranges
**before any graph exists** — so an edge can be a call *because*
tree-sitter saw one and point where it points *because* SCIP resolved it.

Both halves are load-bearing, and that is measured rather than assumed: no
SCIP indexer populates the field that would say what a reference
syntactically *was* — `scip-python` leaves it unset for 0 of 8,575
occurrences, `scip-go` for 0 of 18,682, `rust-analyzer` for 0 of 169.
Three independent implementations, the same omission. Without the syntax
half a language gets references and no call graph at all, which is why
adding a language means an indexer **and** a grammar.

Every edge then carries a **tier**: `semantic` (proven), `syntactic` (lane
A's own resolution, kept as a labelled floor when the indexer could not
answer), or `dynamic` (reserved). Consumers treat tier as trust — a
violation proven on semantic edges is a finding, the same on syntactic
edges is a suspicion, and the reviewer flow says which.

Because "how much did you miss" matters as much as "what did you find",
`graph.json` also carries per-file **resolution coverage**: call sites,
how many resolved in-repo, how many to an external package, and how many
to nothing at all.

## Where this is going

An accurate graph of a repo is useful on its own. It is not what Hobbes is
for.

**A model's accuracy falls as its context grows and as tasks accumulate in
one session.** Everyone has watched it happen: the agent that was sharp on
the first task is confidently wrong by the fifth, still fluent, working from
a context window that is now mostly its own earlier output. The usual
answers are a bigger window and a better prompt. Both treat the symptom.

The answer Hobbes is built around is **a smaller job**. If you know a repo's
real structure, you can derive — *per task* — the context that task actually
needs and the policy that task is actually permitted, start one agent inside
both, and let it end when the task does. Context becomes something **scoped
by the architecture and regenerated**, rather than something assembled by a
prompt and accumulated until it rots. That is the difference between an
agent that has read the right twelve files and one that has been handed
everything and told to be careful.

The policy half is what makes it safe to actually do this, and it is why the
sandbox sits below the model instead of inside it. **A rule in a prompt is a
request.** A command outside the policy is not refused — it is *absent*: no
binary on the path, no mount to write through, no route to the network. In
the project's own words: *if an agent cannot execute a command in a space
where it literally cannot, then it literally cannot.* Enforcement that
depends on the model's cooperation is not enforcement, and an agent that
cannot be talked out of its constraints does not need to be trusted.

Three of the four pieces exist today:

| Piece | State |
|---|---|
| A graph accurate enough to derive context *from* | built — this is what v2's extraction layer is for |
| Invariants that make the result checkable | built (`hobbes review`, the reviewer role) |
| Enforcement that is real rather than advisory | built (rootless Podman + the Go policy engine and proxy) |
| **The derivation itself** — per-task context and policy generated *from* the architecture | **not built.** Not a milestone yet |

That last row is the honest one, and it stays in the README rather than
being implied away. Nothing in the current design should make it harder to
reach, and that is the test any new work here has to pass — but it has not
been started, and Hobbes is not it yet.

## Status

**v1 is complete — M0–M8 built and reviewed.** Policy engine, extractors,
Mermaid + graph diff, Terraform layer, sandbox and tool proxy, narrative
pass, TS/JS extraction, web surface, invariants and the reviewer flow.

**v2 (the extraction rebuild) is complete — V2.M0–V2.M7 all built,
reviewed, and passed (the last on 2026-08-16).** Two lanes over SCIP,
graph schema v4 with tiers and evidence lanes, semantic edges for
**Python, TypeScript/JavaScript, Go, and Rust**, framework knowledge
isolated into removable enrichment packs, a unified tier-aware invariant
checker, and a lane-agreement self-test — on this repo it compares 3,085
call sites across every lane with zero disagreements.

The programme ended the way it was designed to: **V2.M7 added Rust with
zero new lines in the graph builder, the join, or the schema** — one
grammar walk, one indexer entry, and the checklist did the rest. That was
the claim ("languages are configuration, not integrations"), and it is
now proven twice, on Go and on a language nobody planned for. Along the
way Hobbes learned to see **its own Go** (closing the dogfood loop) and
its own Rust fixture — six languages in the graph it builds of itself.

What v2 *cannot* tell you is a first-class artifact too:
[`docs/constraints.md`](docs/constraints.md) holds thirty-seven
registered constraints, seven of them since lifted, each naming where a
user meets the limit — and
[`docs/extraction-evidence.md`](docs/extraction-evidence.md) is the
standing record of every repo the extraction layer has been tested
against, with its measured numbers and what was and was not verified. One worth knowing before you ingest strangers' code:
**indexing a Rust repo executes its `build.rs` and proc macros** (C-29 —
disclosed on stderr at every rust ingest; ingest an untrusted Rust repo
only if you would also build it).

Current detail lives in the "Current status" section of
[`CLAUDE.md`](CLAUDE.md); the session-by-session record is
[`docs/BUILDLOG.md`](docs/BUILDLOG.md).

## The design docs

| Document | What |
|---|---|
| [`docs/hobbes-architecture.md`](docs/hobbes-architecture.md) | **Source of truth — the running architecture.** Describes Hobbes as it is now; amended in place, in the same commit as the code that moves it |
| [`docs/hobbes-build-plan-v2.md`](docs/hobbes-build-plan-v2.md) | The v2 programme, V2.M0–V2.M7, complete — kept with its exit criteria and outcomes |
| [`docs/hobbes-architecture-v1.md`](docs/hobbes-architecture-v1.md) | The frozen v1 design — history, kept for the reasoning behind the carried subsystems |
| [`docs/hobbes-build-plan.md`](docs/hobbes-build-plan.md) | v1 milestones M0–M8 and the locked decisions |
| [`docs/adr/`](docs/adr/) | 42 numbered ADRs — one per decision the running architecture doesn't make |
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

# per-language, only if your repos need them:
go install github.com/scip-code/scip-go/cmd/scip-go@v0.2.7   # Go semantics
rustup component add rust-analyzer                           # Rust semantics
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
cd go        && go test ./...     # 245 cases across 12 packages
cd pipeline  && uv run pytest     # 566 cases
cd web       && npm test          # 52 vitest cases (the pure layer)
cd tsextract && npm test          # 27 node --test cases
cd scip      && npm test          # 24 node --test cases
```

Tests accompany the code they test in the same commit; the pytest suite
runs lane-A-only by default (`HOBBES_SCIP=0`) so it stays hermetic and
fast, which also means the degraded path is exercised on every run.

## License

MIT — see [`LICENSE`](LICENSE). Keep a reference to the beloved goat HOBBES!!.
