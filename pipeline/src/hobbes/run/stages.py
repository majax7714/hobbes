"""The staged run — a proposal to a verified patch (harness restructure, ADR-059).

The owner's structure: single-use **derived-context** agents, one alive
at a time, each agent's job arriving as its short memory (the previous
agent's handoff). One does its job and sends to the next; some agents'
whole job is to feed the next agent's short memory. The stages:

1. **plan** — a *planner* session (read-only) breaks the proposal down
   over the repo's derived context and hands off the files, symbols and
   tests the change touches. Its handoff becomes the seeds — this is the
   generative layer C-36 always said would sit *above* the lexical seeds,
   never inside them.
2. (derive) — ``hobbes plan`` runs deterministically on the planner's
   seeds; ``seed_source`` records whether they came from the planner or,
   when the planner resolved nothing, from the lexical fallback.
3. **review** (opt-in) — a *reviewer* session judges the change-spec;
   ``amend`` re-plans once.
4. **implement** — one *implementer* per unit, in contract order, each
   cloned at the **current** ``hobbes/<task>`` head so a consumer sees
   its owner's commit; the branch is integrated immediately after
   harvest, a conflict recorded at the cut.
5. **verify** — a *verifier* session over the integrated head runs the
   planner's named tests and hands off ``pass``/``fail``.
6. **rework** (opt-in) — on ``fail``, one implementer over the unit(s)
   the verifier named, then verify once more.

Everything a session does is its brief (standing context + inbox) and
its handoff (short memory forward); nothing is a chat transcript. The
whole flow is quota-free to exercise: ``dry_run`` spawns nothing and the
suite drives it with the stand-in session binary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from hobbes import artifacts
from hobbes.derive import derive_plan, write_spec
from hobbes.derive.changespec import task_id
from hobbes.derive.impact import build_lookup, resolve_terms
from hobbes.run import agents, mail, parallel
from hobbes.run.handoff import parse_handoff
from hobbes.run.orchestrate import (
    RunError, UnitRecord, integrate, loss, order_units, read_branch,
    read_flight, review_integration, _branch_exists, _git,
)
from hobbes.run.roles import ensure_role_policies
from hobbes.run.spec import plan_dir

DEFAULT_STAGES = ("plan", "implement", "verify")
ALL_STAGES = ("plan", "review", "implement", "verify", "rework")


def repo_context(graph: dict, limit: int = 60) -> str:
    """The planner's standing context: a repo-level map, the capture
    line, and the blind-spot denominator — enough to name where a change
    lands, deliberately not the source (the planner reads for that)."""
    lines = ["# Repository map (for planning — read the files for detail)", ""]
    langs = ", ".join(graph.get("languages", [])) or "unknown"
    lines.append(f"Languages: {langs}. This is a graph-derived map, not the source.")
    cov = graph.get("resolution_coverage", []) or []
    sites = sum(r.get("sites", 0) for r in cov)
    unresolved = sum(r.get("unresolved", 0) for r in cov)
    if sites:
        pct = round(100.0 * (sites - unresolved) / sites, 1)
        lines.append(f"Capture: {pct}% of {sites:,} detected call sites resolved — "
                     f"{unresolved:,} are unresolved (calls Hobbes cannot see, not absent).")
    lines.append("")
    lines.append("## Modules (id — path)")
    mods = sorted((n for n in graph.get("nodes", []) if n.get("kind") in ("module", "package") and n.get("path")),
                  key=lambda n: n["path"])
    for n in mods[:limit]:
        lines.append(f"- `{n['id']}` — {n['path']}")
    if len(mods) > limit:
        lines.append(f"- … +{len(mods) - limit} more modules; use graph_neighborhood / who_calls to explore")
    lines.append("")
    return "\n".join(lines)


def planner_brief(proposal: str, graph: dict) -> str:
    """The planner's prompt: the proposal, the repo map, and the exact
    handoff shape the orchestrator will parse."""
    return "\n".join([
        "You are a single-use planner. You do not change any files. Your job is to",
        "read the repository and decide **which files the change below touches**, then",
        "hand that off to the implementers who will do the work.",
        "",
        "## Proposal",
        proposal.strip(),
        "",
        "## How to work",
        "- Use the knowledge tools (graph_neighborhood, who_calls, tests_guarding) and",
        "  read the relevant files to locate the change. Be specific: name real files.",
        "- Do not describe a fix in prose only. Your deliverable is the handoff below.",
        "",
        "## Your handoff (call reflect with kind \"handoff\" and exactly this shape)",
        "files: the repo-relative paths the change must edit, comma-separated",
        "symbols: the functions/classes to change (optional)",
        "tests: the test files or ids that guard this behavior, comma-separated",
        "approach: two or three sentences on the fix",
        "risks: what you are unsure of",
        "",
        repo_context(graph),
    ])


def spawn(session_bin: str | None, repo: Path, role: str, agent_dir: Path, session: str,
          brief_path: Path, sessions_root: Path, extra_args: list[str], ref: str | None,
          dry_run: bool) -> subprocess.CompletedProcess | None:
    """Start one single-use session; returns the completed process (or
    None on a dry run with no binary). The caller blocks on it; in a
    staged run several may be alive in one wave (ADR-063), never two of
    the same unit. The
    process carries ``wall_seconds`` (measured from outside, so it is
    observed even when the session emits no envelope) and its output is
    the agent's ``session.log`` — every stage's meter, whatever the role."""
    cmd = [session_bin or "hobbes-session", "start", "--repo", str(repo), "--role", role,
           "--agent-dir", str(agent_dir), "--session", session,
           "--sessions", str(sessions_root), "--task-file", str(brief_path)]
    if ref:
        cmd += ["--ref", ref]
    if dry_run:
        cmd.append("--dry-run")
    cmd += list(extra_args or [])
    (agent_dir / "spawn.txt").write_text(" ".join(cmd) + "\n")
    if dry_run and not session_bin:
        return None
    # Session names are deterministic (task id + role/unit), so a previous
    # run of the same proposal leaves a session dir behind and the clone
    # refuses a non-empty worktree (the full-stage probe's U3). The old
    # dir's record was captured by its own run; clear it.
    stale = Path(sessions_root) / session
    if stale.is_dir() and not dry_run:
        shutil.rmtree(stale, ignore_errors=True)
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    proc.wall_seconds = round(time.monotonic() - started, 3)  # type: ignore[attr-defined]
    (agent_dir / "session.log").write_text(proc.stdout + proc.stderr)
    # A rework reuses the unit's agent dir; the per-session copy keeps
    # the first pass's meter readable after the second overwrites session.log.
    (agent_dir / f"{session}.log").write_text(proc.stdout + proc.stderr)
    return proc


def _wall(proc) -> float | None:
    return getattr(proc, "wall_seconds", None) if proc else None


def _head_sha(repo: Path, target: str, base: str) -> str:
    """The commit at *target* (the running integration branch), falling
    back to *base* — passed as ``--ref`` so a --local clone reaches it by
    object, not by a branch name it did not copy."""
    code, sha = _git(repo, "rev-parse", "--verify", "-q", target)
    return sha.strip() if code == 0 and sha.strip() else base


def _resolve_binaries(session_bin, sessions_root, dry_run):
    session_bin = session_bin or os.environ.get("HOBBES_SESSION_BIN") or shutil.which("hobbes-session")
    if not session_bin and not dry_run:
        raise RunError("hobbes-session not found; build go/bin/hobbes-session or set HOBBES_SESSION_BIN")
    sessions_root = Path(sessions_root or os.environ.get("HOBBES_SESSIONS") or Path.home() / ".hobbes" / "sessions")
    return session_bin, sessions_root


def run_planner(repo: Path, proposal: str, graph: dict, pdir: Path, session_bin, sessions_root,
                extra_args, brief_limit, dry_run) -> dict:
    """Spawn the planner and return its parsed handoff plus the raw text
    and the misses when its named files did not resolve."""
    directory = agents.agent_dir(pdir, "planner")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / mail.INBOX).touch()
    (directory / "policy.yaml").write_text(json.dumps(
        {"version": 1, "scope": "agent", "default": "escalate",
         "rules": [{"pattern": "git commit*", "decision": "deny", "reason": "the planner writes nothing"},
                   {"pattern": "git add *", "decision": "deny", "reason": "the planner writes nothing"}]}))
    brief = planner_brief(proposal, graph)
    if brief_limit and len(brief) > brief_limit:
        brief = brief[:brief_limit] + "\n… (repo map truncated to the brief limit; use the knowledge tools)\n"
    (directory / "brief.md").write_text(brief)
    session = f"{task_id(proposal)}-planner"
    proc = spawn(session_bin, repo, "planner", directory, session, directory / "brief.md",
                 sessions_root, extra_args, ref=None, dry_run=dry_run)
    reflected = mail.reflections(sessions_root / session)
    chosen, _ = mail.handoff(reflected)
    parsed = parse_handoff(chosen.get("text", "") if chosen else "")
    return {"session": session, "exit": proc.returncode if proc else None, "wall_seconds": _wall(proc),
            "handoff": parsed, "reflections": [m.get("text", "") for m in reflected]}


def run_staged(
    repo_root: Path,
    proposal: str,
    stages: tuple[str, ...] = DEFAULT_STAGES,
    session_bin: str | None = None,
    sessions_root: Path | None = None,
    extra_args: list[str] | None = None,
    brief_limit: int | None = None,
    workers: int = 1,
    max_units: int | None = None,
    budget: int | None = None,
    seeds: list[str] | None = None,
    dry_run: bool = False,
    max_rework: int = 1,
) -> dict:
    """Run a proposal end to end through the stages. Returns the
    partition record, extended with a ``stages`` list and ``seed_source``."""
    repo = Path(repo_root).resolve()
    session_bin, sessions_root = _resolve_binaries(session_bin, sessions_root, dry_run)
    extra_args = list(extra_args or [])
    graph = artifacts.load_graph(repo, accepts=artifacts.V4_ONLY)
    tests_doc = artifacts.load_tests(repo) if (repo / ".hobbes/derived/tests.json").is_file() else {"tests": []}
    ensure_role_policies(repo)
    task = task_id(proposal)
    pdir = plan_dir(repo, task)
    pdir.mkdir(parents=True, exist_ok=True)
    stage_log: list[dict] = []

    # 1. plan — the planner names the change; its handoff is the seeds.
    planner_seeds = list(seeds or [])
    seed_source = "explicit" if seeds else "lexical-fallback"
    planner_misses: list[str] = []
    planner_tests: list[str] = []
    if "plan" in stages:
        result = run_planner(repo, proposal, graph, pdir, session_bin, sessions_root,
                             extra_args, brief_limit, dry_run)
        handoff = result["handoff"]
        named = handoff.get("files", []) + handoff.get("symbols", [])
        hits, planner_misses = resolve_terms(graph, named)
        planner_tests = handoff.get("tests", [])
        stage_log.append({"stage": "plan", "role": "planner", "agent": "planner",
                          **{k: result.get(k) for k in ("session", "exit", "wall_seconds")},
                          "handoff": handoff.get("raw", ""), "approach": handoff.get("approach", ""),
                          "files": list(handoff.get("files", [])), "symbols": list(handoff.get("symbols", [])),
                          "terms": term_modules(graph, named),
                          "resolved": hits, "unresolved": planner_misses, "tests": planner_tests})
        if hits:
            planner_seeds = hits
            seed_source = "planner"

    # 2. derive — deterministic, on the planner's seeds *alone* (the
    # lexical layer is the fallback, not a co-seeder), or the fallback.
    kwargs = {"seeds": planner_seeds, "max_units": max_units, "lexical": seed_source != "planner"}
    if budget:
        kwargs["budget"] = budget
    spec_obj = derive_plan(repo, proposal, **kwargs)
    write_spec(repo, spec_obj)
    spec = artifacts_spec(repo, task)

    # 3. review — opt-in; an amend re-plans once (bounded).
    if "review" in stages:
        verdict = run_review(repo, spec, pdir, session_bin, sessions_root, extra_args, brief_limit, dry_run)
        stage_log.append(verdict["stage"])

    dirs = agents.materialize(pdir, spec, tests_doc, role="implementer")
    orchestrator = agents.agent_dir(pdir, agents.ORCHESTRATOR)
    contexts = {c["unit"]: c for c in spec.get("contexts", [])}
    # The planner's handoff is the first short memory every implementer
    # gets — PROJECTED onto the unit (ADR-062): each inbox carries only
    # the part of the change that lies in its own interior, and says so
    # when none does. One global handoff led every unit to the same file.
    for unit in dirs:
        planner_note = _planner_note(seed_source, stage_log, contexts.get(unit))
        if planner_note:
            mail.post(dirs[unit], "planner", planner_note, kind="handoff")

    code, head = _git(repo, "rev-parse", "HEAD")
    base = head if code == 0 else spec.get("graph_sha", "")
    test_files = {t["id"]: t.get("file", "") for t in tests_doc.get("tests", [])}
    order = order_units(spec)
    records: list[UnitRecord] = []
    sessions: dict[str, str] = {}
    target = f"hobbes/{task}"
    integ = {"branch": target, "merged": [], "failed": []}

    implement_wall: float | None = None
    waves: list[list[str]] = []
    if "implement" in stages:
        _git(repo, "branch", "-f", target, base)
        implement_started = time.monotonic()
        deps = parallel.unit_dependencies(spec)
        pending = list(order)
        done: set[str] = set()

        def start(unit: str):
            """Brief + spawn for one unit; runs on a worker thread. Only
            reads the repo (the clone is at the integration head as of
            now) — harvest and integration happen on the caller's thread."""
            session = f"{task}-{unit.lower()}"
            record = UnitRecord(unit=unit, role="implementer", session=session, spawned=False)
            inbox = mail.read(dirs[unit])
            full = agents.render_brief(spec, unit, "implementer", inbox, session)
            brief = agents.render_brief(spec, unit, "implementer", inbox, session, limit=brief_limit)
            (dirs[unit] / "brief.md").write_text(brief)
            record.brief_chars, record.brief_cut = len(brief), max(0, len(full) - len(brief))
            # Chained: start at the current integration head so a consumer
            # sees its owner's commit. The ref is the *commit*, not the
            # branch name — a --local clone exposes other branches only as
            # origin/*, but the object is in the copied store.
            head_ref = _head_sha(repo, target, base)
            proc = spawn(session_bin, repo, "implementer", dirs[unit], session, dirs[unit] / "brief.md",
                         sessions_root, extra_args, ref=head_ref, dry_run=dry_run)
            record.spawned = not dry_run
            record.exit = proc.returncode if proc else None
            record.wall_seconds = _wall(proc)
            return record

        def finish(unit: str, record: UnitRecord):
            sessions[unit] = record.session
            _harvest_unit(repo, base, record.session, contexts[unit], test_files, sessions_root, record,
                          orchestrator, unit)
            # Integrate this one immediately, scoped to the unit's own
            # files (C-38 enforced at the cut).
            _integrate_one(repo, target, unit, record.session, integ, _manifest_paths(contexts[unit], test_files))
            records.append(record)
            stage_log.append(_unit_stage("implement", unit, record))
            done.add(unit)

        # Human-first units are never spawned; they count as done for
        # their consumers (the orchestrator's inbox says why).
        for unit in list(pending):
            if contexts[unit].get("human_first"):
                record = UnitRecord(unit=unit, role="implementer", session=f"{task}-{unit.lower()}", spawned=False)
                record.reason = "human-first: not spawned — " + contexts[unit].get("human_first_reason", "")
                mail.post(orchestrator, unit, record.reason, kind="human-first")
                records.append(record)
                pending.remove(unit)
                done.add(unit)

        # Task-tailored selection (ADR-064): on the planner path a unit
        # the planner named nothing in is not brought in at all — the
        # re-probe showed such units burn a session to plan editing
        # someone else's file. A skipped unit counts as done so its
        # consumers still become ready. On the lexical fallback there is
        # no per-unit naming, so every unit stays (the seeds are the
        # whole signal). C-52.
        plan_stage = next((st for st in stage_log if st.get("stage") == "plan"), None)
        if seed_source == "planner" and plan_stage:
            for unit in list(pending):
                if not unit_has_planner_work(plan_stage, contexts[unit]):
                    record = UnitRecord(unit=unit, role="implementer",
                                        session=f"{task}-{unit.lower()}", spawned=False)
                    record.reason = ("not spawned — the planner named no file in this unit's "
                                     "interior (task-tailored selection, ADR-064)")
                    mail.post(orchestrator, unit, record.reason, kind="not-selected")
                    records.append(record)
                    pending.remove(unit)
                    done.add(unit)

        # Waves over the contract DAG (ADR-063): every unit whose owners
        # are integrated may run at once, up to *workers*; each finishes
        # on this thread (harvest + scoped integration are serial), which
        # may free the next wave. workers == 1 is exactly the old order.
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            running: dict = {}
            while pending or running:
                ready = parallel.ready_units(pending, done, deps)
                if not ready and not running and pending:
                    ready = [pending[0]]  # cycle: by order, as order_units breaks it
                started_now = []
                for unit in ready:
                    if len(running) >= max(1, workers):
                        break
                    pending.remove(unit)
                    running[pool.submit(start, unit)] = unit
                    started_now.append(unit)
                if started_now:
                    waves.append(started_now)
                if not running:
                    continue
                finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for fut in finished:
                    unit = running.pop(fut)
                    finish(unit, fut.result())
        implement_wall = round(time.monotonic() - implement_started, 3)

    review = {"skipped": "dry run" if dry_run else "not run"}
    if not dry_run and integ["merged"]:
        review = review_integration(repo, base, target)

    # 5. verify — a read-only session over the integrated head.
    verify: dict = {"skipped": "not requested"}
    reworked = 0
    if "verify" in stages and not dry_run and integ["merged"]:
        verify = run_verifier(repo, task, _head_sha(repo, target, base), planner_tests, spec, pdir,
                              session_bin, sessions_root, extra_args, brief_limit, dry_run, test_files=test_files)
        stage_log.append(verify["stage"])
        while (verify.get("verdict") == "fail" and "rework" in stages and reworked < max_rework):
            reworked += 1
            _run_rework(repo, task, target, base, verify, spec, contexts, test_files, dirs,
                        orchestrator, records, sessions, integ, session_bin, sessions_root,
                        extra_args, brief_limit, stage_log)
            verify = run_verifier(repo, task, _head_sha(repo, target, base), planner_tests, spec, pdir,
                                  session_bin, sessions_root, extra_args, brief_limit, dry_run, attempt=reworked + 1,
                                  test_files=test_files)
            stage_log.append(verify["stage"])

    contract_failures = len(integ.get("failed", []))
    record_doc = {
        "task": task, "proposal": proposal, "base": base,
        "graph_sha": spec.get("graph_sha", ""), "order": order, "selected": order,
        "seed_source": seed_source, "seeds": spec.get("seeds", {}),
        "units_not_selected": [r.unit for r in records if r.reason and "task-tailored selection" in r.reason],
        "planner_unresolved": planner_misses,
        "units_deferred": [u.get("name") for u in spec.get("units_deferred", [])],
        "stages": stage_log,
        "units": [{**r.__dict__, "fault_rate": round(r.fault_rate, 4)} for r in records],
        "contracts": len(spec.get("contracts", [])),
        "integration": integ, "review": review, "verify": verify,
        "rework": reworked,
        # Outside-measured: with parallel units the sum of per-unit walls
        # overstates the stage (ADR-063); this is what the clock saw.
        "implement_wall_seconds": implement_wall,
        "parallel": {"workers": max(1, workers), "waves": waves},
        "loss": loss(records, contract_failures),
    }
    (pdir / "partition-record.json").write_text(json.dumps(record_doc, indent=2, sort_keys=True) + "\n")
    return record_doc


