# go/ — policy engine and (later) the Hobbes daemon

Go module `github.com/majax7714/hobbes/go`. Standard layout: `cmd/` for
binaries, `internal/` for packages.

- `internal/policy/` — the single implementation of Hobbes policy semantics:
  strict-YAML policy files (ADR-001), the box → repo → folder chain loader,
  and the resolution algorithm (deny overrides allow, most-specific-wins
  shadowing, escalate tier — ADR-002).
- `cmd/hobbes-policy/` — CLI front-end. `hobbes-policy resolve` prints a JSON
  resolution and encodes the decision in its exit code
  (0 allow / 10 deny / 20 escalate — ADR-003). The Python `hobbes` CLI shells
  out to it.

The M4 tool proxy, session supervisor, and flight recorder will live in this
module and import `internal/policy` directly, so there is exactly one
deny-overrides-allow in the system.

```sh
go test ./...
go build -o bin/hobbes-policy ./cmd/hobbes-policy
./bin/hobbes-policy resolve --dir . "git push --force origin main"
```
