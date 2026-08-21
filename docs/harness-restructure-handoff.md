# Harness restructure — handoff for a fresh session

**Written 2026-08-21, end of a deep session.** The first live 7B runs
are done being *shaken out*: getting the benchmark harness to produce a
candidate patch at all took **six** fixes (all ADR-058, all committed,
797 pytest / Go green). Running it then exposed the **structural**
problem the owner named — the harness spawns a session for **every**
partition unit, and **~half of them are spurious** (no real work),
which is most of its per-instance weight. **The owner stopped the run
here: we have gained enough to restructure, not to keep paying for the
current shape.** This doc is the whole picture so a fresh context can
pick up the restructure and start a clean run.

## What the current run measured (efficiency, not H1)

**No solve-rate verdicts were gathered** — the evaluator runs at the
end of a full pass, and we stopped early. What we have is harness
*mechanics and efficiency*, which is what justified stopping:

- `astropy-13398` harness arm: outcome `patch`, **6.1 min**, 6/10
  units productive.
- `astropy-13579` harness arm (in progress when stopped): **2/9** units
  productive; the other seven stalled with `no progress` after the
  discipline caught them.
- Across sessions seen: **8/17 units ever edited.** The rest were
  spurious — interiors the proposal never touches, spawned by the
  partition (lexical seeds, C-36 + co-change merging), stopped by the
  new discipline but still costing a session spawn + round-trips each.
- The strict pipeline roughly **halved** the heavy-repo harness wall
  time (13.8 → 6.1 min on `astropy-13398`) by refusing repeated calls
  and stopping stalls — but bounding waste is not removing it.

Partial run archived at `~/.hobbes/bench/verified-complex-7b.strict-partial`
(and `.prefix-runs`, `.stopped-1` are earlier aborted shapes).

## The six harness fixes already in the tree (keep these)

All ADR-058, committed `4ee079a` / `bbb9173` / `e21a759` / `e53c211`:

1. **Environment binding** — both arms run in the instance's own
   swebench image, worktree bound by `PYTHONPATH=/work` + copied build
   artifacts (C-43); every session clone gets a git identity.
2. **Unit cap** — `--max-units` (C-44), after a 210-unit astropy plan.
3. **Brief as a file + brief limit** — `--task-file`, `--brief-limit`
   (C-45); a 488 KB brief broke the argv limit.
4. **Window fit** — the loop shrinks `max_tokens` / elides oldest tool
   results / clips results (C-46); a big read used to be a fatal 400.
5. **Commit-on-exit** — `hobbes-session --commit-on-exit` commits edits
   the agent left uncommitted (`.hobbes/` excluded); the harvest takes
   only commits.
6. **Pipeline discipline** — the loop refuses an identical read-only
   call (`repeats_refused`), nudges at `--nudge-after`, and stops a
   stall at `--stall-after` (a 55-call loop stops at turn 9). It
   disciplines *how* the model works, never *what* it writes.

## The restructure — the fresh session's actual job

**Primary: task-tailored unit selection.** Today `hobbes run` spawns a
session per unit in contract order. Change it to spawn a **stream of
*selected* units — the ones the change reaches — with `--max-units` a
ceiling, not a target.** The measured 8/17 productive ratio is the
waste this removes.

- **First cut (cheap, high-value):** do not spawn a unit whose interior
  has **no seed-reachable node** — it entered the plan only through
  co-change / partition merging, not through the impact set. The impact
  scores already exist (`derive/impact.py`); a unit whose interior
  nodes all score ~0 is context to hand a neighbour, not a session to
  run. This alone would have dropped `astropy-13579` from 9 sessions to
  ~2.
- **Open design (the owner's framing — "a stream of selected"):** what
  the selection signal is (seed reach into the interior? a nonzero cut
  the change crosses? a declared-edge touch?); whether an *unselected*
  unit still contributes standing context to its selected neighbours;
  and how selection composes with the cap (select first, then cap the
  selected). This is the execution-side twin of D1 partition quality
  (C-35). Parked detail in `docs/future_additions.md`.

**Then re-ask the bigger question (owner, 2026-08-21):** *if the
harness weight stays high even after selection, is a per-unit-session
fan-out the right execution model for a single-issue benchmark task at
all* — or is a leaner single derived-context agent the better arm to
measure? Decide from the post-selection numbers, not before. The
hypotheses (`docs/benchmark-hypotheses.md`) do not move (P11).

**Also parked (do not fold into the model's competence):** the brief
carries a *map* (module names, one-hop signatures — "internals
deliberately absent"), never source, so an implementer still reads the
files. Selection removes the spurious readers; whether the *selected*
implementer's context is rich enough to solve is then the real H1
question.

## How to start a fresh run (once the restructure lands)

Everything the previous run used still applies — see
`docs/bench-run-handoff.md` for the endpoint, secrets, image, and the
exact command. In short:

```
HOBBES_LLM_API_KEY=$(grep '^llm_key=' secrets.txt | cut -d= -f2-) \
uv run hobbes bench run verified.jsonl --secrets secrets.txt \
  --difficulty complex --runtime openai \
  --llm-base-url $(uv run pipeline/scripts/modal_vllm.py url) \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --session-bin go/bin/hobbes-session \
  --out ~/.hobbes/bench/verified-complex-7b \
  --max-turns 20 --max-units 10 --evaluate --eval-modal
```

- `--max-turns 20 --max-units 10` were the owner's cost-cut settings;
  keep or revisit after selection lands (selection should make the cap
  rarely bind).
- The run is resumable; both arms run in each instance's swebench image.
- **The decision point is still the first 10–20 completed instances'
  solve verdicts** — the thing this session never reached. Do not
  re-scope H1/H2/H3 from them (P11); interpret in
  `docs/benchmark-hypotheses.md`'s Results section, dated.

## State at handoff

- All work committed to `main` (latest at write time: the docs commit
  after this file). 797 pytest / Go green. Nothing running; 0
  containers. `verified.jsonl` (the 45-instance selection source) is at
  the repo root, gitignored.
- The findings live in ADR-058 (six findings), `docs/constraints.md`
  (C-43..C-46), `docs/future_additions.md` (unit selection with the
  measured ratio, harness re-evaluation, the nudge blind-spot now
  addressed), `docs/BUILDLOG.md` (entries thirty-third..thirty-fifth),
  and the memory `hobbes-benchmark-run.md`.
