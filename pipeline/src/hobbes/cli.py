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

from hobbes import __version__, policy

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
    from hobbes.extract.terraform import PlanError

    from hobbes.extract.emit import ensure_hobbes_ignored

    repo_root = _repo_root_from(args)
    ignored = ensure_hobbes_ignored(repo_root)
    if ignored:
        print(f"{ignored} (Hobbes files stay out of version control, ADR-012)")
    try:
        paths = ingest(repo_root, tf_plan=Path(args.tf_plan) if args.tf_plan else None)
    except (StampError, PlanError) as exc:
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
    for path in sorted(paths):
        print(f"  wrote {path}")
    return 0


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
    artifact = repo_root / ".hobbes" / "derived" / "graph.json"
    if not artifact.is_file():
        print(
            f"hobbes render: {artifact} not found — run `hobbes ingest` first",
            file=sys.stderr,
        )
        return 1
    print(to_mermaid(json.loads(artifact.read_text())), end="")
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
    args = build_parser().parse_args(argv)
    handlers = {
        "init": _cmd_init,
        "ingest": _cmd_ingest,
        "render": _cmd_render,
        "diff": _cmd_diff,
        "narrate": _cmd_narrate,
        "docs": _cmd_docs_status,
        "policy": _cmd_policy_resolve,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
