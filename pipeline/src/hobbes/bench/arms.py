"""The two arms (ADR-055): Hobbes as a harness, and the model pure.

Both start from the same checkout (:mod:`hobbes.bench.workspace`) and
end in a candidate patch; everything between is what the comparison
measures.

**Harness arm.** ``ingest`` → ``plan`` → ``run`` → patch, exactly the
commands a human runs (ADR-051/054), with the issue text as the
proposal. The seeds are lexical (C-36): an instance whose issue names
no identifier the graph knows seeds nothing, and that is recorded as
the harness outcome ``no-seed`` — a failure of the harness arm, counted
against it, never dropped from the denominator (dropping it would
inflate the arm the benchmark exists to test). Every unit's session
runs in the ADR-018 sandbox through ``hobbes-session``; the partition
record, the plan summary, and the per-unit meters ride the record.

**Pure arm.** Claude Code on the same checkout with its own tools and
nothing of Hobbes — no MCP server, no policy, no derived context — the
issue text as the prompt. It runs where ``claude`` runs, on the host,
with shell access to the checkout (the benchmark repo's code can run;
the containment of the pure arm is an owner decision recorded with
ADR-055, not a default taken here). The result envelope is the meter.

Neither arm interprets its result. The verdict is the benchmark's
(:mod:`hobbes.bench.verdict`).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from hobbes.bench import accounting
from hobbes.bench.instances import Instance
from hobbes.bench.workspace import candidate_patch
from hobbes.bench.environment import Environment
from hobbes.narrate.runner import CLAUDE_BIN_ENV

#: The owned agent loop (ADR-056): one stdlib-only file, run by the host
#: python for the pure arm and copied into the sandbox for the harness arm.
LOOP_PATH = Path(__file__).resolve().parent.parent / "agent" / "loop.py"

#: The solo/benchmark session floor (ADR-057): a benchmark checkout is a
#: committed-only clone, so the repo and role policies never reach the
#: session, and there is no human to approve escalations. This box policy
#: grants a solo implementer the tests-and-commit it needs while the
#: specific guarantees stay denied — passed to ``hobbes-session --box``.
BENCH_BOX = Path(__file__).resolve().parent / "bench.box.policy"

#: How long an escalated command parks before expire-to-deny on the solo
#: path. Short by design: no human approves, so parking is dead time.
BENCH_ESCALATION = "5s"
RUNTIMES = ("claude", "openai")


@dataclass
class Runtime:
    """Which loop the arms run on. ``claude`` is Claude Code; ``openai``
    is :mod:`hobbes.agent.loop` against an OpenAI-compatible endpoint
    (``base_url`` required) — the small-model ladder's runtime."""

    kind: str = "claude"
    base_url: str = ""
    api_key_env: str = "HOBBES_LLM_API_KEY"
    max_turns: int = 60

    def __post_init__(self) -> None:
        if self.kind not in RUNTIMES:
            raise ValueError(f"runtime must be one of {RUNTIMES}, not {self.kind!r}")
        if self.kind == "openai" and not self.base_url:
            raise ValueError("the openai runtime needs a base_url")

    def session_args(self) -> list[str]:
        """Flags for ``hobbes-session`` so the harness arm runs the same loop."""
        if self.kind != "openai":
            return []
        return ["--runtime", str(LOOP_PATH), "--llm-base-url", self.base_url]

#: Harness-arm outcome classes — the error stream ADR-052 asked for.
HARNESS_OUTCOMES = ("patch", "empty-patch", "no-seed", "plan-error", "run-error", "ingest-error", "env-error")
PURE_OUTCOMES = ("patch", "empty-patch", "claude-error", "env-error")


@dataclass
class ArmResult:
    """What one arm produced for one instance."""

    arm: str
    model: str
    outcome: str
    patch: str = ""
    usage: accounting.Usage = field(default_factory=accounting.Usage)
    detail: dict = field(default_factory=dict)
    error: str = ""

    @property
    def patch_files(self) -> list[str]:
        return sorted({
            line.split(" b/", 1)[1] for line in self.patch.splitlines()
            if line.startswith("diff --git ") and " b/" in line
        })


def _classify_patch(patch: str) -> str:
    return "patch" if patch.strip() else "empty-patch"


def pure_prompt(instance: Instance) -> str:
    """The pure arm's prompt: the issue, and the one instruction the
    benchmark protocol needs (a diff of the tree is the answer)."""
    return (
        f"You are working in a checkout of {instance.repo} at commit "
        f"{instance.base_commit[:12]}. Resolve the issue below by changing "
        "the code in this working tree. Do not commit, push, or create "
        "branches; the diff of the working tree is your answer.\n\n"
        f"{instance.problem_statement.strip()}\n"
    )


