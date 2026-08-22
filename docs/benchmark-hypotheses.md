# Benchmark verification — the harness plan and the preregistered hypotheses

**Status: preregistered, not started** (Max, 2026-08-19; ADR-052).
Nothing here has been measured. This document exists *before* any
benchmark run for the same reason the constraint register exists: a
claim written down after the results arrive can be quietly re-scoped
to fit them, and a hypothesis written down first cannot (P11's
discipline, applied forward). When testing starts, results land in
this file next to the hypothesis they bear on — dated, with the
benchmark, instance set, models, and numbers — the way
`extraction-evidence.md` records extraction runs.

> under the current build this should arguably be the case. however
> that is what testing is for. — Max, 2026-08-19

## The approach: Hobbes as a harness

Verify a large part of Hobbes by using it as a **benchmark harness**:
take a known software-engineering benchmark (SWE-bench-class — issue
in, patch out, hidden tests decide), run each instance through the
Hobbes pipeline (`ingest` → `plan` → per-unit sandboxed execution →
verify), and compare against the same models run **pure** — no
Hobbes, same instances, same patch protocol.

Why benchmarks rather than more dogfooding:

- **Ground truth at volume.** A benchmark instance has a known
  pass/fail answer, and there are hundreds of them. Dogfooding
  verifies mechanisms; it cannot produce a solve-rate curve.
- **A large pure-model pool.** Known benchmarks carry published
  baselines across model sizes, and any baseline not published is
  cheap to reproduce — the comparison Hobbes needs is *same model,
  with and without the harness*.
- **The error stream is the adjustment signal.** Every failed
  instance is labeled data for exactly the numbers the system says
  are guesses: C-35's partition weights get their loss inputs
  (rework, contract failures, context faults — the agent-mapping §6
  loop), a failure class that turns out to be a concession gets a
  register entry, and a repo shape that breaks extraction extends
  `extraction-evidence.md`.

## The focus benchmark and the bar (Max, 2026-08-21 — preregistered)

**SWE-bench Verified is the focus benchmark**, run on a ladder of
small open models served from the owner's compute (ADR-056/057) —
Qwen2.5-Coder **7B → 32B**, then the family's next rung above 32B
(pinned when taken). Why this ladder and this set: the 7B rung has
**no published Verified score** and is generally discouraged for
multi-step agentic work — exactly the regime derived context is meant
to help — and Verified carries a human-rated `difficulty` per
instance, so "complex multi-step" is the dataset's own label
(`1-4 hours` 42, `>4 hours` 3 of 500), not our proxy.

**The bar, in rung form (H1′):** *harnessed rung N performs comparably
to pure rung N+1 on the complex multi-step set* — Hobbes-on-7B ≈
pure-32B, Hobbes-on-32B ≈ pure-next. "Comparably" is stated before the
run: the harnessed N solve rate on the complex set is within the
binomial 95% interval of pure N+1's on the same instances — at 45
instances that interval is wide, and the report prints the counts so
the width is visible, never hidden in a percentage.

- **Falsified if** harnessed 7B does not close a meaningful fraction
  of the 7B→32B gap on the complex set, or closes it only on instances
  pure 7B already solves.
- **Known biases, both against the harness:** Verified is entirely
  pre-cutoff for these models (C-39 — contamination helps the pure arm
  more: a memorised answer needs no context); and the harness arm's
  lexical seeding (C-36) fails closed, so a `no-seed` instance counts
  as a harness loss.
- **Cost shape:** the complex set is 45 instances × 2 arms per rung;
  the 7B rung fits the free Modal credit comfortably, the 32B rung
  (A100-80GB) is the first thing that may not — the run records
  GPU-seconds per arm so the H3 cost row is real, not estimated.

**Amendment (Max, 2026-08-22) — the next rung is not the 32B.** The
second rung of the ladder is changed from Qwen2.5-Coder-32B to
**Qwen3.8 27B** (`Qwen/Qwen3.8-27B`, pinned in `scripts/modal_vllm.py`
`RUNGS` on A100-80GB; not deployed — the image's vLLM pin predates its
architecture and is bumped when the rung is taken).
Reason stated before any run on it: the model is reported to score
high on instruction following and agentic coding but **low on deep
SWE tasks**, and the focus set is the deep end of Verified — so a
harness gain on it is easier to attribute (the model already follows
tools and instructions; what it lacks is the depth derived context
claims to supply) than on a 32B whose raw SWE depth is closer to
the bar. The bar's rung form (H1′) is unchanged: harnessed 7B ≈ pure
27B, harnessed 27B ≈ pure next. The rung is taken only after a 7B
run's failures are cleanly the model's (the resolve-harness-first
rule); the in-flight 5-fresh re-run is that check.

## The hypotheses

Each is stated with the metric that decides it and what failure looks
like. They are mechanisms the current build arguably implies — argued
below, measured never.

