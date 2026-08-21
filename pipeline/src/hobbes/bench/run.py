"""The run: selection → checkout → arms → records → verdicts (ADR-055).

``hobbes bench run`` is a loop, not an agent: for every selected
instance, for every model, for every arm, check the repo out at the
base commit, run the arm, append the record. Afterwards, when asked,
hand every (arm, model) group's patches to the evaluator and write the
verdicts back. A run directory holds ``run.json`` (the selection and
every parameter — the run is reproducible from it), ``records.jsonl``,
the predictions and evaluator logs, and per-instance workspaces under
``work/`` (kept, so a failure can be read in place; ``--clean``
removes them as each instance finishes).

Resumable: an (instance, arm, model) that already has a record is
skipped, so an interrupted run continues where it stopped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from hobbes.bench import arms, results, verdict, workspace
from hobbes.bench.instances import Selection

ARMS = ("pure", "harness")


def _tool_version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()[:80]
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def write_manifest(run_dir: Path, selection: Selection, models: list[str], which: list[str], params: dict) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "selection": selection.to_dict(),
        "models": models,
        "arms": which,
        "params": params,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "claude": _tool_version(["claude", "--version"]),
        "evaluator": f"swebench=={verdict.SWEBENCH_VERSION}",
    }
    (run_dir / "run.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return run_dir / "run.json"


def run(
    run_dir: Path,
    selection: Selection,
    models: list[str],
    which: list[str] = ARMS,
    session_bin: str | None = None,
    sessions_root: Path | None = None,
    session_args: list[str] | None = None,
    budget: int | None = None,
    clean: bool = False,
    timeout: float = 3600.0,
    runtime: arms.Runtime | None = None,
    log=print,
) -> list[results.Record]:
    """Run every (instance, model, arm) not yet recorded; return all records."""
    run_dir = Path(run_dir)
    runtime = runtime or arms.Runtime()
    write_manifest(run_dir, selection, models, list(which), {
        "session_bin": session_bin, "session_args": session_args or [], "budget": budget,
        "timeout": timeout, "clean": clean,
        "runtime": {"kind": runtime.kind, "base_url": runtime.base_url, "max_turns": runtime.max_turns},
    })
    done = {(r.instance_id, r.arm, r.model) for r in results.load(run_dir)}
    for instance in selection.selected:
        for model in models:
            for arm in which:
                if (instance.instance_id, arm, model) in done:
                    continue
                ws = run_dir / "work" / instance.instance_id / f"{arm}-{model or 'default'}".replace("/", "_")
                log(f"{instance.instance_id} [{arm}/{model or 'default'}] checkout {instance.base_commit[:12]}")
                try:
                    workspace.checkout(instance, ws)
                except workspace.WorkspaceError as exc:
                    result = arms.ArmResult(arm, model, "ingest-error" if arm == "harness" else "claude-error",
                                            error=f"checkout: {exc}")
                else:
                    if arm == "pure":
                        result = arms.run_pure_arm(instance, ws, model, timeout=timeout, runtime=runtime)
                    else:
                        result = arms.run_harness_arm(
                            instance, ws, model, session_bin=session_bin, sessions_root=sessions_root,
                            extra_session_args=session_args, budget=budget, runtime=runtime,
                        )
                record = results.make_record(instance, result)
                results.append(run_dir, record)
                log(f"  → {record.outcome}, {len(record.patch_files)} files, "
                    + (f"usage unobserved: {', '.join(record.usage['unobserved'])}"
                       if record.usage["unobserved"] else f"{record.usage['total_tokens']} tokens")
                    + (f"; {record.error[:120]}" if record.error else ""))
                (run_dir / "patches").mkdir(exist_ok=True)
                (run_dir / "patches" / f"{instance.instance_id}.{arm}.{(model or 'default').replace('/', '_')}.diff"
                 ).write_text(result.patch)
                if clean:
                    shutil.rmtree(ws, ignore_errors=True)
    return results.load(run_dir)


def evaluate(run_dir: Path, dataset: str, max_workers: int = 1, timeout: float | None = None, log=print) -> list[results.Record]:
    """Judge every unjudged record through the benchmark's evaluator,
    one call per (arm, model), and write verdicts back."""
    run_dir = Path(run_dir)
    records = results.load(run_dir)
    groups: dict[tuple[str, str], list[results.Record]] = {}
    for r in records:
        if r.solved is None:
            groups.setdefault((r.arm, r.model), []).append(r)
    patches = run_dir / "patches"
    for (arm, model), rs in sorted(groups.items()):
        name = verdict.model_name(arm, model)
        rows = []
        for r in rs:
            path = patches / f"{r.instance_id}.{arm}.{(model or 'default').replace('/', '_')}.diff"
            rows.append({"instance_id": r.instance_id, "model_name_or_path": name,
                         "model_patch": path.read_text() if path.is_file() else ""})
        preds = verdict.write_predictions(run_dir / "eval" / f"{name}.predictions.json", rows)
        run_id = run_dir.name
        log(f"evaluating {len(rows)} {arm}/{model or 'default'} patches ({name}) …")
        try:
            verdicts = verdict.evaluate(dataset, preds, run_id, name, [r.instance_id for r in rs],
                                        cwd=run_dir / "eval", max_workers=max_workers, timeout=timeout)
        except verdict.VerdictError as exc:
            log(f"  evaluator failed: {exc}")
            continue
        for r in rs:
            r.verdict = verdicts.get(r.instance_id, "unjudged")
        log("  " + ", ".join(f"{v} {sum(1 for x in verdicts.values() if x == v)}" for v in verdict.VERDICTS
                            if any(x == v for x in verdicts.values())))
    results.rewrite(run_dir, records)
    return records