def _unit_stage(stage: str, unit: str, record: UnitRecord) -> dict:
    """An implementer's entry in the stage log: the same session the
    unit record names, so the bench adapter can find its meter."""
    return {"stage": stage, "role": "implementer", "agent": unit, "unit": unit,
            "session": record.session, "exit": record.exit, "wall_seconds": record.wall_seconds,
            "commits": record.commits, "files_changed": list(record.files_changed)}


def artifacts_spec(repo: Path, task: str) -> dict:
    from hobbes.run.spec import load_spec
    return load_spec(repo, task)


def term_modules(graph: dict, terms: list[str]) -> dict[str, str | None]:
    """Each planner-named term → the module id it resolves to (``None``
    when it does not), the same tolerant lookup :func:`resolve_terms`
    uses. Kept on the plan stage so the handoff can be projected per
    unit (ADR-062)."""
    lookup = build_lookup(graph, dotted_head=True)
    out: dict[str, str | None] = {}
    for term in terms:
        cleaned = (term or "").strip()
        if cleaned and cleaned not in out:
            out[cleaned] = lookup(cleaned)
    return out


def _in_interior(term: str, module: str | None, ids: set[str], paths: list[str]) -> bool:
    if module in ids:
        return True
    bare = term.strip().lstrip("./")
    return any(p == bare or p.endswith("/" + bare) or bare.endswith("/" + p) for p in paths if p)


