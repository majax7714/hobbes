"""The ``hobbes`` command-line interface.

M0 skeleton (build plan): ``init``, ``ingest``, and ``diff`` are stubs that
name the milestone in which they land, and ``policy resolve`` is a working
passthrough to the Go ``hobbes-policy`` binary — JSON on stdout, decision
exit code propagated (ADR-003). argparse over click/typer per ADR-004.
"""

from __future__ import annotations

import argparse
import json
import sys

from hobbes import __version__, policy

#: Exit code for stub subcommands that are not implemented yet.
EXIT_NOT_IMPLEMENTED = 2

#: Which milestone delivers each stub, for honest error messages.
_STUB_MILESTONES = {
    "init": "M1",
    "ingest": "M1",
    "diff": "M2",
}


def _stub(name: str) -> int:
    """Report a not-yet-implemented subcommand without pretending otherwise."""
    milestone = _STUB_MILESTONES[name]
    print(
        f"hobbes {name}: not implemented yet (lands in {milestone} "
        "per docs/hobbes-build-plan.md)",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


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

    sub.add_parser("init", help="scaffold .hobbes/ in a repo (M1)")
    sub.add_parser("ingest", help="run deterministic extractors (M1)")
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
    if args.command == "policy":
        return _cmd_policy_resolve(args)
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
