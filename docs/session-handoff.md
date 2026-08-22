# Session handoff — the single resume point

**Written 2026-08-22, updated after the first 27B run and ADR-075.** This is the one authoritative resume doc for a
fresh session. The old per-phase handoffs are deleted; their history is
in `docs/BUILDLOG.md` (append-only, one entry per session). Read this,
then `docs/benchmark-hypotheses.md` (the reading rules) and the recent
BUILDLOG entries. **Nothing is running. Do not launch a benchmark
without a fresh decision from Max — the last session pushed experiments
faster than the base could stay clean.**

## LATEST (2026-08-22): 27B deployed, its first run void, the harness revised — ready for a scoped re-run

**The 27B is deployed and the loop can drive it (ADR-074).** Modal app
`hobbes-llm-qwen-qwen3-8-27b`, A100-80GB, vLLM 0.27.1, window 131,072,
`qwen3` reasoning + `qwen3_coder` tool parsers, text-only. The owned loop
takes `--temperature/--top-p/--reasoning-effort/--thinking` and keeps
reasoning on the transcript; `bench.Runtime` carries sampling and the loop
knobs to both arms via `hobbes-session --loop-arg`. Deploy pitfalls (all
fixed in `modal_vllm.py`): bake `MODEL` into the image env;
`VLLM_USE_FLASHINFER_SAMPLER=0` (JIT wants nvcc); warm with a short-timeout
`/models` loop before a run (~10 min cold start; Modal answers a request
that outlives it with a `303` poll redirect).

### The harness revisions (do these before going further — mostly DONE)

The first 27B run (`five-fresh-27b`) was **void as a model verdict**: the
harness arm (20%) lost to pure (40%) because the proxy strangled it, not
because the model was worse. Two revisions came out of reading it:

1. **ADR-075 (DONE, committed) — compound-command policy.** The engine
   matched a whole command string against anchored globs, so a capable
   model's `cd /work && pytest`, chained git, and env-prefixed commands
   matched no box allow rule and expire-denied (104 of 253 exec calls).
   Now `Chain.ResolveCommand` splits on top-level `&& || ; |`, strips
   `cd`/env prefixes, and resolves each segment most-restrictive-wins
   (deny > escalate > allow); box policy broadened with the read-only pipe
   filters. C-54. **This is the fix that should let the harness arm
   execute.**
2. **ADR-076 (DONE, committed) — loop-discipline knobs per run.**
   `bench run --stall-after/--nudge-after`, both arms; loop defaults (6/3,
   cut for the 7B) unchanged when unset. A thinking model investigates
   before its first edit — sphinx pure was stopped mid-investigation at 6
   dry turns. Raise these on a 27B run. The pure wall is `--timeout`
   (sklearn pure hit 3600 s doing real work) — raise it too.

**Known, still open (not blocking the re-run):** a minority of exec calls
returned `fork/exec /bin/sh: no such file or directory` — a separate
secondary defect, unread; watch whether ADR-075 alone clears it.

### The next round — scoped (Max, 2026-08-22)

Run **only the four harness failures** — `django`, `sympy`, `sklearn`,
`sphinx` — **plus `xarray` again as the control** (verify the one harness
solve still holds). Re-running the passing pair for its own sake is lower
value; the point is the harness fix applied over the failures. Same five
ids as before, then, but the framing is four-targets-plus-control.

**Preregistered expectation (Max):** with the harness able to execute,
**Hobbes should now beat pure on this set**, even though it is mostly
failures — the findings so far (planner localises 80% from derived
context; the harness losses were the proxy, not the model) point that way.
Recorded in `docs/benchmark-hypotheses.md` before the run (P11).

**Per-instance targets to watch:**
- **sympy** — the real model wall: both arms localised and edited gold but
  under-implemented (only `polylog(2,1/2)`, not the full closed-form table
  the hidden `test_polylog_values` needs; harness used the wrong method AND
  was blind). Watch whether the harness arm, now able to run its guarding
  tests, self-corrects the method and generalises.