def planner_slice(plan: dict, context: dict) -> tuple[list[str], list[str]]:
    """Split the planner's named terms into (in this unit's interior,
    owned elsewhere). A term is the unit's when it resolved to one of
    its interior modules or path-matches one of its interior files."""
    ids = {m.get("id") for m in context.get("modules", [])}
    paths = [m.get("path", "") for m in context.get("modules", [])]
    terms = plan.get("terms") or {}
    named = [t for t in plan.get("files", []) + plan.get("symbols", []) if t and t.strip()]
    mine, others = [], []
    for term in dict.fromkeys(t.strip() for t in named):
        (mine if _in_interior(term, terms.get(term), ids, paths) else others).append(term)
    return mine, others


def unit_has_planner_work(plan_stage: dict, context: dict) -> bool:
    """True when the planner named at least one file/symbol in this
    unit's interior (ADR-064). A unit for which this is false is not
    brought into a planner-seeded run — it would only plan editing
    another unit's file."""
    mine, _ = planner_slice(plan_stage, context)
    return bool(mine)


def _planner_note(seed_source: str, stage_log: list[dict], context: dict | None = None) -> str:
    """The planner's handoff as ONE unit's short memory (ADR-062): its
    slice of the change, the approach, and a plain statement that the
    rest is owned elsewhere — or that nothing named lies in its interior.
    Without *context* the whole handoff is returned (the pre-062 shape)."""
    if seed_source != "planner":
        return ""
    plan = next((s for s in stage_log if s.get("stage") == "plan"), None)
    if not plan:
        return ""
    approach = (plan.get("approach") or "").strip() or plan.get("handoff", "").strip()[:600]
    tests = "run these tests: " + ", ".join(plan["tests"]) if plan.get("tests") else ""
    if context is None:
        return "\n".join(p for p in [f"planner: {plan['handoff'].strip()[:800]}", tests] if p)
    mine, others = planner_slice(plan, context)
    parts = []
    if mine:
        parts.append("planner: your slice of the change — the planner named these IN YOUR INTERIOR: "
                     + ", ".join(mine) + ". Edit those paths (see Interior below).")
    else:
        parts.append("planner: nothing the planner named lies in your interior. It named: "
                     + (", ".join(others[:8]) + (" …" if len(others) > 8 else "") or "nothing") +
                     " — all owned by other units. You are in the plan because the graph reaches "
                     "you from the change: change a file here only if a contract at your boundary "
                     "requires it; otherwise hand off that no change was needed. Do not create or "
                     "edit files outside your interior — they are dropped at integration.")
    if approach:
        parts.append(f"approach: {approach[:600]}")
    if mine and others:
        parts.append(f"the planner also named {len(others)} location(s) owned by other units ("
                     + ", ".join(others[:8]) + (" …" if len(others) > 8 else "") +
                     "): not yours — do not create or edit them; edits outside your interior are "
                     "dropped at integration.")
    if tests:
        parts.append(tests)
    return "\n".join(parts)


