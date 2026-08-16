"""The ``hobbes`` command-line interface.

``ingest`` runs the deterministic extractors into ``.hobbes/derived/``;
``init`` scaffolds the ``.hobbes/`` layout; ``render`` prints the module
graph as Mermaid (ADR-008); ``diff <base>..<head>`` prints the
architecture delta between two refs (ADR-009 — exit 0 no delta / 1
delta / 2 trouble, mirroring diff(1)); ``narrate`` runs the
quota-spending cartographer pass into ``.hobbes/derived/docs/``
(ADR-019/020); ``docs status`` prints stale badges; ``policy resolve``
passes through to the Go ``hobbes-policy`` binary (ADR-003). argparse
per ADR-004.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hobbes import __version__, artifacts, policy

#: Starter repo policy written by `hobbes init` (format per ADR-001).
_STARTER_POLICY = """\
# Repo policy for this repository — see hobbes docs/adr/001 for the format,
# 002 for merge semantics (box -> repo -> folder, deny overrides allow).
version: 1
scope: repo
default: escalate
rules:
  # Terraform state carries secrets: never read, written, or shipped.
  - pattern: "*.tfstate*"
    decision: deny
    reason: "tfstate carries secrets"
"""

#: Lines `hobbes init` guarantees are present in the repo's .gitignore,
#: in addition to the .hobbes/ protection from ADR-012.
_GITIGNORE_LINES = ["*.tfstate", "*.tfstate.*"]


def _detect_repo_root(start: Path) -> Path | None:
    """Walk up from *start* looking for a .git entry (mirrors ADR-003)."""
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _repo_root_from(args: argparse.Namespace) -> Path:
    if args.repo:
        return Path(args.repo).resolve()
    detected = _detect_repo_root(Path.cwd())
    if detected is None:
        raise SystemExit(
            "hobbes: no repo root found (no .git upward from here); pass --repo"
        )
    return detected


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Run the extractors and write the derived artifacts."""
    from hobbes.extract import ingest
    from hobbes.extract.emit import StampError
    from hobbes.extract.packs import PackRefusal
    from hobbes.extract.terraform import PlanError

    from hobbes.extract.emit import ensure_hobbes_ignored

    repo_root = _repo_root_from(args)
    ignored = ensure_hobbes_ignored(repo_root)
    if ignored:
        print(f"{ignored} (Hobbes files stay out of version control, ADR-012)")
    try:
        paths = ingest(repo_root, tf_plan=Path(args.tf_plan) if args.tf_plan else None)
    # PackRefusal is how a pack declines user-supplied input (ADR-035); it
    # reaches here rather than degrading, so `--tf-plan some.tfstate` still
    # exits 1 rather than warning and ingesting (I-1).
    except (StampError, PlanError, PackRefusal) as exc:
        print(f"hobbes ingest: {exc}", file=sys.stderr)
        return 1
    docs = {p.name: json.loads(p.read_text()) for p in paths}
    graph, tests, interfaces = (
        docs["graph.json"],
        docs["tests.json"],
        docs["interfaces.json"],
    )
    dirty = " (dirty tree)" if graph["dirty"] else ""
    languages = ", ".join(graph["languages"])
    print(f"ingested {repo_root} @ {graph['sha'][:12]}{dirty} [{languages}]")
    for degraded in graph.get("extraction_errors", []):
        print(
            f"  WARNING: {degraded['path']}: {degraded['stage']} extraction "
            f"degraded ({degraded['message']})",
            file=sys.stderr,
        )
    print(
        f"  graph.json:      {len(graph['nodes'])} nodes, "
        f"{len(graph['module_edges'])} module edges, "
        f"{len(graph['symbols'])} symbols, "
        f"{len(graph['symbol_edges'])} call edges"
    )
    print(f"  tests.json:      {len(tests['tests'])} tests")
    print(
        f"  interfaces.json: {len(interfaces['routes'])} routes, "
        f"{len(interfaces['cli_entry_points'])} CLI entry points"
    )
    _print_tail_view(graph.get("resolution_coverage", []))
    for path in sorted(paths):
        print(f"  wrote {path}")
    return 0