### H1 — Derived context substitutes for model size

**With Hobbes, smaller models perform to the degree of — if not
better than — larger models**, because the hard half of many tasks is
context assembly, and Hobbes hands every agent a derived, checked,
citable slice instead of asking the model to assemble one.

- **Metric:** solve rate across a model-size ladder (small / mid /
  large), each model run pure and harnessed, same instances. The
  quantity of interest is how much of the pure small→large gap the
  harness closes.
- **Falsified if** the harnessed small model does not close a
  meaningful fraction of that gap — or closes it only on instances
  the large model also finds trivial.
- **Mechanism in the current build:** context manifests are computed,
  not assembled by prompt (interior full, boundary contracts,
  one-hop signatures, complement stated); the model never spends
  capability discovering structure the graph already knows.

### H2 — Depth stops costing accuracy

**With Hobbes, deep tasks become more accurate**, because context is
*regenerated per unit* rather than accumulated across the task: a
model's accuracy degrades as context grows and tasks pile up in one
session, and the harness's answer is a smaller job, not a larger
window (architecture, "Where this is going").

- **Metric:** solve rate as a function of task depth — instances
  bucketed by edit spread (files touched), dependency-chain length,
  or step count — pure vs harnessed, same model. The quantity of
  interest is the *slope*: pure models should degrade with depth;
  the harnessed curve should be materially flatter.
- **Falsified if** the harnessed slope tracks the pure slope — depth
  hurting both equally means partitioning is not isolating what it
  claims to isolate.
- **Mechanism in the current build:** the partition bounds every
  unit's context at a budget held below the window ceiling; a deep
  task becomes several bounded units with pinned contracts instead
  of one long accumulating session.

### H3 — Cheaper and faster, as a byproduct

**Hobbes is cheaper and quicker than pure models** — fewer tokens
consumed and produced per solved task — as a byproduct of H1 and H2:
the deterministic layers spend no tokens at all (ingest, plan, gate,
and verification are parsers, indexers, and graph checks), and the
generative layer holds bounded manifests instead of accumulated
transcripts.

- **Metric:** tokens (in + out), wall time, and dollar cost **per
  solved instance** — not per attempt, so a cheap failure cannot
  masquerade as efficiency — at equal or better solve rate.
- **Falsified if** the per-solve cost is not lower, or is lower only
  by trading away solve rate.
- **The honest counter-pressure, stated up front:** multi-unit plans
  add coordination cost (several agents, contract overhead,
  renegotiations), so cross-cutting tasks could cost *more* under
  the harness. H3 claims the deterministic savings dominate; the
  per-depth cost curve is what settles it.

## The harness (ADR-055, built 2026-08-21 — quota-free, unrun)