def run_pure_arm(
    instance: Instance,
    workspace: Path,
    model: str,
    timeout: float = 3600.0,
    permission_mode: str = "acceptEdits",
    allowed_tools: str = "Bash,Edit,Write,Read,Glob,Grep",
    runtime: Runtime | None = None,
    environment: Environment | None = None,
    network: str = "pasta",
) -> ArmResult:
    """The model, pure, on *workspace*: Claude Code (``HOBBES_CLAUDE_BIN``
    names the binary — the narrate runner's precedent and the tests'
    stand-in), or the owned loop with bash and file tools when
    *runtime* is ``openai``. With an *environment* (ADR-058) the owned
    loop runs inside the benchmark's image over the mounted workspace
    — the same binding the harness arm gets, so the arms differ in
    Hobbes and nothing else."""
    runtime = runtime or Runtime()
    bin_ = os.environ.get(CLAUDE_BIN_ENV, "claude")
    if runtime.kind == "openai" and environment is not None:
        loop = ["--base-url", runtime.base_url, "--model", model, "--api-key-env", runtime.api_key_env,
                "--prompt", pure_prompt(instance), "--workdir", "/work", "--max-turns", str(runtime.max_turns)]
        inner = [environment.runtime_python, "/hobbes/loop.py", *loop]
        if environment.pre:
            inner = ["/bin/sh", "-c", environment.pre + ' && exec "$@"', "hobbes-pre", *inner]
        cmd = ["podman", "run", "--rm", "--network", network, "--env", "HOME=/tmp",
               *environment.podman_env(),
               "--env", f"{runtime.api_key_env}={os.environ.get(runtime.api_key_env, '')}",
               "-v", f"{Path(workspace).resolve()}:/work:rw,z",
               "-v", f"{LOOP_PATH}:/hobbes/loop.py:ro,z",
               "--workdir", "/work", environment.image, *inner]
    elif runtime.kind == "openai":
        cmd = [sys.executable, str(LOOP_PATH), "--base-url", runtime.base_url, "--model", model,
               "--api-key-env", runtime.api_key_env, "--prompt", pure_prompt(instance),
               "--workdir", str(workspace), "--max-turns", str(runtime.max_turns)]
    else:
        cmd = [bin_, "-p", pure_prompt(instance), "--output-format", "json",
               "--permission-mode", permission_mode, "--allowedTools", allowed_tools]
        if model:
            cmd += ["--model", model]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(workspace), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return ArmResult("pure", model, "claude-error", error=f"claude binary not found ({bin_!r})")
    except subprocess.TimeoutExpired:
        return ArmResult("pure", model, "claude-error", error=f"claude timed out after {timeout:.0f}s",
                         usage=accounting.Usage(wall_seconds=timeout, envelopes=0))
    elapsed = time.monotonic() - started
    usage = accounting.from_text(proc.stdout)
    if usage.wall_seconds is None:
        usage.wall_seconds = round(elapsed, 3)
    (Path(workspace) / ".hobbes").mkdir(exist_ok=True)
    (Path(workspace) / ".hobbes" / "pure-arm.log").write_text(proc.stdout + proc.stderr)
    patch = candidate_patch(workspace, instance.base_commit)
    detail = {"exit": proc.returncode, "turns": usage.turns, "runtime": runtime.kind}
    if environment is not None:
        detail["environment"] = environment.to_dict()
    result = ArmResult("pure", model, _classify_patch(patch), patch=patch, usage=usage, detail=detail)
    if proc.returncode != 0:
        result.outcome = "claude-error" if not patch.strip() else result.outcome
        result.error = (proc.stderr or proc.stdout).strip()[-400:]
    return result