def _print_tail_view(coverage_rows: list[dict]) -> None:
    """The per-language capture line (ADR-045): accounted share of the
    *detected* call sites — always stated with that denominator — and
    the unresolved tail split into what the graph sees and does not
    model versus what it cannot resolve. This is the honesty line: it
    runs on every ingest, not only during development."""
    from hobbes.extract.tail import NOT_MODELLED, rollup

    for lang, agg in sorted(rollup(coverage_rows).items()):
        sites, unresolved = agg["sites"], agg["unresolved"]
        if not sites:
            continue
        accounted = (sites - unresolved) / sites * 100
        not_modelled = {
            c: n for c, n in agg["tail"].items() if c in NOT_MODELLED
        }
        cannot = {
            c: n for c, n in agg["tail"].items() if c not in NOT_MODELLED
        }
        print(
            f"  capture [{lang}]: {accounted:.1f}% of {sites} detected "
            f"call sites accounted"
        )
        if not_modelled:
            named = ", ".join(f"{c} {n}" for c, n in sorted(not_modelled.items()))
            print(f"    seen, not modelled by design: "
                  f"{sum(not_modelled.values())} ({named})")
        if cannot:
            named = ", ".join(f"{c} {n}" for c, n in sorted(cannot.items()))
            print(f"    cannot resolve: {sum(cannot.values())} ({named})")