`hobbes bench` is the machinery: `select` applies the instance protocol
(a `created_at` cutoff and filters, every drop counted), `run` checks
each instance out at its base commit and runs the **pure** arm (Claude
Code, its own tools, no Hobbes) and the **harness** arm (`ingest` →
`plan` with the issue as the proposal → `run` → the integration
branch's diff) per model, `--evaluate` hands the patches to the pinned
`swebench` evaluator, and `report` lays the records against H1–H3
below without interpreting them. Architecture §6.2 is the description
of record. Three things the harness fixes in advance so a result
cannot bend them:

- **An instance that seeds nothing is a harness failure** (`no-seed`),
  counted in the harness arm's denominator. Dropping it would inflate
  the arm under test.
- **H3 is per solved instance over observed terms.** A session that
  emitted no usage envelope is recorded unobserved and the row says how
  many; a zero is never shown for a number nobody saw.
- **The planner hit is scored after the arm, never inside it** (harness
  restructure phase 3, 2026-08-22). A staged record (`--stages`,
  ADR-059) carries `seed_source` and whether the planner's named files
  reach a gold-patch file, computed by `results.py` from the gold patch
  no session saw; `report` splits the staged harness by `seed_source`
  with the hit-rate beside the solve rate. It answers "did the planner
  find the place?" before any verdict exists — and it is a proxy, since
  the gold patch is one solution (C-49). Phase 4's probe reads this
  column first.
- **Depth is the rated band where the dataset has one** (Verified's
  `difficulty`: `<15 min fix` 194, `15 min - 1 hour` 261, `1-4 hours`
  42, `>4 hours` 3), else the gold-patch file-count proxy, and every
  report says which. `hobbes bench select --difficulty complex` is the
  45-instance focus set.

## What has to be true before a run — the current gaps

Reflecting the build as it is, not as the plan wants it:

1. **The sandbox cannot run Claude Code yet.** D2 (ADR-054) consumes a
   change-spec end to end, but no session has ever been spawned live:
   the session image is Alpine (musl), the `claude` binary is
   glibc-linked and not mounted into the container, and the session
   network is `none`. A route to the network is exactly what the
   sandbox's enforcement story says is absent, so granting one is the
   owner's decision and a register entry when taken (ADR-055 lists the
   items: glibc image, binary mount, credential, network mode, and
   the pure arm's containment).
2. **C-36 will bite, and the shape is now measured once.** Eight
   `psf/requests` instances (Verified), checked out and ingested,
   quota-free: 8/8 seed lexically; the seed set touches a gold file in
   4/8. Misses: dotted `package.function` names (`requests.get`) match
   no symbol *name*; trailing punctuation makes prose look code-shaped;
   generic words seed spuriously. Candidate adjustments are parked in
   `future_additions.md`; the loop adjusts from verdicts, not from one
   probe.
3. **Instance selection must respect contamination** — now bounded,
   not proven (C-39). Verified's newest instance is 2023-08-07; a 2025
   cutoff selects zero of 500, so a live run on a contemporary model
   needs SWE-rebench or SWE-bench-Live, recorded in `run.json`.
4. **The evaluator needs a container engine** (C-40): rootless podman
   through its socket, SWE-bench's per-instance images pulled on first
   use.
5. **P11 governs the claims.** A result on one benchmark licenses
   that benchmark's shape, not "Hobbes makes small models better."
   Every result entry below names its sample.


## Run note — the first 7B complex-set pass (2026-08-21)

The first live pass runs the 45-instance complex set on the 7B rung
(`--max-turns 20 --max-units 10`, both arms in each instance's swebench
image). Getting the harness to produce a candidate at all took five
fixes (ADR-058); it now does. **Reading rule set before the numbers
(P11):** the pass **need not finish** — the **first 10–20 completed
instances are the decision point**. A drastic outcome (harness solve ≈
0, or harness far below pure) is a signal to refocus the harness
(future_additions: unit selection, harness re-evaluation), not to
re-scope H1/H2/H3. Interpretation still lands in the Results section
below, dated, once verdicts exist — the hypotheses do not move.

## Results

None yet. The harness exists (ADR-055, 2026-08-21); no live run has
been made — the first one starts when Max settles the session-image
and network question and names the instance set and model ladder.

### 2026-08-22 — the planner probe (harness restructure phase 4, step 1)

`hobbes bench run --stages plan` on astropy-13398 and astropy-13579,
Qwen2.5-Coder-7B on Modal, harness arm only — the question was
narrow: *can a 7B, given the issue and the graph's standing context,
name the place?* Read by the planner hit column (C-49), not by any
verdict. Three attempts, each stopped by a harness finding, the
third clean:

| attempt | 13398 (gold 4 files) | 13579 (gold 1) | what stopped it |
|---|---|---|---|
| 1 | planner died in 1 s, no tokens | — | the C-43 pre-command failed on the `ro` worktree (ADR-060: overlay) |
| 2 | `files: []` → lexical-fallback, miss | `SlicedLowLevelWCS.world_to_pixel` unresolved → miss | handoff parser keyed only `files:`; no dotted-name rule |
| 3 | **hit 1/4** (`builtin_frames/itrs.py`), `seed_source: planner` | **hit 1/1** (`wrappers/sliced_wcs.py`) | — |

Both planners took **2 turns, ~9k input tokens, ~10 s** and made
**one tool call — the `reflect` itself**: neither touched a knowledge
tool or read a file; the names came from the issue text and the map.
The 13579 planner named a package dir (`wcs/wcsapi.py`) as a file and
the gold module only through a symbol; the 13398 planner named four
plausible neighbours of which one was gold, and missed the file the
patch *creates* (`itrs_observed_transforms.py`) — a created file can
never be named from the graph, and the hit-rate's denominator counts
it (noted under C-49).

**Unit interiors vs gold, re-derived offline on the probe workspaces
(deterministic, quota-free) after the third fix — the planner's seeds
now *replace* the lexical layer instead of joining it (attempt 3 had
joined them, re-admitting `input`/`frame`/`isinstance` and making the
plan the capped repository again):**

| instance | cap | gold files inside spawned units | deferred |
|---|---|---|---|
| 13398 | 20 | 3/4 (`__init__`, `itrs`, `intermediate_rotation_transforms`) | 50 |
| 13398 | 10 | 2/4 (`__init__`, `itrs`) | 60 |
| 13398 | 5 | 1/4 (`itrs`) | 65 |
| 13579 | 20 / 10 / 5 | 1/1 (`sliced_wcs`, in a 4-file unit with `base`, `__init__`, its test) | 41 / 51 / 56 |

The seed-bearing gold unit survives every cap (select-then-cap, C-44,
doing its job); the neighbour gold files go first. Two to four seeds
still expand to 60–70 modules, so the cap binds — C-35's grain, now
measured on the planner path. **Reading: the unlock works on these two
— the planner found the place both times — and the next number is the
solve.** Not a result for H1–H3 (n=2, planner-only); the full-stage
run on the same two instances follows, then the 45-set.

### 2026-08-22 — the full-stage run (phase 4, step 2), astropy-13398 & 13579

Both arms, 7B, `--stages plan,implement,verify --max-units 10
--max-turns 40`, evaluated by the pinned swebench 5.0.2 run **locally
over the rootless-podman Docker socket** (its `--modal` path is broken
upstream — C-50). **n=2, not an H1–H3 result** (P11); recorded as the
first end-to-end verdicts the harness has ever produced.

| instance | planner hit | harness verdict | pure verdict |
|---|---|---|---|
| astropy-13398 | 1/4 gold | unresolved (patch applied, F2P failed) | unresolved |
| astropy-13579 | 1/1 gold | unresolved (patch applied, 41/41 P2P pass, 1 F2P fails) | unresolved |

**0/2 both arms.** The planner found the place both times (hit 100%,
mean gold recall 62%); neither the harnessed nor the pure 7B turned
that into a passing fix. On 13579 the harness patch applied cleanly and
kept all 41 PASS_TO_PASS green but did not make the one FAIL_TO_PASS
pass — a real near-miss, not a broken patch. The pure 7B on both
instances edited an invented file (`coordinates/transforms.py`) or a
test file, never the source.

What the run cost in harness wall time and what inspecting it fixed is
in the BUILDLOG (2026-08-22, forty-first..forty-third): the implement
stage ran 21–36 min, ~45% of it on prose turns and no-op exec repeats,
now capped (`--max-tokens`, exec-repeat refusal). **Reading:** the
unlock (planner naming the place) holds; the 7B *implementer* is the
wall on these two — which is H1's actual question and needs the 45-set,
not two instances, to answer. The evaluator now works, so the set can
run.

### 2026-08-22 — the ADR-062 re-probe (harness arm only), astropy-13398 & 13579

Harness arm re-run after the planner handoff became per-unit
(ADR-062), sequential (pre-ADR-063 code), same flags, local eval.
**n=2, not an H1–H3 result** (P11). The pure-arm verdicts above stand.

| instance | planner hit | implement wall | patch | verdict |
|---|---|---|---|---|
| astropy-13398 | 1/4 gold (again) | 1,523 s (was 2,148) | 6 files, +201/−2,998 | unresolved |
| astropy-13579 | 1/1 gold (again) | 670 s (was ~1,250) | 1 file, +28/−300 | unresolved |

**0/2.** What the trace verified (every unit's brief, tool-call log and
branch read by hand — BUILDLOG forty-sixth):

- The projection works as a mechanism: each unit's inbox carried only
  its slice or a plain "nothing named is yours"; the Interior section
  was never cut.
- **The owner unit now acts on its own file** — 13579's U10 (interior
  `sliced_wcs.py`, idle last run) edited it in 47 s / 2 turns. It
  issued `pytest` and `write_file` in **one completion**, never called
  `read_file`, and replaced the 308-line module with a bare 36-line
  function. Its summary claimed it "modified the method".