def run_harness_arm(
    instance: Instance,
    workspace: Path,
    model: str,
    session_bin: str | None = None,
    sessions_root: Path | None = None,
    extra_session_args: list[str] | None = None,
    environment: Environment | None = None,
    max_units: int | None = None,
    budget: int | None = None,
    seeds: list[str] | None = None,
    runtime: Runtime | None = None,
) -> ArmResult:
    """``ingest`` → ``plan`` → ``run`` → patch on *workspace*. The
    sessions run on *runtime* (Claude Code, or the owned loop through
    ``hobbes-session --runtime``)."""
    runtime = runtime or Runtime()
    from hobbes import artifacts
    from hobbes.derive import DeriveError, derive_plan, write_spec
    from hobbes.derive.changespec import ComplementError
    from hobbes.derive.impact import SeedError
    from hobbes.derive.manifests import GuaranteeError
    from hobbes.extract import ingest
    from hobbes.extract.emit import StampError
    from hobbes.extract.packs import PackRefusal
    from hobbes.invariants import ValidationError
    from hobbes.run import RunError, run_task

    workspace = Path(workspace)
    detail: dict = {"model": model, "runtime": runtime.kind}
    started = time.monotonic()
    try:
        ingest(workspace)
    except PackRefusal:
        # P10: a refusal is a specific guarantee; the arm's catch-all
        # below must not absorb it into an outcome class.
        raise
    except (StampError, Exception) as exc:  # noqa: BLE001 — recorded as the arm's outcome
        return ArmResult("harness", model, "ingest-error", error=f"{type(exc).__name__}: {exc}")
    graph = artifacts.load_graph(workspace)
    detail["ingest"] = {
        "languages": graph.get("languages", []),
        "nodes": len(graph.get("nodes", [])),
        "call_edges": len(graph.get("symbol_edges", [])),
        "capture": _capture(graph),
    }
    try:
        kwargs = {"seeds": seeds or [], "max_units": max_units}
        if budget:
            kwargs["budget"] = budget
        spec = derive_plan(workspace, instance.problem_statement, **kwargs)
    except SeedError as exc:
        detail["plan"] = {"unresolved_terms": _unresolved_from(str(exc))}
        return ArmResult("harness", model, "no-seed", detail=detail, error=str(exc))
    except (DeriveError, GuaranteeError, ComplementError, ValidationError, artifacts.ArtifactError) as exc:
        return ArmResult("harness", model, "plan-error", detail=detail, error=f"{type(exc).__name__}: {exc}")
    write_spec(workspace, spec)
    detail["plan"] = {
        "task": spec.task,
        "seeds": dict(spec.seeds),
        "unresolved_terms": list(spec.unresolved_terms),
        "units": len(spec.units),
        "max_units": max_units,
        "capped": sum(1 for u in spec.units if any(f.startswith("capped") for f in u.flags)),
        "contracts": len(spec.contracts),
        "human_first": [c.unit for c in spec.contexts if c.human_first],
        "gate": spec.gate.result,
    }
    session_args = solo_session_args(extra_session_args) + runtime.session_args()
    if environment is not None:
        session_args += environment.session_args()
        detail["environment"] = environment.to_dict()
    if model:
        session_args += ["--model", model]
    try:
        record = run_task(workspace, spec.task, session_bin=session_bin,
                          sessions_root=sessions_root, extra_args=session_args)
    except (RunError, artifacts.ArtifactError, Exception) as exc:  # noqa: BLE001
        return ArmResult("harness", model, "run-error", detail=detail, error=f"{type(exc).__name__}: {exc}")
    usage = accounting.Usage()
    from hobbes.run.agents import agent_dir
    from hobbes.run.spec import plan_dir
    pdir = plan_dir(workspace, spec.task)
    for unit in record.get("units", []):
        log = agent_dir(pdir, unit["unit"]) / "session.log"
        if log.is_file():
            usage = usage.add(accounting.from_text(log.read_text()))
    if usage.wall_seconds is None and usage.envelopes == 0:
        # The harness arm's wall time is observable from outside the
        # sessions even when no envelope was emitted inside them.
        usage.wall_seconds = round(time.monotonic() - started, 3)
    detail["run"] = {
        "units": [{k: u[k] for k in ("unit", "spawned", "exit", "knowledge_calls", "context_faults",
                                      "commits", "rework_files", "reflections", "reason")}
                  for u in record.get("units", [])],
        "integration": record.get("integration", {}),
        "review": {k: v for k, v in record.get("review", {}).items() if k in ("needs_attention", "error", "skipped")},
        "loss": record.get("loss", {}),
    }
    branch = record.get("integration", {}).get("branch")
    patch = candidate_patch(workspace, instance.base_commit, ref=branch) if branch and _ref_exists(workspace, branch) else ""
    return ArmResult("harness", model, _classify_patch(patch), patch=patch, usage=usage, detail=detail)


def solo_session_args(extra: list[str] | None) -> list[str]:
    """The benchmark session's floor and escalation backstop, unless the
    caller already set them (a --session-arg wins, so a run can override
    the policy or the timeout deliberately)."""
    args = list(extra or [])
    joined = " ".join(args)
    if "--box" not in joined:
        args += ["--box", str(BENCH_BOX)]
    if "--escalation-timeout" not in joined:
        args += ["--escalation-timeout", BENCH_ESCALATION]
    return args


def _ref_exists(repo: Path, ref: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                          capture_output=True).returncode == 0


def _capture(graph: dict) -> dict[str, float]:
    """Per-language capture (% of detected call sites resolved) from the
    coverage rows — the ingest summary's number, kept on the record so
    a harness failure can be read against how much the graph saw."""
    out: dict[str, list[int]] = {}
    for row in graph.get("resolution_coverage", []):
        lang = row.get("language") or "all"
        sites, unresolved = int(row.get("sites", 0)), int(row.get("unresolved", 0))
        acc = out.setdefault(lang, [0, 0])
        acc[0] += sites
        acc[1] += unresolved
    return {lang: round(100.0 * (s - u) / s, 1) for lang, (s, u) in out.items() if s}


def _unresolved_from(message: str) -> list[str]:
    marker = "unmatched code-shaped terms: "
    if marker not in message:
        return []
    tail = message.split(marker, 1)[1].split(")", 1)[0]
    return [t.strip() for t in tail.split(",") if t.strip()]
