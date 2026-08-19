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

## What has to be true before a run — the current gaps

Reflecting the build as it is, not as the plan wants it:

1. **D2 is not built.** Nothing consumes a change-spec: `hobbes plan`
   produces manifests no session spawner reads yet. An end-to-end
   benchmark run needs the execution half (spawning, faults, the
   recorder's partition record) — parked in `future_additions.md`
   with scope. Until then, only the mapping is inspectable per
   instance, not the solve rate.
2. **C-36 will bite first.** Benchmark issues are prose; lexical
   seeding will miss on instances whose text names no identifier.
   The predicted first adjustment is a seed-extraction layer over
   the issue text (the generative planner parked in D2's entry) —
   and the C-36 miss rate on real instances is itself a number worth
   recording.
3. **Instance selection must respect contamination.** Known
   benchmarks are in training corpora; a pure model may "solve" from
   memory, which biases *against* the harness (memorized answers
   need no context). Prefer post-cutoff or held-out instance sets,
   and record the choice with the results.
4. **P11 governs the claims.** A result on one benchmark licenses
   that benchmark's shape, not "Hobbes makes small models better."
   Every result entry below names its sample.

## Results

None yet. Testing is deliberately not introduced as of 2026-08-19;
this section fills in when Max names the start.