- That is the pattern, not a one-off: on 13398 the merged units
  U2/U7/U9 called `write_file` on files they **had not read**
  (`transformations.py` −1,646 lines, `funcs.py`, `baseradec.py`);
  the gold file's owner U10 read `itrs.py` ten times and made seven
  `edit_file` attempts, none of which landed.
- Units told "nothing named is yours" did **not** hand off a no-change:
  on 13579 three of them returned prose plans to edit the owner's file
  (zero tool calls, 14–62 s each); on 13398 four of them `write_file`'d
  their *own* interiors — files the change did not need.

**Reading (no claim beyond this):** ADR-062 removed the harness's
mis-aim; what it exposed is that this 7B, given the right target,
overwrites unread files. Whether that is the model or the loop's tool
surface (`write_file` = "create or overwrite", no read-before-write
rule, a nudge that says act) is **not separable from two instances** —
a loop-side guard applied to both arms is the next harness decision,
and the non-owner note's `approach` line is a candidate for removal.
The loop keeps no transcript; a trace stops at the tool call.

### 2026-08-22 — the ADR-064 re-run (both arms), astropy-13579

Both arms, 7B, `--stages plan,implement,verify --parallel auto
--max-units 10`, local eval, after ADR-064 (transcript, task-tailored
selection, read-before-overwrite). **n=1, not an H1–H3 result** (P11).

**0/1 both arms** (harness patch 1 file, pure patch 2 files; both
unresolved). What the three mechanisms did, each verified from the
record and the new transcript:

- **Selection (C-52) worked and paid off:** of 10 units, **2 were
  spawned** (U5, U10 — the planner-named ones), 7 skipped as
  "planner named no file in interior", 1 human-first. Implement wall
  **274 s** (was 670 s on the same instance last run) — the do-nothing
  sessions are gone.
