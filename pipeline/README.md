# pipeline/ — Python package `hobbes`

The `hobbes` CLI and the deterministic extraction pipeline (M1); the
invariant compiler joins at M8. uv-managed, src layout (ADR-004). Runtime
dependencies: `tree-sitter` + `tree-sitter-python` only (ADR-005).

Surface:

- `hobbes ingest [--repo PATH]` — runs the extractors and writes the three
  SHA-stamped artifacts (ADR-006) to `.hobbes/derived/`: `graph.json`
  (module nodes + symbol layer, `imports`/`env-read`/`calls` typed edges),
  `tests.json` (pytest inventory with static test→symbol reach), and
  `interfaces.json` (FastAPI/Flask routes, CLI entry points).
- `hobbes init [--repo PATH]` — scaffolds `.hobbes/` (policies/, invariants/,
  starter repo.policy, gitignore entries). Idempotent.
- `hobbes policy resolve "<command>"` — passthrough to the Go `hobbes-policy`
  binary: prints its JSON resolution, propagates its decision-coded exit
  (0 allow / 10 deny / 20 escalate, ADR-003). Found via
  `$HOBBES_POLICY_BIN`, else `$PATH`.
- `hobbes diff` — stub until M2.

Layout: `src/hobbes/cli.py` (argparse front-end), `src/hobbes/policy.py`
(policy shell-out), `src/hobbes/extract/` (discover → pysource → graph /
interfaces / testmap → emit; resolution rules in ADR-007).

```sh
uv sync         # venv + dev deps
uv run pytest   # hermetic: fixture repo under tests/fixtures/miniapp
uv run hobbes ingest --repo /path/to/repo
```