def _harvest_unit(repo, base, session, context, test_files, sessions_root, record, orchestrator, unit):
    session_dir = sessions_root / session
    read_flight(session_dir, record)
    reflected = mail.reflections(session_dir)
    record.reflections = [m.get("text", "") for m in reflected]
    mail.fold_back(orchestrator, unit, reflected)
    read_branch(repo, base, session, _manifest_paths(context, test_files), record)


def _manifest_paths(context: dict, test_files: dict[str, str]) -> set[str]:
    """A unit's write scope: its interior module paths plus the files of
    the tests it guards. The partition makes interiors disjoint, so a
    file belongs to at most one unit — which is why scoping the harvest
    to these paths lets no two units write the same file."""
    paths = {m["path"] for m in context.get("modules", []) if m.get("path")}
    paths |= {test_files[t] for t in context.get("guarding_tests", []) if test_files.get(t)}
    return paths


def _integrate_one(repo: Path, target: str, unit: str, session: str, integ: dict,
                   allowed: set[str] | None = None) -> None:
    """Integrate one unit's contribution onto the running target,
    **scoped to its manifest paths** (C-38 enforced at the cut, not just
    measured as rework). The unit branch was cloned from the current
    target, so ``target..branch`` is exactly the unit's own change; we
    take only the part of it that touches files the unit owns and apply
    that to the target. Files the model wrote outside its scope — a
    neighbour's source (the astropy probe's four units that all created
    ``wcsapi.py``) or a scratch note (``session_commit.txt``) — never
    enter the candidate patch, and no other unit can be clobbered."""
    branch = f"hobbes/{session}"
    if not _branch_exists(repo, branch):
        return
    # The unit's change is what it did since it was cloned — the
    # merge-base, not the target's tip, which may have advanced under a
    # parallel unit (ADR-063). Its scoped files are disjoint from
    # anything that landed meanwhile, so the base-relative patch still
    # applies onto the tip; a failure is a real conflict at the cut.
    code, merge_base = _git(repo, "merge-base", target, branch)
    since = merge_base if code == 0 and merge_base else target
    # What the unit changed, and what of it is out of scope (dropped).
    _, names = _git(repo, "diff", "--name-only", f"{since}..{branch}")
    changed = [n for n in names.splitlines() if n]
    dropped = sorted(n for n in changed if allowed is not None and n not in allowed)
    if dropped:
        integ.setdefault("dropped", {})[unit] = dropped
    # The in-scope diff. With no manifest (allowed None) fall back to the
    # whole change, preserving the pre-C-38 behaviour for callers that
    # pass no scope. Captured raw (bytes) — _git strips and merges
    # stderr, which corrupts a patch's trailing newline.
    diff_args = ["diff", "--binary", f"{since}..{branch}"]
    if allowed is not None:
        in_scope = sorted(n for n in changed if n in allowed)
        if not in_scope:
            integ.setdefault("empty", []).append(unit)
            return
        diff_args += ["--", *in_scope]
    proc = subprocess.run(["git", "-C", str(repo), *diff_args], capture_output=True)
    patch = proc.stdout
    if proc.returncode != 0 or not patch.strip():
        integ.setdefault("empty", []).append(unit)
        return
    tmp = repo / ".hobbes" / "plans" / target.split("/", 1)[-1] / ".integrate"
    shutil.rmtree(tmp, ignore_errors=True)
    code, out = _git(repo, "worktree", "add", "-q", "--detach", str(tmp), target)
    if code != 0:
        integ["failed"].append({"unit": unit, "branch": branch, "error": out[-400:]})
        return
    try:
        # The scoped diff touches only this unit's files, so it applies
        # cleanly (no 3-way needed) — a failure here is a real conflict at
        # the cut (two units guarded by one test file both edited it).
        ap = subprocess.run(["git", "-C", str(tmp), "apply", "--whitespace=nowarn"],
                            input=patch, capture_output=True)
        if ap.returncode == 0:
            _git(tmp, "add", "-A")
            _git(tmp, "-c", "user.name=hobbes", "-c", "user.email=hobbes@local",
                 "commit", "-q", "-m", f"integrate {unit} ({branch}, scoped)")
            _git(tmp, "branch", "-f", target, "HEAD")
            integ["merged"].append(unit)
        else:
            integ["failed"].append({"unit": unit, "branch": branch,
                                    "error": ap.stderr.decode(errors="replace")[-400:]})
    finally:
        _git(repo, "worktree", "remove", "--force", str(tmp))
        shutil.rmtree(tmp, ignore_errors=True)
    return


