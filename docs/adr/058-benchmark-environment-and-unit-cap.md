# ADR-058 — The benchmark's environment bound to both arms, and the unit cap

**Date:** 2026-08-21
**Status:** accepted — built, run live on one instance's pure arm;
the first full complex-set run relaunched under it
**Amends:** `docs/hobbes-architecture.md` (§6.2); `docs/constraints.md`
(C-43, C-44); `docs/bench-run-handoff.md`; ADR-057's "consequences"

## Context

The first full run of the complex set (ADR-057's handoff) was stopped
after its first instance. Twenty minutes in, `astropy__astropy-13398`
had surfaced two structural problems, both independent of the model
under test and both in the harness's own hands:

1. **The plan exploded to 210 units.** `hobbes plan` over astropy with
   the issue as proposal produced 210 agent units (an 80k-line
   change-spec); `hobbes run` spawns one sandbox session per unit, and
   the measured session was ~7.5 minutes — about 26 hours for one
   instance's harness arm, on a 45-instance set. ADR-051's per-hop
   decay had cut the dogfood repo's 33-unit case; at astropy's scale
   with lexical seeds (C-36) it does not hold. C-35 — partition
   quality unvalidated — firing on the first large repo.
2. **Neither arm could run the target's tests.** The session image is
   a bare Alpine with python3 and git; the pure arm ran on the host.
   Every unit's flight log was the same loop: `pytest` → exit 127,
   `pip install pytest` → 127, `git commit` → exit 128 (no identity
   in the clone), then `apt-get` / `curl get-pip.py` /
   `git config --global`, each escalating and expire-denying at 5s.
   The solo policy (ADR-057) was working exactly as designed — the
   `pytest*` and `git add*` rules answered `allow` — but there was
   nothing to run. An agent that cannot run a test cannot verify a
   fix, so the arm's outcome was empty by construction.

The owner's direction: cap benchmark plans at **20 units** ("we can
adjust after with n max sizing"), and **install the environment** —
acknowledged as a benchmark practice, not an architecture change.

## Decision

1. **The benchmark's environment is the benchmark's own image, bound
   to both arms** (`pipeline/src/hobbes/bench/environment.py`). Each
   SWE-bench instance publishes an image with the repo installed at
   the base commit and its per-version environment — the same image
   the evaluator judges in (C-40). Both arms now run *in* it:
   `hobbes-session --image` for the harness arm, a bare `podman run`
   over the mounted workspace for the pure arm (which was on the
   host; this also discharges ADR-055's "pure-arm containment" item).
   The workspace at `/work` is bound to the environment by two
   mechanisms, both visible in the dry run and recorded per arm
   (image + digest):
   - `PYTHONPATH=/work` — the image's editable install points at
     `/testbed`; a path entry precedes the editable finder on
     `sys.meta_path`, so the worktree shadows the installed copy;
   - a **pre-command** that copies `/testbed`'s untracked files (the
     in-place build artifacts: `.so` extensions, generated version
     modules) into `/work`, so a compiled repo imports without a
     rebuild. Verified on astropy: the same test file gives the same
     result from `/work` as from `/testbed`.
   `hobbes-session` gained the flags this needs — `--path`, `--env
   K=V` (repeatable), `--pre CMD`, `--runtime-python P` — and the
   session command is unchanged in shape: the pre-command wraps it
   with `sh -c 'PRE && exec "$@"'`. The owned loop runs on the
   image's base python (`/opt/miniconda3/bin/python3`, 3.11) because
   the conda env carries the *target's* python, which is 3.6 on old
   django. `hobbes bench run --environment swebench` is the default;
   `none` is the old behaviour, kept so the harness can run without
   podman images (the tests use it).
2. **A commit identity for every session clone.** `hobbes-session`
   copies the canonical repo's `user.name`/`user.email` into the
   clone (falling back to `hobbes-session` / `session@hobbes.local`).
   A sandbox has no global git config, so every in-session commit
   had been exit 128. Not benchmark-specific: any session that
   commits needed this.
3. **The unit cap** (`partition.build_units(max_units=…)`). After the
   budgeted partition, while the count exceeds the cap: merge the
   strongest-coupled pair *past the budget*; when nothing couples,
   merge the two lightest units. Deterministic by the partition's own
   tie rule. Every unit the cap touched is flagged `capped` — the
   merge was for session count, not coupling — and the spec records
   `max_units`. `hobbes bench run --max-units` defaults to **20**
   (`0` = no cap); `hobbes plan --max-units` exists with no default,
   because a human-reviewed plan has a human to size it.

## What this is not

- Not a change to the sandbox boundary. The mounts, the network
  (C-41), the policy chain and the proxy are unchanged; the image is
  the benchmark's and the two bindings are host-authored, listed in
  the argv, never the agent's to set.
- Not a claim that 20 is right. It is the owner's first sizing, to
  be adjusted from the run's verdicts ("n max sizing"); the flag on
  every capped unit is what makes the adjustment measurable — a run
  can count how often the cap, not the coupling, decided a unit.
- Not a fix for C-35/C-36. The 210 units were the impact set's size
  under lexical seeds on a large repo; the cap bounds the cost of
  that, it does not improve the partition. The parked seed
  adjustments in `future_additions.md` remain the response to the
  miss rate, decided from verdicts.

## Consequences

- **C-43** registered, surfaced: the environment binding's edge — a
  change that needs a rebuild of a compiled extension is not seen by
  the tests, because the build artifacts are copied, not rebuilt.
  Four of the 45 complex instances are compiled repos (astropy ×3,
  scikit-learn ×1); 41 are pure python.
- **C-44** registered, surfaced: a capped unit's modules were merged
  for count, not coupling; the flag, the spec's `max_units`, the
  record's `capped` count and the run banner all say so.
- The run manifest records `environment`, `network`, `max_units`;
  each record's `detail.environment` carries the image and digest.
- Tests: Go +3 (env binding printed and wrapped; no wrapper without
  `--pre`; clone identity copied and defaulted), pytest +14 (cap
  semantics ×6, environment ×8). 783 pytest / Go green.
- The 20-minute poll that found this is the handoff's "watch it"
  step; it worked. The handoff doc now says what to look for first.
