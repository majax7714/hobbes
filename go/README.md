# go/ — policy engine, tool proxy, flight recorder

Go module `github.com/majax7714/hobbes/go`. Standard layout: `cmd/` for
binaries, `internal/` for packages.

- `internal/policy/` — the single implementation of Hobbes policy semantics:
  strict-YAML policy files (ADR-001), the box → repo → folder chain loader
  (with the built-in tfstate deny floor, ADR-011), and the resolution
  algorithm (deny overrides allow, most-specific-wins shadowing, escalate
  tier — ADR-002).
- `internal/recorder/` — the flight recorder: append-only JSONL audit log,
  one file per session, one line per proxied call, fsynced per event
  (architecture §9, ADR-015/016).
- `internal/escalation/` — the escalation queue (ADR-016): parked commands
  as atomic JSON records under
  `~/.hobbes/sessions/<session>/escalations/`, resolved by the CLI,
  expiring to deny.
- `internal/proxy/` — the M4 tool proxy: the MCP server standing between an
  agent session and the machine. One tool, `exec`; every call resolved
  through `internal/policy` and logged through `internal/recorder`.
  Escalated commands park (blocking the call, with MCP progress
  notifications) and run in place once approved.
- `cmd/hobbes-policy/` — CLI front-end. `hobbes-policy resolve` prints a JSON
  resolution and encodes the decision in its exit code
  (0 allow / 10 deny / 20 escalate — ADR-003). The Python `hobbes` CLI shells
  out to it.
- `cmd/hobbes-proxy/` — the per-session daemon (ADR-014): `hobbes-proxy
  serve --repo DIR --role ROLE` speaks MCP over stdio and logs to
  `~/.hobbes/sessions/<session>/flight.jsonl`. The M4 session wrapper lists
  it in the sandboxed Claude Code's MCP config. `hobbes-proxy escalations
  [list | approve <id> | deny <id>]` is the human side of the queue.

```sh
go test ./...
go build -o bin/hobbes-policy ./cmd/hobbes-policy
go build -o bin/hobbes-proxy  ./cmd/hobbes-proxy
./bin/hobbes-policy resolve --dir . "git push --force origin main"
./bin/hobbes-proxy serve --repo . --role implementer   # MCP on stdio
./bin/hobbes-proxy escalations                          # pending queue
./bin/hobbes-proxy escalations approve E-...            # parked cmd runs
```
