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
- **Depth is a proxy** — the gold patch's file count, bucketed
  1 / 2–3 / 4+ — and every report says so. On SWE-bench Verified the
  buckets hold 429 / 61 / 10 of 500, so H2's slope there would rest on
  ten instances at the deep end; a set with more spread is preferable
  and the choice is recorded with the results.

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

## Results

None yet. The harness exists (ADR-055, 2026-08-21); no live run has
been made — the first one starts when Max settles the session-image
and network question and names the instance set and model ladder.

### Pre-run observations (quota-free; not results)

- **2026-08-21 — seed probe, `psf/requests`, SWE-bench Verified, 8
  instances, lane A only.** 8/8 seeded; seed set touches a gold-patch
  file in 4/8 (1142, 1766, 1921, 2317 hit; 1724, 2931, 5414, 6028
  miss). Raw probe kept with the session's scratch output; the shapes
  of the misses are recorded under C-36.