def run_review(repo, spec, pdir, session_bin, sessions_root, extra_args, brief_limit, dry_run) -> dict:
    """A reviewer session judges the change-spec; ``amend`` is recorded
    (the re-plan is a future step — the base records the verdict)."""
    directory = agents.agent_dir(pdir, "reviewer")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / mail.INBOX).touch()
    (directory / "policy.yaml").write_text(json.dumps(
        {"version": 1, "scope": "agent", "default": "escalate", "rules": [
            {"pattern": "git commit*", "decision": "deny", "reason": "a reviewer writes nothing"}]}))
    brief = "\n".join([
        "You are a single-use plan reviewer. You change nothing. Read the change-spec below and",
        "judge whether the units and their assigned files match the proposal.",
        "", f"## Proposal\n{spec.get('proposal', '')}", "",
        "## Units",
        "\n".join(
            f"- {u['name']}: " + ", ".join(
                m['path'] for m in next((x for x in spec['contexts'] if x['unit'] == u['name']), {}).get('modules', [])
                if m.get('path'))
            for u in spec.get("units", [])),
        "", "## Your handoff (reflect kind \"handoff\")",
        "verdict: approve or amend", "reason: one line",
    ])
    (directory / "brief.md").write_text(brief)
    session = f"{spec['task']}-reviewer"
    proc = spawn(session_bin, repo, "reviewer", directory, session, directory / "brief.md",
                 sessions_root, extra_args, ref=None, dry_run=dry_run)
    chosen, _ = mail.handoff(mail.reflections(sessions_root / session))
    parsed = parse_handoff(chosen.get("text", "") if chosen else "")
    return {"verdict": parsed.get("verdict", ""), "stage": {
        "stage": "review", "role": "reviewer", "agent": "reviewer", "session": session,
        "exit": proc.returncode if proc else None, "wall_seconds": _wall(proc),
        "verdict": parsed.get("verdict", ""), "verdict_source": parsed.get("verdict_source"),
        "reason": parsed.get("reason", "")}}