- **sklearn** — localisation miss (gold `base.py`/`_base.py` ranked 44/71;
  planner named `_set_output.py`). May still miss; a planner-map or
  partition question if it does.
- **sphinx** — planner localised (1/2); implementers were strangled by
  C-54. Should improve most directly from ADR-075.
- **django** — harness failed 2 F2P (pure passed); should be within reach.
- **xarray** — control; expect it to hold.

## How to run the set (unchanged except the two new flags)

The evaluator runs **locally over the rootless-podman Docker socket**
(swebench 5.0.2 `--modal` is broken upstream, C-50). Ensure the socket:
`systemctl --user start podman.socket`. Do **not** pass `--eval-modal`.
7B endpoint URL from `uv run pipeline/scripts/modal_vllm.py url`;
secrets in `secrets.txt` (`llm_key`, `modal_key_id`, `modal_key_secret`);
`verified.jsonl` at the repo root (gitignored). Rebuild `hobbes-session`
after any Go change.

```sh
cd /home/mmarrujo/hobbes/pipeline
export PATH=$HOME/.local/go/bin:$HOME/.local/bin:$PATH
export MODAL_TOKEN_ID=$(grep '^modal_key_id=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-)
export MODAL_TOKEN_SECRET=$(grep '^modal_key_secret=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-)
URL=$(uv run scripts/modal_vllm.py url)
HOBBES_LLM_API_KEY=$(grep '^llm_key=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-) \
uv run hobbes bench run /home/mmarrujo/hobbes/verified.jsonl --secrets /home/mmarrujo/hobbes/secrets.txt \
  --id django__django-11400 --id sympy__sympy-13852 --id pydata__xarray-3993 \
  --id sphinx-doc__sphinx-8548 --id scikit-learn__scikit-learn-25102 \
  --arm both --runtime openai --llm-base-url "$URL" --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --session-bin /home/mmarrujo/hobbes/go/bin/hobbes-session \
  --out ~/.hobbes/bench/five-fresh-7b-clean \
  --stages plan,implement,verify --max-units 10 --max-turns 40 --max-tokens 1536 \
  --parallel auto --instance-workers 5 --evaluate --human-first spawn
```

## Inspecting a run (what to read, in order)

1. `~/.hobbes/bench/<name>/records.jsonl` — per (instance, arm):
   `outcome`, `resolved`, `patch_files`, and for the harness
   `detail.planner` (hit/hits/gold vs gold, C-49), `detail.seed_source`,
   `detail.run.integration` (merged/dropped/empty),
   `detail.run.stage_wall` + `parallel`.
2. Per-session **transcript** (new, ADR-064):
   `<sessions>/<instance-id>/<task>-<unit>/transcript.jsonl` — the full
   message list, so a trace no longer stops at the tool-call line. The
   `session.log` first line is the envelope (turns, tokens,
   repeats_refused, edited).
3. `hobbes bench report ~/.hobbes/bench/<name>` — H1/H2/H3 + planner hit
   split by seed_source. Computes, never interprets.
4. Gold files per instance: the `patch` field in `verified.jsonl`.

Read a failing instance the way the 5-fresh set was read: gold files →
what each arm touched → planner handoff (did it localise?) → the unit
transcript (did the implementer ground or hallucinate?). Classify each
failure as **planner-localisation**, **implementer-execution**, or
**hallucination** before drawing any model conclusion.

## Housekeeping

- Commit to `main`; never `git push` (Max publishes). One ADR per design
  decision; one BUILDLOG entry per session; every concession a `C-n` in
  `docs/constraints.md`.
- `docs/BUILDLOG.md` is the history — update it in the same commit as the
  work, and keep this doc as the single forward-looking resume point
  (rewrite it, don't spawn a new handoff file).
