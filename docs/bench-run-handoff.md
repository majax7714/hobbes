# Benchmark run — handoff for a fresh session (ADR-055/056/057)

**Written 2026-08-21.** The harness, the owned runtime, the small-model
ladder, and the solo policy are all built, tested, and committed. One
live instance has run end to end (both arms, 7B) and surfaced the solo
policy finding (now fixed). **The next session's job is the first real
run: the complex multi-step set on the 7B→32B ladder.** This doc is the
whole picture so a fresh context can start cold.

## Start here

1. **Read** `docs/benchmark-hypotheses.md` (the bar), ADR-055/056/057,
   and `docs/hobbes-architecture.md` §6.2. Then this file.
2. **Secrets** are in `secrets.txt` (gitignored, untracked — verified):
   `daytona_key`, `modal_key_id`, `modal_key_secret`, `llm_key`.
   `hobbes bench run --secrets secrets.txt` exports them to the env the
   tools read (Modal CLI, the loop, swebench). Never print the values.
3. **Build the binaries** (Go ≥1.26 first on PATH):
   ```
   cd go && go build -o bin/hobbes-session ./cmd/hobbes-session \
        && go build -o bin/hobbes-policy ./cmd/hobbes-policy \
        && CGO_ENABLED=0 go build -o ../sandbox/hobbes-proxy ./cmd/hobbes-proxy \
        && CGO_ENABLED=0 go build -o bin/hobbes-proxy ./cmd/hobbes-proxy
   ```
   The sandbox image already exists (`podman images | grep hobbes-session`);
   rebuild only if the proxy changed: `cd sandbox && podman build -t hobbes-session:local -f Containerfile ..`

## The endpoint (already deployed)

- **7B is live**: `https://majax7714--hobbes-llm-qwen-qwen2-5-coder-7b-instruct-serve.modal.run/v1`
  (token = `llm_key`, also in Modal secret `hobbes-llm-key`).
- Print it: `uv run pipeline/scripts/modal_vllm.py url`.
- **Deploy the 32B rung** when ready (A100-80GB, ~an hour of credit to
  watch): `MODEL=Qwen/Qwen2.5-Coder-32B-Instruct uv run pipeline/scripts/modal_vllm.py deploy`,
  then its `url` (a different subdomain — the app name embeds the model).
- Rungs are pinned in `modal_vllm.py`'s `RUNGS` table. The next rung
  above 32B is not pinned yet (Qwen3-Coder-30B-A3B is the candidate; it
  needs a vLLM with its parser — pin it in the table and note it in
  ADR-057 when taken). Cold start ~2.5 min; scales to zero when idle.
- vLLM 0.10.1.1 + **transformers <5** (pinned; 5.x breaks this vLLM).

## Fetch the focus set

```
uv run pipeline/scripts/bench_fetch.py princeton-nlp/SWE-bench_Verified test verified.jsonl
uv run hobbes bench select verified.jsonl --difficulty complex
```
That is the **45-instance complex multi-step set** (`1-4 hours` 42,
`>4 hours` 3). The bar: harnessed-7B solve rate on this set within the
95% binomial interval of pure-32B's on the same instances.

## Run it (the exact command)

```
HOBBES_LLM_API_KEY=$(grep '^llm_key=' secrets.txt | cut -d= -f2-) \
uv run hobbes bench run verified.jsonl --secrets secrets.txt \
  --difficulty complex \
  --runtime openai --llm-base-url $(uv run pipeline/scripts/modal_vllm.py url) \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --session-bin go/bin/hobbes-session --session-arg=--network=pasta \
  --out ~/.hobbes/bench/verified-complex-7b --max-turns 40 \
  --evaluate --eval-modal
```
- **Both arms run per instance.** The run is **resumable** — a record
  that exists is skipped, so re-invoking continues after an interruption.
- `--eval-modal` runs the swebench evaluator on Modal (needs the Modal
  token; no local Docker). Without it, the evaluator needs a local
  container engine (`systemctl --user enable --now podman.socket`,
  `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock`).
- The **solo policy is automatic**: each session gets
  `--box src/hobbes/bench/bench.box.policy` and `--escalation-timeout 5s`
  so tests and commits run without a human and nothing parks 30 minutes.
- For the second rung, repeat with `--model …-32B-Instruct` and the 32B
  `url`, into a new `--out`. The H1 comparison is 7B-harness vs 32B-pure;
  `hobbes bench report` over the combined records computes it if both
  models' records share one run dir, else compare two reports.

## Watch it (don't poll by hand)

Runs are long. Use a Monitor on the log, matching **both** progress and
failure signatures:
```
tail -n +1 -f run.log | grep -E --line-buffered "→|checkout|exit [0-9]|Traceback|Error|no-seed|evaluat|H1 —"
```
A harness session that stalls shows no `→` line for minutes — check
`~/.hobbes/sessions/<task>-<unit>/flight.jsonl` for `escalate` rows (the
finding below). A container list: `podman ps`.

## What is already known (don't rediscover)

- **The solo policy finding (fixed, ADR-057).** A benchmark checkout is
  a committed-only clone, so repo/role policies don't reach the session;
  before the fix, `pytest …` and `git add && commit` escalated and
  parked 30 min with no approver. The shipped box policy + short
  timeout fix it. If you see escalate-parks again, the box isn't being
  passed — check `solo_session_args` and the `--session-arg` overrides.
- **The 7B writes tool calls as text** (fenced JSON / `<tool_call>`),
  not structured calls. The loop parses and counts them
  (`text_tool_calls` in every envelope). This is expected, not a bug.
- **C-36 on real prose** (measured): dotted names (`requests.get`) don't
  seed, trailing punctuation looks code-shaped, generic words seed
  spuriously. A `no-seed` instance is a harness loss, counted, never
  dropped. If the miss rate is high on the complex set, the parked
  seed-adjustment candidates (`future_additions.md`) are the response —
  but adjust from the run's verdicts, not from a guess.
- **Cost:** the 7B set fits the free Modal credit; the 32B rung
  (A100-80GB) is the first thing that may strain it — watch
  `modal.com` usage. Every record carries GPU/token usage for the H3
  row (unobserved terms are named, never imputed).

## Where results go

- `--out` dir: `run.json` (selection + params + versions),
  `records.jsonl` (one per instance/arm/model), `patches/`, `eval/`.
- `hobbes bench report <out> [--json]` prints H1/H2/H3 with counts and
  unobserved terms; it **computes, never interprets**.
- **Write the interpretation into `docs/benchmark-hypotheses.md`'s
  Results section**, dated, naming the instance set/models/numbers —
  that is the preregistered home, and the results cannot re-scope the
  hypotheses (P11).

## Cleanup / gotchas

- Stop a stuck run: `podman ps -q | xargs -r podman kill`, then the
  background task.
- `secrets.txt` format is one `name=value` per line — keep the newline
  between entries (a run earlier concatenated two keys; fixed).
- Never `git push`; never commit `.hobbes/derived` or plans.
