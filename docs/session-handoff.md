# Session handoff — the single resume point

**Written 2026-08-22, updated the same day after the re-run and ADR-067.** This is the one authoritative resume doc for a
fresh session. The old per-phase handoffs are deleted; their history is
in `docs/BUILDLOG.md` (append-only, one entry per session). Read this,
then `docs/benchmark-hypotheses.md` (the reading rules) and the recent
BUILDLOG entries. **Nothing is running. Do not launch a benchmark
without a fresh decision from Max — the last session pushed experiments
faster than the base could stay clean.**

## Where the work is

The derivation programme's **benchmark harness** is the active work:
Hobbes run as a harness over SWE-bench Verified instances vs a
pure-model baseline, on a small open model (Qwen2.5-Coder-7B) served
from Max's Modal. The question is H1 — does derived context let a small
harnessed model match a larger pure one — but **testing has not reached
a verdict about the model**, because each run keeps surfacing harness
defects that must be fixed first. That is the current loop: run a small
set → read every failure by hand → fix what is the harness, not the
model → re-run.

**Standing rule from Max (2026-08-22):** resolve the harness's
contribution to a failure *before* attributing anything to the model.
"If in N instances we see harness weakness, that's harness tweaking, not
model re-evaluation yet." Model-rung re-evaluation (7B → **Qwen3.8 27B**, Max 2026-08-22 —
not the 32B; see the hypotheses doc's dated amendment) is on the
table but only once a run's failures are cleanly the model's.

## What the last two runs showed (both 0-solved, both informative)

The astropy pair and the 5-fresh set (django/sympy/xarray/sphinx/
scikit-learn) both scored 0 solved on both arms. But hand-reading them
(the point of small sets) showed the failures are **mostly the harness,
not hallucination**:

- The astropy "model overwrites files unread" pathology **did not
  generalise** — 1 of 10 arm runs on the 5-fresh set hallucinated a new
  file. Several arms grounded on the right file (django edited the gold
  `filters.py` with real symbols).
- On the 5-fresh set the **planner localised ~4/5**, but the harness
  recorded 2/5 because the **handoff parser dropped two correct
  answers** (xarray named both gold files on one markdown line; sympy
  named the right symbol `polylog` in prose).
- django's one grounded-but-broken edit was the **repeated-edit stack**,
  a harness edit-tool defect.

Full analysis: `docs/benchmark-hypotheses.md` Results, 2026-08-22
entries.

## What was just built (this session, on `main`)

Every commit is on `main`, tests green (843 pytest / Go), nothing pushed.

- **ADR-062** (`74ce3c1`) — the planner handoff is projected per unit
  (`planner_slice`); a unit's `## Interior` is never cut by the brief
  limit.
- **ADR-063** (`c54cade`) — implementers run in **waves over the
  contract DAG** (`--parallel`); gated on a batching endpoint
  (`--parallel auto` → vLLM detected → 4 workers, else sequential; C-51);
  integration diffs from the merge-base.
- **ADR-064** (`7d5c981`) — the owned loop writes a **transcript**
  (`<session>/transcript.jsonl`); units the planner named nothing in are
  **not spawned** (C-52); `write_file` refuses to overwrite an unread
  file. Both arms.
- **ADR-065** (`11998e5`) — `--instance-workers N` runs **instances
  concurrently** on the shared Modal endpoint; the speedup is
  endpoint-throughput-bound (~2–3× on five, one A10G), not N×.
- **ADR-066** (`a2a5504`) — the two fixes from the 5-fresh read:
  **inline handoff fields** are split (xarray's one-line handoff now
  resolves to both gold files) and a **repeated identical edit is
  refused** (django's stack). Both arms.

## The next step

**Two re-runs done on 2026-08-22, both 0/5 both arms** — read the last
two dated entries in `docs/benchmark-hypotheses.md` Results before
anything else. Each run moved the failure one layer deeper and built
the harness fix it exposed:

- `five-fresh-7b-clean` → ADR-067 (read-before-edit, anchor-stack
  refusal, cut-completion retry, any-fence parser), ADR-068 (per-call
  `calls.jsonl`, `calls_saturated`, pure-arm transcript), ADR-069
  (brief sized to the window — 35 % of `max_model_len` — filled by
  priority).
- `five-fresh-7b-adr069` → ADR-070 (`search_file` for both arms; the
  clip notice says "NOT the whole file"; the planner handoff bounded to
  ≤5 files / <15 lines). **Not yet run.**

**What to do next (Max's go needed for any launch):**

1. Re-run the same five on ADR-070. The read: did `search_file` get
   used (`calls.jsonl` / transcript)? Did anchors stop missing? Did the
   sphinx planner's handoff land? If the model ignores the search and
   still guesses, the 7B's failures are finally cleanly its own — then
   the **Qwen3.8-27B** rung (pinned, undeployed; vLLM/transformers bump
   needed — see below) is the question.
2. The brief's deeper shape (what the sections should *contain*, not
   just their size) is still Max's.

Known, not built: `bench report` roll-up of `calls_saturated` /
`prompt_tokens_max` (future_additions).

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
  --parallel auto --instance-workers 5 --evaluate
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