def resolve_tests(named: list[str], test_files: dict[str, str]) -> tuple[list[str], list[str]]:
    """Map a planner's named tests to what the repo actually has: a test
    id, a file path, or a bare filename / path suffix matching exactly
    one test file. Returns (resolved, unresolved). The probe's verifier
    ran ``pytest test_intermediate_transformations.py`` at the root and
    found nothing — the planner had named the file bare."""
    files = sorted(set(test_files.values()))
    ids = set(test_files)
    resolved: list[str] = []
    unresolved: list[str] = []
    for name in named:
        n = name.strip().strip("`'\"")
        if not n:
            continue
        base = n.split("::", 1)[0]
        if n in ids or base in files:
            hit = n
        else:
            suffix = [f for f in files if f == base or f.endswith("/" + base)]
            if len(suffix) != 1:
                stem = [f for f in files if f.rsplit("/", 1)[-1] == base.rsplit("/", 1)[-1]]
                suffix = stem if len(stem) == 1 else suffix
            if len(suffix) == 1:
                hit = suffix[0] + (n[len(base):] if "::" in n else "")
            else:
                unresolved.append(n)
                continue
        if hit not in resolved:
            resolved.append(hit)
    return resolved, unresolved


def run_verifier(repo, task, head, planner_tests, spec, pdir, session_bin, sessions_root,
                 extra_args, brief_limit, dry_run, attempt: int = 1, test_files: dict[str, str] | None = None) -> dict:
    """A verifier session over the integrated head: run the guarding
    tests and hand off pass/fail. Read-only worktree — the brief tells it
    to keep pytest from writing (``-p no:cacheprovider``); a write-denied
    failure is the harness's, classified ``verifier-env``, not a fail."""
    directory = agents.agent_dir(pdir, f"verifier-{attempt}")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / mail.INBOX).touch()
    (directory / "policy.yaml").write_text(json.dumps(
        {"version": 1, "scope": "agent", "default": "escalate", "rules": [
            {"pattern": "git commit*", "decision": "deny", "reason": "a verifier writes nothing"}]}))
    guards = sorted({t for c in spec.get("contexts", []) for t in _guard_files(c, spec)})
    tests, tests_unresolved = resolve_tests(planner_tests, test_files or {}) if test_files is not None else (list(planner_tests), [])
    tests = tests or guards
    brief = "\n".join([
        "You are a single-use verifier. You change nothing; you run the tests and report.",
        "", f"## Proposal\n{spec.get('proposal', '')}", "",
        "## Run these tests (through the exec tool)",
        "\n".join(f"- {t}" for t in tests) or "- none named; run the repo's test suite for the changed area",
        *( ["", "Named but not found in the repo (do not guess a path; say so if nothing else runs): "
            + ", ".join(tests_unresolved)] if tests_unresolved else []),
        "", "## Important",
        "- The worktree is read-only. Run pytest with `-p no:cacheprovider` and do not write files.",
        "- If a test cannot run because the tree is read-only, say so in `reason` — that is not a fail.",
        "", "## Your handoff (reflect kind \"handoff\")",
        "verdict: pass or fail", "units: the units to redo if fail (optional)", "reason: what failed",
    ])
    (directory / "brief.md").write_text(brief)
    session = f"{task}-verifier-{attempt}"
    proc = spawn(session_bin, repo, "verifier", directory, session, directory / "brief.md",
                 sessions_root, extra_args, ref=head, dry_run=dry_run)
    log = (proc.stdout + proc.stderr) if proc else ""
    chosen, _ = mail.handoff(mail.reflections(sessions_root / session))
    parsed = parse_handoff(chosen.get("text", "") if chosen else "")
    verdict = parsed.get("verdict", "")
    # A read-only-mount failure is the harness's, not the model's.
    reason = parsed.get("reason", "")
    if verdict == "fail" and ("Read-only file system" in log or "EROFS" in reason or "read-only" in reason.lower()):
        verdict, environment_flag = "verifier-env", True
    else:
        environment_flag = False
    return {"verdict": verdict, "units": parsed.get("units", []), "reason": reason,
            "verdict_source": parsed.get("verdict_source"),
            "stage": {"stage": "verify", "role": "verifier", "agent": f"verifier-{attempt}",
                      "session": session, "attempt": attempt,
                      "exit": proc.returncode if proc else None, "wall_seconds": _wall(proc), "verdict": verdict,
                      "verdict_source": parsed.get("verdict_source"), "reason": reason,
                      "verifier_env": environment_flag, "tests": tests, "tests_unresolved": tests_unresolved}}