- **Parallel gate (ADR-063) worked, no overlap here:** the endpoint was
  detected as vLLM → 4 workers, but the two live units are a contract
  chain (`waves [[U5],[U10]]`), so `implement_wall_seconds 274 ≈
  implement_units_sum 273` — nothing independent to run at once. The
  lever is correct; this instance had no work for it.
- **Transcript (ADR-064) worked:** 62 KB of U10's full message list,
  the first time the model's own reasoning is readable turn by turn.
- **Read-before-overwrite worked as specified and did not change the
  outcome:** U10 called `write_file` on the unread `sliced_wcs.py` →
  **refused**; it read the 308-line file (transcript: "I'll read the
  file first"), then wrote a **1,088-byte stub replacing 308 lines**
  anyway. The guard forces a read, not comprehension — exactly the
  boundary the ADR named. It then looped the identical stub and the
  pre-existing repeat-refusal stopped it (the loop is the model's, not
  the guard's).

**Reading (no claim beyond n=1):** the harness now aims one unit at the
exact gold file, forces it to read that file, drops every unit that has
no work — and this 7B still answers by overwriting a 308-line module
with a stub. On this instance the model, not the harness, is the wall,
and the measurement is now clean of the harness faults that used to
confound it. Whether that holds is the 45-set's question. Open, for
Max: the stub is a `write_file`-shaped failure a `read`-gate cannot
catch; a size-delta refusal (reject a whole-file write that shrinks a
read file past a fraction, both arms) is the next candidate, but it is
tuning against one instance until the set runs.

### 2026-08-22 — the 5-fresh-instance set (both arms), django/sympy/xarray/sphinx/scikit-learn

Both arms, 7B, `--parallel auto --instance-workers 5` (ADR-063/065),
local eval. First multi-repo sample. **n=5, not an H1–H3 result**
(P11). **0/5 both arms.** But the investigation (every planner handoff
and the django edit read by hand) found the failures are **harness
weaknesses masking model capability**, not the astropy hallucination:

Recorded vs actual planner localization:

| instance | recorded | actual | cause |
|---|---|---|---|
| django | hit 1/3 | 1/3 | correct (partial) |
| sklearn | hit 1/2 | 1/2 | correct (partial) |
| xarray | **0/2** | **2/2** | **parser bug** — planner named both gold files + the right fix (dim→coord) on one markdown line; the parser swallowed `symbols:`/`tests:` into `files` |
| sympy | **0/1** | symbol ✓ | **parser bug** — planner named `polylog` (in the gold file) in prose; parser extracted nothing → lexical-fallback |
| sphinx | 0/2 | 0/2 | genuine model miss (named 9 unrelated `domains/*`) |

So corrected localization is ~4/5, not the recorded 2/5.

The one grounded-but-broken edit (django harness, `filters.py`) was a
**harness bug too**: the 7B repeated a byte-identical `edit_file` four
times (its test kept failing); `edit_file` re-includes its anchor so
each repeat stacks a duplicate, and the loop refuses repeated reads and
execs but not repeated edits — four stacked dead-code blocks.

**Reading:** the astropy hallucination did NOT generalize — of 10 arm
runs only one pure-arm run hallucinated a new file (sphinx `autodoc.py`).
The dominant failures here are two harness defects (handoff parsing,
repeated-edit stacking) that discard or corrupt correct model output.
Per the standing rule (resolve harness contribution before judging the
model): both are fixed before the next re-run, then the model rung is
re-read on clean localization. Instance concurrency (ADR-065) worked —
five instances overlapped; sphinx showed the first real unit overlap
(implement wall 1188 s < units_sum 1288 s).

### 2026-08-22 — the 5-fresh re-run on the ADR-066 harness (both arms), `five-fresh-7b-clean`

Same five instances, same flags, harness at `a2a5504`+. **0/5 both arms**
(harness: 2 unresolved, 3 empty-patch; pure: 3 unresolved, 1 empty,
1 loop-error). **n=5, not an H1–H3 result** (P11). Planner hit 3/5
recorded — and this time the record is right: the ADR-066 parser split
xarray's one-line handoff into both gold files (2/2), django 1/3,
sklearn 1/2; sympy and sphinx are misses of different kinds (below).
Instances overlapped (ADR-065); implement walls 90 s – 1,479 s.

**The window, read properly (Max's question — the Modal 400s).** The
envelopes on disk explain what Modal shows: the two earlier big runs
today paid **~390 context-length 400s** (`five-fresh-7b`: 14 fitted +
184 elided + 2 fatal; `probe-full-7b`: 55 + 131 + 4); this run paid
~10. The drop is **not** a roomier window — mean harness input is still
13.7k tokens/turn — it is that sessions now end earlier on the 6-turn
no-progress exit. Where the window goes: an implementer brief is
33.8k chars mean / 59.8k max (the C-45 limit; sympy U2's tokenized to
**16,750 tokens of 32,768**), and **82 % of it is outside the unit** —
Neighborhood 11.1k + Guarding tests 10.2k + Contracts 6.4k chars mean —
while the unit's own Interior averages 171 chars. With `max_tokens`
1536 and 12k-char read clips, a unit gets three or four `read_file`s
before the first overflow, and C-46's fit then elides **the model's own
reads first** (the brief is protected): sympy U2 read the file it was
about to edit, had the read elided, guessed the anchor, and spun. That
is a constraint the harness imposes, and it is registered as such
(C-46 amended).

**Per instance, classified** (gold files → arm touches → planner → unit
transcript):

| instance | planner | harness units | pure | class |
|---|---|---|---|---|
| django | 1/3 (`filters.py`) | U4 edited `filters.py` **without reading it**: one guessed anchor missed, one hit; the hit edit applied 3× with slightly different `new_text` each time (the ADR-066 byte-identity refusal correctly did not fire) — stacked; unresolved | edited `filters.py`; unresolved | implementer-execution (no read; anchor stacking) |
| sympy | **0** — named `sympy/polys/modules/zeta.py`, a path that does not exist, in prose → lexical fallback | U2's reads elided (fit 2 / elided 3); guessed anchor ×6 | touched 4 files incl. gold; unresolved | planner-localisation (model) + window (harness) |
| xarray | **2/2** | U1 wrote its edits as a ```` ```python ```` fence (unparsed, invalid JSON); U2 `edit_file` on `def integrate(self, dim=None, **kwargs):` — a signature that does not exist — **9 identical pairs, never a read** | loop-error (no-progress) | implementer-execution (no read) |
| sklearn | 1/2 (`base.py`) | U1 prose only across 3 nudges; U2 ran the guarding tests, then *reported* edits it never made | empty | implementer-execution (no edit) |
| sphinx | **0** — the planner wrote `reflect` as a ```` ```json ```` fence that **`--max-tokens 1536` cut mid-list**, three times; the loop does not record `finish_reason`, so a truncated tool call is treated as prose and nudged → lexical fallback | U1/U7 edited `domains/cpp.py`, `util/inspect.py`; unresolved | hallucinated new file `sphinx/ext/autodoc.py`; unresolved | harness (truncation) + planner-localisation |

**Reading.** The two ADR-066 fixes did what they were built for (xarray
2/2; no byte-identical stack). What dominates now is one model
behaviour and three harness gaps around it. The behaviour: **the 7B
implementer edits from memory** — in 30 unit sessions the first turn is
a prose "Changes made" and the edits that follow carry guessed anchors;
`read_file` is rarely called before `edit_file`. The gaps: (1) a
completion cut at `max_tokens` is not detected — the sphinx planner's
correct-shaped handoff was lost three times; (2) the fenced-call parser
accepts only ```` ```json ```` / bare fences with strict JSON; (3)
`edit_file` has no read-before-edit rule (ADR-064 gave `write_file`
one), so a guessed anchor costs the model nothing but a turn; and the
anchor-stacking variant ADR-066 does not cover (same anchor, reworded
text). Behind all of it sits the window: **82 % of the brief is
context the unit cannot change**, and forcing reads will make that the
binding constraint — the brief's shape is a design decision (Max's),
not a parser fix. Per the standing rule, the four gaps are harness and
are fixed before the model is re-read; the brief question is put to
Max with the numbers above.

**Addendum, the same night — the window per call, validated.** Max read
the Modal vLLM log and saw calls saturating far more often than the
envelope counts said. Reconstructed every harness call of the re-run
(221 calls: each assistant turn's message prefix tokenized on the
endpoint) and checked it against vLLM's own `prompt_tokens` sums in the
envelopes: the difference is a constant **1,546 tokens/call** on every
implementer and 1,361 on read-only roles — the tool schema — so the
reconstruction is exact. **In this run (02:38–03:10 EDT) the harness
was not saturated:** median prompt 14k, mean 14k, 41 % of calls ≥ 16k,
19 % ≥ 20k, **8 calls ≥ 24k, 2 ≥ 28k** (sympy U2's last two — the only
session that fit or elided), 1 call with less than the 1,536-token cap
of room. The pure arm has no transcript (fixed, ADR-068); from its
envelopes the largest estimated last call is ~27k (sympy, 20 turns).
What *was* saturated is the two earlier runs (`five-fresh-7b`, ended
01:16 EDT, and `probe-full-7b`, 21:59 the day before): 198 and 190
overflow events, average prompts 16–19k, sessions sitting at the
window for consecutive turns — each turn a 400 absorbed into a 200.
That is what a Modal log spanning the day shows, and it is the
honest description of those runs: most of their implement wall was
spent at the limit. The instrument that makes this a read instead of
a reconstruction is ADR-068's `calls.jsonl` + `calls_saturated`.

### 2026-08-22 — the cheap 7B run on ADR-067/068/069, `five-fresh-7b-adr069`

Same five, both arms, brief **sized to the window** (37,847 chars = 35 %
of 32,768 tokens, read from the endpoint — ADR-069), read-before-edit +
anchor-stack refusal + cut retry (ADR-067), every call logged (ADR-068).
**0/5 both arms** (harness 3 unresolved / 2 empty; pure 2 / 3 loop-error).
**n=5, not an H1–H3 result.** Planner: django 1/3, sklearn 1/2, xarray
2/2, sympy 0 (prose again), sphinx 0 (cut again). Implement walls rose
(xarray 1,186 s, sympy 1,490 s, sphinx 1,922 s): the forced reads cost
turns and tokens.

**What the per-call log shows (the first run that has one):**

- **The window bound where reads were forced**: xarray U2/U7 and sympy
  U1/U4 reached 31–32k-token prompts with 1–3 saturated calls each; most
  sessions stayed at 12–22k. The smaller brief made room; the reads
  filled it.
- **Read-before-edit worked and was not enough.** The refusal fired
  (`has not read`: 1–4 per session), the model read — and the reads
  were **clipped**: 161 `read_file` calls, **40 clipped at 12k chars,
  1 with a line range**. xarray U2 read `dataarray.py`,
  `test_dataarray.py`, `test_dataset.py` whole, saw only their imports,
  and re-sent `def integrate(self, dim=None, **kwargs):` (a signature
  that does not exist; the real one is at line 5,966 of a 260,900-char
  file) six more times. 15 of the 18 sessions with an anchor miss had a
  clipped read. The loop had no search; the pure arm had `bash` and
  never grepped. → **ADR-070: `search_file`**, and the clip notice says
  "this is NOT the whole file".
- **The cut retry fired and was not enough for the sphinx planner**:
  cut at 1,536 and at 3,072 — a 9,895-char enumeration of
  `sphinx/domains/*`. → ADR-070 bounds the handoff in the brief (≤5
  files, <15 lines).
- The pure arm's three loop-errors are all the same exit: repeated
  refused edits (xarray: 24 anchor misses after one clipped read).
- sympy pure touched the gold file (`zeta_functions.py`, the
  `exp_polar` line) — unresolved, but the first pure-arm edit on the
  right line in this set.

**Reading.** The failures are now one layer deeper than last time and
still not cleanly the model's: the model's habit (edit from memory)
meets a tool set in which a large file is unreadable. With ADR-070 the
search exists and every refusal points at it; if the next run shows
`search_file` unused and anchors still guessed, that is the 7B, cleanly.
Planner localization is unchanged (3/5 hit; sympy prose, sphinx
verbose) — the 27B question.

### 2026-08-22 — the ADR-070 verification run, `five-fresh-7b-adr070`

Same five, both arms, ADR-067–070. **0/5 both arms** (harness 2
unresolved / 3 empty; pure 5 loop-errors). **n=5, not an H1–H3 result.**
Max's ask: verify honestly whether the failures are now the 7B's.

**Planner:** all five handoffs **parsed** (no lexical fallback — the
bound worked). Hits: django 1/3, sklearn 1/2, xarray 2/2 (recorded 1/2:
`dataset.py.` with a sentence dot — fixed), sympy **1/1** (first time),
sphinx 0/2 (named `domains/python|cpp|javascript`, wrong — a clean
localisation miss).

**The chain, verified per session** (`search_file` / reads / clipped /
ranged / unread refusals / anchor misses):

| session | what happened | whose |
|---|---|---|
| sklearn U2 | refusal → `search_file` → `read_file` 10–150 → `edit_file` with the anchor copied → **edited** (merged; wrong fix, unresolved) — then its `pytest` was refused as a repeat | model did the chain; **harness** refused the test (exec name, ADR-071) |
| xarray U2 | 6 searches, **0 reads**, 6 unread refusals | model |
| sphinx U1 | 7 searches, 0 reads, 7 unread refusals | model |
| django U4 (harness) | 1 search, 0 reads, prose, no edit | model |
| sympy (harness) | planner hit → owner unit **human-first, parked**; six others unnamed → **zero units ran** | design (C-53) |
| django pure | search found both classes (`:162`, `:419`); read a **range**; `old_text` = invented code not in the file | model |
| sympy pure | `search_file("def polylog")` ×3 → no match (it is a `class`); anchor `if n == 1:` vs real `if z == 1:` | model |
| sklearn pure | searched `sklearn/utils/_output.py` (hallucinated; real `_set_output.py`) → "(no matches)" → kept editing it | **harness** (missing path ≠ empty result) + model |
| sphinx pure | same: `sphinx/ext/autodoc.py` (a package) → "(no matches)" ×2 | harness + model |
| xarray pure | searched a call shape, not the def; guessed anchors again | model |

**Two harness findings, both fixed (ADR-071):** the loop's shell check
only matched `…__exec`, and the proxy's tool is `exec` — so in **every
harness run since ADR-058** a test re-run after an edit was refused as
a read-only repeat, which is the "refused repeated calls" exit most
harness sessions end on; and `search_file` answered a missing path as
"(no matches)". One design finding: the better planner produced the
emptier run — sympy's gold owner is human-first in this partition and
was parked, as it had been in both earlier partitions; a benchmark has
no human to park on (C-53, `--human-first spawn`, Max's call).

**Also observed:** the pure arm at temperature 0 is **not
reproducible** across runs (django: patch, patch, loop-error; sympy hit
the gold line in one run of three) — vLLM batching makes decode
order-dependent, so n=1 per instance is noisier than the temperature
suggests.

**Reading.** Seven of ten arms now fail in the model cleanly: it uses
the search, receives ground truth, and writes from memory anyway; or it
searches and never reads though the refusal tells it to. That is the
7B's shape, stated for the first time without a harness excuse beside
it — except the exec defect, which ended sessions early and whose size
on this set is unknown until a run without it. So: one more 7B run on
ADR-071 (with `--human-first spawn`) is the honest minimum before the
27B; it is cheap, and it is the first run whose harness we have no
known reason to doubt.

**Addendum — the planner never had the context (ADR-072).** Max asked
whether sphinx's planner was given `sphinx/ext/autodoc` and named
`domains/*` anyway. It was not given it: the planner's map was the
first 60 modules alphabetically, and across the five briefs of this run
the gold module was present for **1 of 5** instances. Every planner's
single tool call was its `reflect`. **Every planner hit recorded on
2026-08-22 measured the 7B's prior knowledge of these repositories
(C-39), not Hobbes.** The map is now ranked by the proposal (path and
symbol tokens, rarity-weighted) with the whole package tree; on the
five real graphs the gold files rank django 1/38/44, xarray 7/5,
sklearn 71/44, sphinx 2/9, sympy 40 — all within the 80 listed. The
next run is the first in which the planner hit rate can say anything
about derived context.

### 2026-08-22 — the ADR-071/072 run, `five-fresh-7b-adr072` (`--human-first spawn`)

Same five, both arms; shell recognised (ADR-071), planner map ranked by
the proposal (ADR-072), human-first units spawned (C-53). **0/5 both
arms** (harness 1 unresolved / 4 empty; pure 3 unresolved / 2 empty).
**n=5, not an H1–H3 result.**

**The planner changed shape — the first Hobbes-derived localisation.**
Before ADR-072 no planner called a tool. Now: sympy `search_file
("polylog")` → `read_file(zeta_functions.py)` → `who_calls` →
`tests_guarding` → a correct handoff naming the gold file **and** the
gold test — grounded in derived context, not memory. sklearn's planner
searched twice and called `graph_neighborhood` three times (by path —
refused, ADR-073). sphinx's planner searched three times for a guessed
string, found nothing, and handed off the failure message (lexical
fallback). Hits: django 1/3, sympy 1/1, xarray 2/2, sklearn 0/2
(before: 1/2 by memory — now it named `_set_output.py`, the module the
gold patch *calls*), sphinx 0/2. Gold rank in the map: django 1,
xarray 5/7, sklearn 71/44, sphinx 2/9, sympy 40.

**Implementers, per session:** ranged reads are now common (5–7 per
session where the search was used); the exec fix shows as `exec ok`
followed by the *correct* "nothing edited since" refusal; sympy's
human-first owner ran (U9): searched, found `polylog` at line 63, then
tried to `write_file` the whole module from memory (refused, ADR-064)
and never read it. Anchor misses carry no line-number prefixes — the
model invents names (`def get_attribute` for `id_attributes`) and once
a literal `<path_to_found_file>`. Nothing in this run's harness arm is
left that a known harness defect explains.

**Reading.** Four runs, 0/5 each, and the failure has walked all the
way down to the model: it now gets the place from Hobbes (sympy), the
file's real text from the search, and still writes from memory. The
7B rung is read: **it cannot execute on derived context**, cleanly.
Planner localisation from derived context works in the one case the
model bothered to look (sympy); where it guessed (sphinx) it failed.
The 27B is the question now — with the harness record behind it, not
ahead of it. Pure arm: still not reproducible at temperature 0.

### Pre-run observations (quota-free; not results)

- **2026-08-21 — seed probe, `psf/requests`, SWE-bench Verified, 8
  instances, lane A only.** 8/8 seeded; seed set touches a gold-patch
  file in 4/8 (1142, 1766, 1921, 2317 hit; 1724, 2931, 5414, 6028
  miss). Raw probe kept with the session's scratch output; the shapes
  of the misses are recorded under C-36.
