# Handoff — the harness restructure through phase 4, and what stands before the 45-set

**Written 2026-08-22.** This is the single resume point for a fresh
session. The harness restructure (`docs/harness-restructure-plan.md`)
is built through **phase 4**; the first full end-to-end verdicts exist;
the evaluator is unblocked. **One design fix is decided-but-not-built
and should land before the 45-set** (below). Read this, then
`docs/harness-restructure-plan.md` and `docs/benchmark-hypotheses.md`.

## State in one paragraph

Phase 3 (the harness adapter) and phase 4 (probe → full-stage run on
two astropy instances) are done and committed to `main`. The 7B
**planner hit the gold file on both instances (2/2)**; both arms scored
**0/2 solved** — the planner finds the place, the 7B *implementer* is
the wall. Getting there fixed eleven things (list below), the last and
most important being **write-scope enforcement at the cut** (ADR-061).
The **role-specific implementer context** fix is confirmed necessary
and **not yet built** — it is the recommended next step before spending
45-set compute. 827 pytest / Go green. Nothing running; monitors all
stopped.

## This session's commits (on `main`, oldest first)

```
d89307d phase 3 — the harness adapter over the staged run (ADR-059 amended)
5f137c2 ADR-060 — read-only roles mount the worktree as an overlay, not ro
f982be8 read the handoff shape a 7B writes; resolve dotted symbol names
9c66c11 planner seeds replace the lexical layer; the planner probe's results
40bc4b1 four findings from the first full-stage run (verifier tests, stale dirs, refused-repeat stall, --max-turns)
a646760 speed: cap completions, refuse no-op exec repeats, allow read-only pip
f76c2f6 resolve a dataset *file* to an absolute path for the evaluator
81a3c09 unblock the evaluator (local podman socket) — first end-to-end verdicts
cb86bbb ADR-061 — enforce a unit's write scope at the cut
```

New ADRs: **059** (amended, phase 3), **060** (overlay mount), **061**
(write-scope at the cut). New constraints: **C-47..C-50** and C-38
flipped measured→enforced. Results recorded in
`docs/benchmark-hypotheses.md` (2026-08-22 entries).

## THE decision before the 45-set — role-specific implementer context

**BUILT 2026-08-22 — ADR-062** (`_planner_note` takes the unit's
context; `planner_slice`; `## Interior` protected from the C-45 cut).
What remains of this section is the reasoning; the next step is the
two-instance re-probe named at its end. Original text follows.

**Confirmed by inspecting the phase-4 patches.** On
astropy-13579 four implementers with unrelated interiors all created
`astropy/wcs/wcsapi.py` (a file none owned, not the gold
`wcsapi/wrappers/sliced_wcs.py`), while the unit that owned the gold
file changed nothing. Cause: **`_planner_note` (in `run/stages.py`)
builds ONE planner handoff and posts it identically to every unit's
inbox** — short memory is global, not projected onto each unit's role —
**and the per-unit interior is truncated to fit the brief limit** (U1
lost 21,281 chars of its own context). So the loudest, uncut signal in
every brief is the planner's whole-change file list, and units aim at
it instead of their own interior.

