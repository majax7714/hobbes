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
from hobbes.derive.impact import resolve_terms
from hobbes.run import agents, mail
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
    None on a dry run with no binary). One session at a time — the caller
    blocks on it before starting the next (agent-mapping §3.4). The
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
        hits, planner_misses = resolve_terms(graph, handoff.get("files", []) + handoff.get("symbols", []))
        planner_tests = handoff.get("tests", [])
        stage_log.append({"stage": "plan", "role": "planner", "agent": "planner",
                          **{k: result.get(k) for k in ("session", "exit", "wall_seconds")},
                          "handoff": handoff.get("raw", ""),
                          "files": list(handoff.get("files", [])), "symbols": list(handoff.get("symbols", [])),
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
    # The planner's handoff is the first short memory every implementer gets.
    planner_note = _planner_note(seed_source, stage_log)
    for unit in dirs:
        if planner_note:
            mail.post(dirs[unit], "planner", planner_note, kind="handoff")

    code, head = _git(repo, "rev-parse", "HEAD")
    base = head if code == 0 else spec.get("graph_sha", "")
    contexts = {c["unit"]: c for c in spec.get("contexts", [])}
    test_files = {t["id"]: t.get("file", "") for t in tests_doc.get("tests", [])}
    order = order_units(spec)
    records: list[UnitRecord] = []
    sessions: dict[str, str] = {}
    target = f"hobbes/{task}"
    integ = {"branch": target, "merged": [], "failed": []}

    if "implement" in stages:
        _git(repo, "branch", "-f", target, base)
        for unit in order:
            session = f"{task}-{unit.lower()}"
            sessions[unit] = session
            record = UnitRecord(unit=unit, role="implementer", session=session, spawned=False)
            context = contexts[unit]
            if context.get("human_first"):
                record.reason = "human-first: not spawned — " + context.get("human_first_reason", "")
                mail.post(orchestrator, unit, record.reason, kind="human-first")
                records.append(record)
                continue
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
            _harvest_unit(repo, base, session, context, test_files, sessions_root, record, orchestrator, unit)
            # Integrate this one immediately, onto the running target.
            _integrate_one(repo, target, unit, session, integ)
            records.append(record)
            stage_log.append(_unit_stage("implement", unit, record))

    review = {"skipped": "dry run" if dry_run else "not run"}
    if not dry_run and integ["merged"]:
        review = review_integration(repo, base, target)

    # 5. verify — a read-only session over the integrated head.
    verify: dict = {"skipped": "not requested"}
    reworked = 0
    if "verify" in stages and not dry_run and integ["merged"]:
        verify = run_verifier(repo, task, _head_sha(repo, target, base), planner_tests, spec, pdir,
                              session_bin, sessions_root, extra_args, brief_limit, dry_run)
        stage_log.append(verify["stage"])
        while (verify.get("verdict") == "fail" and "rework" in stages and reworked < max_rework):
            reworked += 1
            _run_rework(repo, task, target, base, verify, spec, contexts, test_files, dirs,
                        orchestrator, records, sessions, integ, session_bin, sessions_root,
                        extra_args, brief_limit, stage_log)
            verify = run_verifier(repo, task, _head_sha(repo, target, base), planner_tests, spec, pdir,
                                  session_bin, sessions_root, extra_args, brief_limit, dry_run, attempt=reworked + 1)
            stage_log.append(verify["stage"])

    contract_failures = len(integ.get("failed", []))
    record_doc = {
        "task": task, "proposal": proposal, "base": base,
        "graph_sha": spec.get("graph_sha", ""), "order": order, "selected": order,
        "seed_source": seed_source, "seeds": spec.get("seeds", {}),
        "planner_unresolved": planner_misses,
        "units_deferred": [u.get("name") for u in spec.get("units_deferred", [])],
        "stages": stage_log,
        "units": [{**r.__dict__, "fault_rate": round(r.fault_rate, 4)} for r in records],
        "contracts": len(spec.get("contracts", [])),
        "integration": integ, "review": review, "verify": verify,
        "rework": reworked,
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


def _planner_note(seed_source: str, stage_log: list[dict]) -> str:
    if seed_source != "planner":
        return ""
    plan = next((s for s in stage_log if s.get("stage") == "plan"), None)
    if not plan:
        return ""
    parts = [f"planner: {plan['handoff'].strip()[:800]}"]
    if plan.get("tests"):
        parts.append("run these tests: " + ", ".join(plan["tests"]))
    return "\n".join(parts)


def _harvest_unit(repo, base, session, context, test_files, sessions_root, record, orchestrator, unit):
    session_dir = sessions_root / session
    read_flight(session_dir, record)
    reflected = mail.reflections(session_dir)
    record.reflections = [m.get("text", "") for m in reflected]
    mail.fold_back(orchestrator, unit, reflected)
    manifest_paths = {m["path"] for m in context.get("modules", []) if m.get("path")}
    manifest_paths |= {test_files[t] for t in context.get("guarding_tests", []) if test_files.get(t)}
    read_branch(repo, base, session, manifest_paths, record)


def _integrate_one(repo: Path, target: str, unit: str, session: str, integ: dict) -> None:
    """Merge one harvested unit branch onto the running target in a
    detached worktree; a conflict is recorded at the cut, never guessed."""
    branch = f"hobbes/{session}"
    if not _branch_exists(repo, branch):
        return
    tmp = repo / ".hobbes" / "plans" / target.split("/", 1)[-1] / ".integrate"
    shutil.rmtree(tmp, ignore_errors=True)
    code, out = _git(repo, "worktree", "add", "-q", "--detach", str(tmp), target)
    if code != 0:
        integ["failed"].append({"unit": unit, "branch": branch, "error": out[-400:]})
        return
    try:
        code, out = _git(tmp, "-c", "user.name=hobbes", "-c", "user.email=hobbes@local",
                         "merge", "--no-ff", "-q", "-m", f"integrate {unit} ({branch})", branch)
        if code == 0:
            # HEAD is the *worktree's* — the repo's HEAD is the user's checkout.
            _git(tmp, "branch", "-f", target, "HEAD")
            integ["merged"].append(unit)
        else:
            _git(tmp, "merge", "--abort")
            integ["failed"].append({"unit": unit, "branch": branch, "error": out[-400:]})
    finally:
        _git(repo, "worktree", "remove", "--force", str(tmp))
        shutil.rmtree(tmp, ignore_errors=True)


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


def run_verifier(repo, task, head, planner_tests, spec, pdir, session_bin, sessions_root,
                 extra_args, brief_limit, dry_run, attempt: int = 1) -> dict:
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
    tests = planner_tests or guards
    brief = "\n".join([
        "You are a single-use verifier. You change nothing; you run the tests and report.",
        "", f"## Proposal\n{spec.get('proposal', '')}", "",
        "## Run these tests (through the exec tool)",
        "\n".join(f"- {t}" for t in tests) or "- none named; run the repo's test suite for the changed area",
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
                      "verifier_env": environment_flag, "tests": tests}}


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
        _integrate_one(repo, target, unit, session, integ)
        records.append(record)
        stage_log.append(_unit_stage("rework", unit, record))


def _guard_files(context: dict, spec: dict) -> list[str]:
    test_files = {t: t for t in context.get("guarding_tests", [])}
    return list(test_files)
