"""The ``hobbes`` command-line interface.

M1 surface: ``ingest`` runs the deterministic extractors and writes the
SHA-stamped artifacts into ``.hobbes/derived/``; ``init`` scaffolds the
``.hobbes/`` layout in a repo; ``policy resolve`` passes through to the Go
``hobbes-policy`` binary — JSON on stdout, decision exit code propagated
(ADR-003). ``diff`` remains a stub until M2. argparse per ADR-004.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hobbes import __version__, policy

#: Exit code for stub subcommands that are not implemented yet.
EXIT_NOT_IMPLEMENTED = 2

#: Which milestone delivers each stub, for honest error messages.
_STUB_MILESTONES = {
    "diff": "M2",
}

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

#: Lines `hobbes init` guarantees are present in the repo's .gitignore.
_GITIGNORE_LINES = [".hobbes/derived/", "*.tfstate", "*.tfstate.*"]


def _stub(name: str) -> int:
    """Report a not-yet-implemented subcommand without pretending otherwise."""
    milestone = _STUB_MILESTONES[name]
    print(
        f"hobbes {name}: not implemented yet (lands in {milestone} "
        "per docs/hobbes-build-plan.md)",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


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

    repo_root = _repo_root_from(args)
    try:
        paths = ingest(repo_root)
    except StampError as exc:
        print(f"hobbes ingest: {exc}", file=sys.stderr)
        return 1
    docs = {p.name: json.loads(p.read_text()) for p in paths}
    graph, tests, interfaces = (
        docs["graph.json"],
        docs["tests.json"],
        docs["interfaces.json"],
    )
    dirty = " (dirty tree)" if graph["dirty"] else ""
    print(f"ingested {repo_root} @ {graph['sha'][:12]}{dirty}")
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
    root = Path(args.repo).resolve() if args.repo else Path.cwd()
    actions: list[str] = []

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

    sub.add_parser("diff", help="architecture delta between two refs (M2)")

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
    if args.command in _STUB_MILESTONES:
        return _stub(args.command)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "policy":
        return _cmd_policy_resolve(args)
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