def _cmd_init(args: argparse.Namespace) -> int:
    """Scaffold the .hobbes/ layout (architecture §10). Idempotent."""
    from hobbes.extract.emit import ensure_hobbes_ignored

    root = Path(args.repo).resolve() if args.repo else Path.cwd()
    actions: list[str] = []
    ignored = ensure_hobbes_ignored(root)
    if ignored:
        actions.append(f"{ignored} (ADR-012)")

    for sub in ("policies", "invariants"):
        directory = root / ".hobbes" / sub
        if not directory.is_dir():
            directory.mkdir(parents=True)
            actions.append(f"created {directory.relative_to(root)}/")

    repo_policy = root / ".hobbes" / "policies" / "repo.policy"
    if not repo_policy.exists():
        repo_policy.write_text(_STARTER_POLICY)
        actions.append(f"created {repo_policy.relative_to(root)} (starter policy)")

    gitignore = root / ".gitignore"
    existing_text = gitignore.read_text() if gitignore.exists() else ""
    missing = [
        line for line in _GITIGNORE_LINES if line not in existing_text.splitlines()
    ]
    if missing:
        if existing_text and not existing_text.endswith("\n"):
            existing_text += "\n"
        gitignore.write_text(existing_text + "\n".join(missing) + "\n")
        actions.append(f".gitignore: added {', '.join(missing)}")

    if not actions:
        print(f"{root}: .hobbes/ layout already in place, nothing to do")
    else:
        print(f"initialized .hobbes/ in {root}")
        for action in actions:
            print(f"  {action}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Print the ingested module graph as Mermaid (ADR-008)."""
    from hobbes.render import to_mermaid

    repo_root = _repo_root_from(args)
    try:
        graph = artifacts.load_graph(repo_root)
    except artifacts.ArtifactError as exc:
        print(f"hobbes render: {exc}", file=sys.stderr)
        return 1
    print(to_mermaid(graph), end="")
    return 0


def _parse_range(spec: str) -> tuple[str, str]:
    """``base..head`` (bare ``base`` means ``base..HEAD``); rejects ``...``."""
    if "..." in spec:
        raise SystemExit(
            "hobbes diff: three-dot ranges are not supported; use <base>..<head>"
        )
    base, sep, head = spec.partition("..")
    if not base:
        raise SystemExit(f"hobbes diff: invalid range {spec!r}; use <base>..<head>")
    return base, (head if sep and head else "HEAD")


def _cmd_diff(args: argparse.Namespace) -> int:
    """Print the architecture delta between two refs (ADR-009)."""
    from hobbes.graphdiff import (
        RefError,
        diff_graphs,
        extract_at_ref,
        format_delta,
        has_changes,
    )

    repo_root = _repo_root_from(args)
    base_ref, head_ref = _parse_range(args.range)
    try:
        base = extract_at_ref(repo_root, base_ref)
        head = extract_at_ref(repo_root, head_ref)
    except RefError as exc:
        print(f"hobbes diff: {exc}", file=sys.stderr)
        return 2
    delta = diff_graphs(base, head)
    if args.json:
        print(json.dumps(delta, indent=2, sort_keys=True))
    else:
        print(format_delta(delta, base_ref, head_ref), end="")
    return 1 if has_changes(delta) else 0


def _cmd_lanes(args: argparse.Namespace) -> int:
    """Report where the two extraction lanes disagree (§3.4)."""
    from hobbes.artifacts import ArtifactError, load_graph

    repo_root = _repo_root_from(args)
    try:
        graph = load_graph(repo_root)
    except ArtifactError as exc:
        print(f"hobbes lanes: {exc}", file=sys.stderr)
        return 2

    report = graph.get("lane_agreement")
    if report is None:
        print(
            "hobbes lanes: this graph predates the lane-agreement report — "
            "re-run `hobbes ingest`",
            file=sys.stderr,
        )
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if _has_disagreement(report) else 0

    sites = report["sites_compared"]
    site_bad = report["site_disagreements"]
    print(f"lane agreement @ {graph['sha'][:12]}")
    print(
        f"  call sites both lanes resolved: {sites}"
        f" — {len(site_bad)} disagree"
    )
    for row in site_bad[:20]:
        print(f"    {row['file']}:{row['line']} {row['name']}()")
        print(f"      syntactic -> {row['syntactic']}")
        print(f"      semantic  -> {row['semantic']}")
    if len(site_bad) > 20:
        print(f"    ... and {len(site_bad) - 20} more")

    only_a = report["module_edges_lane_a_only"]
    only_b = report["module_edges_lane_b_only"]
    print(
        f"  module edges compared: {report['module_edges_compared']}"
        f" — {len(only_a)} lane A only, {len(only_b)} lane B only"
    )
    for row in only_a[:10]:
        print(f"    lane A only: {row['from']} -> {row['to']}")
    for row in only_b[:10]:
        print(f"    lane B only: {row['from']} -> {row['to']}")
    if not _has_disagreement(report):
        print("  the lanes agree wherever both can answer")
    return 1 if _has_disagreement(report) else 0


def _has_disagreement(report: dict) -> bool:
    """Whether the report contains anything a human must look at.

    Site disagreements only. A module edge one lane alone produced is
    usually the division of labour working — lane B follows a re-export
    to the real definition where lane A stops at the package (ADR-027) —
    so it is reported and does not fail the check.
    """
    return bool(report["site_disagreements"])


def _cmd_narrate(args: argparse.Namespace) -> int:
    """Run the cartographer narrative pass (ADR-019/020). Spends quota."""
    from hobbes.extract.emit import StampError
    from hobbes.narrate import NarrateError, plan_status, run_pass
    from hobbes.narrate.runner import ClaudeRunner

    repo_root = _repo_root_from(args)
    only, exclude = args.only or [], args.exclude or []
    try:
        if args.dry_run:
            rows = plan_status(
                repo_root,
                only=only,
                exclude=exclude,
                invariants=not args.no_invariants,
                force_all=args.all,
            )
            for unit, due, reason in rows:
                marker = "due " if due else "skip"
                print(f"  {marker} {unit.kind:<10} {unit.id} ({reason})")
            due_count = sum(1 for _, due, _ in rows if due)
            print(
                f"narrate --dry-run: {due_count} cartographer calls would run, "
                f"{len(rows) - due_count} fresh"
            )
            return 0
        summary = run_pass(
            repo_root,
            ClaudeRunner(model=args.model),
            only=only,
            exclude=exclude,
            invariants=not args.no_invariants,
            force_all=args.all,
        )
    except (NarrateError, StampError) as exc:
        print(f"hobbes narrate: {exc}", file=sys.stderr)
        return 1
    return 1 if summary["failed"] else 0


def _cmd_docs_status(args: argparse.Namespace) -> int:
    """Print each narrative artifact with its stale badge (§3.3)."""
    from hobbes.narrate import artifact_status

    repo_root = _repo_root_from(args)
    rows = artifact_status(repo_root)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        print("no narrative artifacts — run `hobbes narrate`")
        return 0
    badges = {"fresh": "fresh", "stale": "STALE", "broken": "BROKEN"}
    for row in rows:
        extra = f" ({', '.join(row['changed'])})" if row["changed"] else ""
        print(f"  {badges[row['status']]:<6} {row['kind']:<19} {row['id']}{extra}")
    stale = sum(1 for row in rows if row["status"] != "fresh")
    print(f"docs: {len(rows)} artifacts, {stale} stale")
    return 0


def _cmd_policy_resolve(args: argparse.Namespace) -> int:
    """Pass through to `hobbes-policy resolve`, propagating its exit code."""
    try:
        resolution = policy.resolve(
            args.command_string, dir=args.dir, repo=args.repo, box=args.box
        )
    except policy.PolicyBinaryNotFound as exc:
        print(f"hobbes policy resolve: {exc}", file=sys.stderr)
        return 1
    except policy.PolicyResolveError as exc:
        print(f"hobbes policy resolve: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(resolution.raw, indent=2))
    return resolution.exit_code


def _load_invariants(repo_root, strict_guards: bool = True):
    """Load records, checking guarded_by against tests.json when present.

    A guard naming a test that no longer exists is a false reassurance,
    so the check is on by default — but a repo that has not been ingested
    has no inventory to check against, and that is not the record's fault.
    """
    from hobbes.invariants import load_all

    known = None
    if strict_guards:
        if artifacts.artifact_path(repo_root, "tests.json").is_file():
            known = {t["id"] for t in artifacts.load_tests(repo_root)["tests"]}
    return load_all(repo_root, known_tests=known)


def _read_graph(repo_root):
    """Load graph.json, or None when the repo has not been ingested.

    A *wrong version* is not an absence and does not become None — it
    raises, so the caller cannot mistake "refused" for "never ingested"
    (ADR-028).
    """
    return artifacts.graph_if_ingested(repo_root)


def _cmd_invariants(args: argparse.Namespace) -> int:
    """`hobbes invariants list | check | compile` (ADR-024)."""
    from hobbes.invariants import ValidationError

    repo_root = _repo_root_from(args)
    try:
        records = _load_invariants(repo_root)
    except ValidationError as exc:
        print(f"hobbes invariants: {len(exc.problems)} problem(s)", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    for record in records:
        for warning in record.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

    if args.invariants_command == "check":
        # Loading is the check; getting here means every record is valid.
        if args.json:
            print(json.dumps({"records": len(records), "ok": True}, indent=2))
        else:
            confirmed = sum(1 for r in records if r.confirmed)
            print(f"invariants: {len(records)} record(s) valid, {confirmed} confirmed")
        return 0

    if args.invariants_command == "list":
        rows = [
            {
                "id": r.id,
                "status": r.status,
                "check": r.check,
                "target": r.target,
                "scope": r.scope,
                "statement": r.statement,
                "guarded_by": r.guarded_by,
                "source": r.source,
            }
            for r in records
            if args.all or r.confirmed
        ]
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
            return 0
        if not rows:
            print("no confirmed invariants — see .hobbes/invariants/README.md")
            return 0
        for row in rows:
            how = row["check"] + (f":{row['target']}" if row["target"] else "")
            print(f"  {row['id']:<6} {row['status']:<9} {how:<13} {row['scope']}")
            print(f"         {row['statement']}")
            if row["guarded_by"]:
                print(f"         guarded by {len(row['guarded_by'])} test(s)")
        print(f"invariants: {len(rows)} shown")
        return 0

    # compile
    from hobbes.invariants.compile import compile_all

    graph = _read_graph(repo_root)
    if graph is None:
        print(
            "hobbes invariants compile: no graph.json — run `hobbes ingest` first "
            "(wildcards expand over the module graph)",
            file=sys.stderr,
        )
        return 1
    manifest = compile_all(repo_root, records, graph)
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not manifest["outputs"]:
        print("nothing to compile — every confirmed record is soft")
    for output in manifest["outputs"]:
        ids = ", ".join(output["invariants"])
        print(f"  wrote {output['path']}  ({ids})")
        print(f"        run: {output['run']}")
    for skip in manifest["skipped"]:
        print(f"  skipped {skip['id']}: {skip['why']}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    """Concept-level review of a range: delta, invariants, coverage (ADR-025)."""
    from hobbes.graphdiff import RefError
    from hobbes.invariants import ValidationError
    from hobbes.review import build_review, format_review, review_to_dict

    repo_root = _repo_root_from(args)
    base_ref, head_ref = _parse_range(args.range)
    try:
        review = build_review(
            repo_root, base_ref, head_ref, with_soft=args.soft
        )
    except RefError as exc:
        print(f"hobbes review: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"hobbes review: invalid invariant records", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(review_to_dict(review), indent=2, sort_keys=True))
    else:
        print(format_review(review), end="")
    return 1 if review.needs_attention else 0


def _cmd_up(args: argparse.Namespace) -> int:
    """`hobbes up`: bring Hobbes up on a repo and hold for decisions (ADR-026).

    Does the mechanical steps — init if needed, re-ingest when the
    artifacts are not stamped at HEAD — then serves the UI and blocks
    until intent and every new invariant have a human verdict. It never
    narrates: that spends quota, and the graph should be checked before
    anything is paid for prose about it.
    """
    import shutil
    import subprocess
    import time

    from hobbes import decisions

    repo_root = _repo_root_from(args)

    # 1. Is Hobbes here at all?
    policy_path = repo_root / ".hobbes" / "policies" / "repo.policy"
    if not policy_path.is_file():
        print(f"hobbes up: no .hobbes/ in {repo_root} — initializing")
        rc = _cmd_init(argparse.Namespace(repo=str(repo_root)))
        if rc != 0:
            return rc

    # 2. Which commit was Hobbes last linked to?
    graph_path = repo_root / ".hobbes" / "derived" / "graph.json"
    head = _git_head(repo_root)
    stamped = ""
    if graph_path.is_file():
        try:
            stamped = json.loads(graph_path.read_text()).get("sha", "")
        except (ValueError, OSError):
            stamped = ""
    if not stamped:
        print("hobbes up: no skeleton yet — ingesting")
    elif stamped != head:
        print(f"hobbes up: artifacts stamped at {stamped[:12]}, HEAD is "
              f"{head[:12]} — re-ingesting")
    else:
        print(f"hobbes up: artifacts current at {stamped[:12]}")
    if not stamped or stamped != head:
        rc = _cmd_ingest(argparse.Namespace(repo=str(repo_root), tf_plan=None))
        if rc != 0:
            return rc

    # 3. What is still owed a human?
    state = decisions.readiness(repo_root)
    print()
    if state.ready:
        print("hobbes up: nothing awaiting a decision")
    else:
        print("hobbes up: decisions needed before this repo is ready:")
        for blocker in state.blockers():
            print(f"  - {blocker}")

    if args.no_serve:
        _print_ready(state, repo_root, served=False)
        return 0 if state.ready else 1

    binary = args.web_bin or shutil.which("hobbes-web")
    if not binary:
        print(
            "hobbes up: hobbes-web not found on PATH — build it "
            "(`cd go && go build -o bin/hobbes-web ./cmd/hobbes-web`) or pass "
            "--web-bin",
            file=sys.stderr,
        )
        return 1

    server = subprocess.Popen(
        [binary, "serve", "--repo", str(repo_root), "--addr", args.addr]
    )
    try:
        # 4. Block until the queue is empty (ADR-026: a queue you can walk
        # past is a queue you never empty).
        announced = state.ready
        if announced:
            _print_ready(state, repo_root, served=True, addr=args.addr)
        while True:
            if server.poll() is not None:
                print("hobbes up: the web surface exited", file=sys.stderr)
                return 1
            time.sleep(_UP_POLL_SECONDS)
            state = decisions.readiness(repo_root)
            if state.ready and not announced:
                announced = True
                _print_ready(state, repo_root, served=True, addr=args.addr)
    except KeyboardInterrupt:
        print("\nhobbes up: shutting down")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


#: How often `hobbes up` re-reads the decision ledger while blocking.
_UP_POLL_SECONDS = 2.0


def _git_head(repo_root: Path) -> str:
    """The repo's HEAD sha, or "" when git cannot answer."""
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _print_ready(state, repo_root: Path, served: bool, addr: str = "") -> None:
    """The banner that says a session can start."""
    print()
    if not state.ready:
        print("hobbes up: still waiting on:")
        for blocker in state.blockers():
            print(f"  - {blocker}")
        if served:
            print(f"  decide them at http://{addr}")
        return
    print("hobbes up: ready to develop.")
    print(f"  hobbes-session start --repo {repo_root} --role implementer --task '...'")
    if served:
        print(f"  surface: http://{addr}   (ctrl-c to stop)")


def build_parser() -> argparse.ArgumentParser:
    """Construct the hobbes argument parser (exposed for tests)."""
    parser = argparse.ArgumentParser(
        prog="hobbes",
        description="Hobbes: policy-governed agentic development environment.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser(
        "init", help="scaffold the .hobbes/ layout in a repo"
    )
    init_parser.add_argument(
        "--repo", help="repo root to initialize (default: current directory)"
    )

    ingest_parser = sub.add_parser(
        "ingest",
        help="run the deterministic extractors, write .hobbes/derived/",
        description=(
            "Extract the repo's knowledge skeleton (module graph, symbols, "
            "routes, test map) into SHA-stamped JSON artifacts under "
            ".hobbes/derived/."
        ),
    )
    ingest_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )
    ingest_parser.add_argument(
        "--tf-plan",
        help="a `terraform show -json` file to enrich the infra graph "
        "(never .tfstate)",
    )

    render_parser = sub.add_parser(
        "render",
        help="print the ingested module graph as Mermaid",
        description=(
            "Reads .hobbes/derived/graph.json (run `hobbes ingest` first) and "
            "prints a module-level Mermaid flowchart to stdout."
        ),
    )
    render_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )

    diff_parser = sub.add_parser(
        "diff",
        help="architecture delta between two refs",
        description=(
            "Extracts the graph at <base> and <head> and prints the typed "
            "edge-level delta. Exit codes mirror diff(1): 0 no differences, "
            "1 differences, 2 trouble."
        ),
    )
    diff_parser.add_argument(
        "range",
        metavar="<base>..<head>",
        help="refs to compare; a bare <base> compares against HEAD",
    )
    diff_parser.add_argument(
        "--json", action="store_true", help="emit the full delta as JSON"
    )
    diff_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )

    lanes_parser = sub.add_parser(
        "lanes",
        help="where the two extraction lanes disagree",
        description=(
            "Architecture v2 §3.4's self-test. Wherever both the syntax "
            "lane and the semantic lane resolved the same call site, they "
            "must point at the same definition; a disagreement is an "
            "extractor bug in one of them. Exit 1 when any site disagrees, "
            "so this runs as a CI check as well as a command."
        ),
    )
    lanes_parser.add_argument(
        "--json", action="store_true", help="emit the full report as JSON"
    )
    lanes_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )

    narrate_parser = sub.add_parser(
        "narrate",
        help="cartographer narrative pass — module docs, test behaviors, "
        "inferred invariants (spends Claude quota)",
        description=(
            "Walks the derived skeleton (run `hobbes ingest` first) and has "
            "headless Claude Code write pinned narrative artifacts into "
            ".hobbes/derived/docs/ (ADR-019/020). Only missing or stale "
            "units run; each unit is one quota-spending call."
        ),
    )
    narrate_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )
    narrate_parser.add_argument(
        "--all", action="store_true", help="regenerate even fresh artifacts"
    )
    narrate_parser.add_argument(
        "--only",
        action="append",
        metavar="PATTERN",
        help="only units whose id or path matches (repeatable, fnmatch)",
    )
    narrate_parser.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help="skip units whose id or path matches (repeatable, fnmatch)",
    )
    narrate_parser.add_argument(
        "--no-invariants",
        action="store_true",
        help="skip the repo-wide invariant inference unit",
    )
    narrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the work plan without spending any quota",
    )
    narrate_parser.add_argument(
        "--model", help="model override passed to claude -p"
    )

    docs_parser = sub.add_parser("docs", help="narrative artifacts front-end")
    docs_sub = docs_parser.add_subparsers(dest="docs_command", required=True)
    status_parser = docs_sub.add_parser(
        "status",
        help="freshness of narrative artifacts (stale badges)",
        description=(
            "Reads .hobbes/derived/docs/ and reports each artifact fresh or "
            "STALE with the changed source files (blob-level, ADR-019)."
        ),
    )
    status_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )
    status_parser.add_argument(
        "--json", action="store_true", help="emit the rows as JSON"
    )

    up_parser = sub.add_parser(
        "up",
        help="bring Hobbes up on this repo and hold for your decisions",
        description=(
            "One command for a bring-up (ADR-026): initialize if needed, "
            "re-ingest when the artifacts are not stamped at HEAD, serve the "
            "surface, and block until intent and every new invariant have a "
            "verdict. Never narrates — that spends quota, and is offered in "
            "the UI instead."
        ),
    )
    up_parser.add_argument("--repo", help="repo root (default: auto-detected via .git)")
    up_parser.add_argument(
        "--addr", default="127.0.0.1:7777", help="surface bind address (loopback only)"
    )
    up_parser.add_argument("--web-bin", help="hobbes-web binary (default: from PATH)")
    up_parser.add_argument(
        "--no-serve",
        action="store_true",
        help="report what is owed and exit instead of serving (exit 1 if not ready)",
    )

    review_parser = sub.add_parser(
        "review",
        help="concept-level review of a range: delta, invariants, coverage",
        description=(
            "The §7 review order in one command (ADR-025): architecture delta, "
            "invariant verdicts computed at BOTH ends so a regression is "
            "distinguishable from inherited breakage, and the behavioural-coverage "
            "delta. Exits 1 when something needs attention. Spends no quota unless "
            "--soft is given."
        ),
    )
    review_parser.add_argument(
        "range", help="commit range, base..head (as `hobbes diff`)"
    )
    review_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )
    review_parser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    review_parser.add_argument(
        "--soft",
        action="store_true",
        help="run a reviewer session for in-scope soft invariants (spends quota)",
    )

    invariants_parser = sub.add_parser(
        "invariants",
        help="confirmed invariant records: list, validate, compile to CI configs",
        description=(
            "Records live in .hobbes/invariants/ (ADR-024). `check` validates "
            "them, `list` shows them, and `compile` emits one CI config per "
            "target into .hobbes/derived/compiled/ — no target's toolchain "
            "needs to be installed to compile for it."
        ),
    )
    invariants_sub = invariants_parser.add_subparsers(
        dest="invariants_command", required=True
    )
    for name, help_text in (
        ("list", "show records"),
        ("check", "validate every record and exit non-zero on any problem"),
        ("compile", "emit CI configs into .hobbes/derived/compiled/"),
    ):
        p = invariants_sub.add_parser(name, help=help_text)
        p.add_argument("--repo", help="repo root (default: auto-detected via .git)")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "list":
            p.add_argument(
                "--all",
                action="store_true",
                help="include inferred and retired records, not just confirmed",
            )

    policy_parser = sub.add_parser("policy", help="policy engine front-end")
    policy_sub = policy_parser.add_subparsers(dest="policy_command", required=True)
    resolve_parser = policy_sub.add_parser(
        "resolve",
        help="resolve a command against the merged policy chain",
        description=(
            "Shells out to the Go hobbes-policy binary. Prints the JSON "
            "resolution; exit code encodes the decision "
            "(0 allow, 10 deny, 20 escalate)."
        ),
    )
    # dest must not collide with the top-level subparser dest ("command").
    resolve_parser.add_argument(
        "command_string",
        metavar="command",
        help="the command to resolve, as one quoted string, "
        'e.g. "git push --force origin main"',
    )
    resolve_parser.add_argument(
        "--dir", help="directory context the command runs in (default: cwd)"
    )
    resolve_parser.add_argument(
        "--repo", help="repo root (default: auto-detected via .git)"
    )
    resolve_parser.add_argument(
        "--box", help="box policy path (default: ~/.hobbes/box.policy if present)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    # Report progress as it happens, not at exit. Python block-buffers
    # stdout when it is not a tty, and the two commands that take real time
    # print while they work: `up` lists the decisions it is blocking on and
    # then holds, `narrate` prints one line per unit. Redirected or
    # supervised (`hobbes up > up.log &`), both looked silent for exactly as
    # long as they were doing their job. A tty is line-buffered already, so
    # this changes nothing about interactive use.
    #
    # Guarded because a captured stdout (pytest's capsys, a StringIO) has no
    # reconfigure, and buffering is not its problem anyway.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = build_parser().parse_args(argv)
    handlers = {
        "init": _cmd_init,
        "ingest": _cmd_ingest,
        "render": _cmd_render,
        "diff": _cmd_diff,
        "lanes": _cmd_lanes,
        "narrate": _cmd_narrate,
        "docs": _cmd_docs_status,
        "invariants": _cmd_invariants,
        "review": _cmd_review,
        "up": _cmd_up,
        "policy": _cmd_policy_resolve,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