ADR-061 (write-scope enforcement) stops the *damage* (a mis-aimed
unit's edits are dropped at the cut), but on that instance the result
would be an **empty patch** — the harness cannot show its value until
units actually aim at their own files. So build this next:

- **Project the planner handoff per unit** — `_planner_note` should take
  the unit and hand it only the files/symbols the planner named that
  intersect *this* unit's interior (plus "your slice of the change is
  X"), not the global list. If nothing intersects, say so plainly.
- **Protect the per-unit interior from truncation** — the brief limit
  (C-45) must never cut a unit's own interior/paths; those are the one
  thing it must keep. Cut standing/neighbour context first.
- Then re-run the two-instance full-stage probe and check whether U10
  (owns `sliced_wcs.py`) now edits it.

**Owner's standing instruction:** do **not** attribute the drift to the
model until this is fixed — "that's how we lock a door accidentally."
The harness led the implementers astray; the model's competence on
these instances is not yet measured.

## How to run the 45-set (corrected command — local eval, not Modal)

Environment (unchanged from `docs/bench-run-handoff.md`): 7B live at
`https://majax7714--hobbes-llm-qwen-qwen2-5-coder-7b-instruct-serve.modal.run/v1`
(`uv run pipeline/scripts/modal_vllm.py url`); secrets in `secrets.txt`
(`llm_key`, `modal_key_id`, `modal_key_secret`); `verified.jsonl` at the
repo root (gitignored). Binaries built in `go/bin/`; rebuild
`hobbes-session` after any Go change.

**The evaluator runs LOCALLY over the rootless-podman Docker socket, not
Modal** (swebench 5.0.2's `--modal` is broken upstream — C-50). Ensure
the socket is up once per boot: `systemctl --user start podman.socket`
(the code auto-starts it via `verdict.docker_host_env`, but confirm).
Do **not** pass `--eval-modal`. The eval dataset defaults to
`SWE-bench/SWE-bench_Verified` (the image-schema one — C-50); do not
override it with the local `verified.jsonl` or `princeton-nlp/…`.

```
# absolute paths — the shell cwd drifts; run from anywhere
cd /home/mmarrujo/hobbes/pipeline
export PATH=$HOME/.local/go/bin:$HOME/.local/bin:$PATH
export MODAL_TOKEN_ID=$(grep '^modal_key_id=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-)
export MODAL_TOKEN_SECRET=$(grep '^modal_key_secret=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-)
URL=$(uv run scripts/modal_vllm.py url)
HOBBES_LLM_API_KEY=$(grep '^llm_key=' /home/mmarrujo/hobbes/secrets.txt | cut -d= -f2-) \
uv run hobbes bench run /home/mmarrujo/hobbes/verified.jsonl --secrets /home/mmarrujo/hobbes/secrets.txt \
  --difficulty complex --arm both \
  --runtime openai --llm-base-url "$URL" --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --session-bin /home/mmarrujo/hobbes/go/bin/hobbes-session \
  --out ~/.hobbes/bench/verified-complex-7b \
  --stages plan,implement,verify --max-units 10 --max-turns 40 --max-tokens 1536 \
  --evaluate
```

- Resumable: a recorded (instance, arm, model) is skipped. The
  evaluator judges every unjudged record at the end.
- `--max-tokens 1536` (new default) caps the 7B's prose-essay turns.
- **Decision point** (preregistered, P11): the first **10–20** completed
  instances' solve verdicts. Interpret in `docs/benchmark-hypotheses.md`
  Results, dated; never re-scope H1–H3 from them.
- The pure arm runs the owned loop in each instance's swebench image
  (bash + file tools); the harness arm runs the staged flow. Both use
  the same model, turns, and token cap — the arms differ in Hobbes and
  nothing else.

## Inspecting a run (what the records carry)

- `~/.hobbes/bench/<name>/records.jsonl` — one per (instance, arm); the
  staged harness record's `detail` carries `seed_source`, `stages`
  (each with wall time + tokens), `planner` (files/hit/recall, scored
  post-hoc vs gold — C-49), `run.integration` (`merged`/`dropped`/
  `empty`), `verify`.
- Per-session logs: `<workspace>/.hobbes/plans/<task>/agents/<unit>/session.log`
  (the loop's envelope: turns, tool_calls, repeats_refused, tokens) and
  `~/.hobbes/sessions/<session>/flight.jsonl` (every exec decision).
- `hobbes bench report ~/.hobbes/bench/<name>` — H1/H2/H3 + the planner
  hit split by seed_source. Computes, never interprets.

## The eleven fixes this session (so a regression is traceable)

Phase 3: staged-arm metering + post-hoc planner∩gold (C-49). Then, from
the live runs: overlay mount (ADR-060); prose-heading + dotted-symbol
handoff parsing; planner seeds replace lexical; verifier test-name
resolution; stale session-dir cleanup; refused-repeat-after-edit stall;
`--max-turns`/`--max-tokens` to both arms; exec-repeat refusal;
read-only `pip show`/`which` in the box; dataset-file absolutizing;
`EVAL_DATASET` default; podman-socket local eval (C-50); write-scope at
the cut (ADR-061). All have tests; all on `main`.

## Deliberately not done

The role-specific context fix (above — the recommended next step).
Parallel implementers. Metering beyond envelopes. The 32B rung (deploy
per `docs/bench-run-handoff.md` when the ladder needs it).
