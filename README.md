# Hobbes

**Hobbes** (after Calvin and Hobbes) is an agentic development environment: it
ingests a repo and produces a policy-governed environment where agents do the
line-level work and humans review at the concept level — docs, test behavior,
and architecture, not diffs.

The design lives in two documents, which are the source of truth:

- [`docs/hobbes-architecture.md`](docs/hobbes-architecture.md) — system design v1.0
- [`docs/hobbes-build-plan.md`](docs/hobbes-build-plan.md) — milestones M0–M8 and locked decisions

## Layout

| Path | What | Language |
|---|---|---|
| `go/` | Policy engine (`hobbes-policy`); later the tool proxy, session supervisor, and flight recorder daemon (M4) | Go |
| `pipeline/` | Extractors, invariant compiler, and the `hobbes` CLI | Python (uv-managed) |
| `web/` | Human surface — four-tab web UI (scaffolded at M7) | TypeScript + React |
| `docs/` | Source docs, ADRs (`docs/adr/`), and the append-only `BUILDLOG.md` | — |
| `.hobbes/` | Hobbes dogfooding itself: `policies/` and `invariants/` are versioned; `derived/` is gitignored | — |

## Running each part

### Go — policy engine

```sh
cd go
go test ./...                                  # merge-algorithm test battery
go build -o bin/hobbes-policy ./cmd/hobbes-policy
./bin/hobbes-policy resolve --dir . "git push --force origin main"
```

### Python — hobbes CLI + extraction pipeline

```sh
cd pipeline
uv sync                                        # create venv, install deps
uv run pytest                                  # extractor + CLI tests
uv run hobbes ingest                           # extract repo -> .hobbes/derived/*.json
uv run hobbes init                             # scaffold .hobbes/ in a repo
uv run hobbes policy resolve "terraform apply" # shells out to hobbes-policy
```

The Python CLI locates the Go binary via `$HOBBES_POLICY_BIN`, falling back to
`hobbes-policy` on `$PATH`.

### Web

Nothing to run yet — `web/` is scaffolded properly at M7 (Vite + React,
Cytoscape.js per locked decision D3).

## Status

M0 (skeleton + policy semantics) — see the "Current status" section of
[`CLAUDE.md`](CLAUDE.md) and [`docs/BUILDLOG.md`](docs/BUILDLOG.md).