def _run_rework(repo, task, target, base, verify, spec, contexts, test_files, dirs,
                orchestrator, records, sessions, integ, session_bin, sessions_root,
                extra_args, brief_limit, stage_log: list[dict]) -> None:
    """One implementer redoes the unit(s) the verifier named, its inbox
    the verifier's handoff. Chained on the current target like the first
    pass."""
    named = [u for u in (verify.get("units") or []) if u in dirs] or [r.unit for r in records if r.spawned]
    for unit in named[:2]:
        session = f"{task}-{unit.lower()}-rw"
        sessions[unit] = session
        record = UnitRecord(unit=unit, role="implementer", session=session, spawned=False)
        mail.post(dirs[unit], "verifier", f"the verifier failed this: {verify.get('reason', '')}", kind="handoff")
        inbox = mail.read(dirs[unit])
        brief = agents.render_brief(spec, unit, "implementer", inbox, session, limit=brief_limit)
        (dirs[unit] / "brief.md").write_text(brief)
        proc = spawn(session_bin, repo, "implementer", dirs[unit], session, dirs[unit] / "brief.md",
                     sessions_root, extra_args, ref=_head_sha(repo, target, base), dry_run=False)
        record.spawned = True
        record.exit = proc.returncode if proc else None
        record.wall_seconds = _wall(proc)
        _harvest_unit(repo, base, session, contexts[unit], test_files, sessions_root, record, orchestrator, unit)
        _integrate_one(repo, target, unit, session, integ, _manifest_paths(contexts[unit], test_files))
        records.append(record)
        stage_log.append(_unit_stage("rework", unit, record))


def _guard_files(context: dict, spec: dict) -> list[str]:
    test_files = {t: t for t in context.get("guarding_tests", [])}
    return list(test_files)
