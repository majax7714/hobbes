# pipeline/ — Python package `hobbes`

The `hobbes` CLI, and — from M1 on — the deterministic extractors and (M8)
the invariant compiler. uv-managed, src layout, zero runtime dependencies
(ADR-004).

M0 surface:

- `hobbes init` / `hobbes ingest` / `hobbes diff` — stubs; they name the
  milestone that delivers them (M1, M1, M2) and exit non-zero.
- `hobbes policy resolve "<command>"` — working passthrough to the Go
  `hobbes-policy` binary: prints its JSON resolution, propagates its
  decision-coded exit (0 allow / 10 deny / 20 escalate, ADR-003). The binary
  is found via `$HOBBES_POLICY_BIN`, else `hobbes-policy` on `$PATH`.

```sh
uv sync         # venv + dev deps
uv run pytest   # hermetic — fakes the Go binary, no Go toolchain needed
uv run hobbes policy resolve "git push --force origin main"
```
