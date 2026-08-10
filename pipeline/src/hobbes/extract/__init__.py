"""Deterministic extraction pipeline (build plan M1).

Walks a repo with tree-sitter (ADR-005) and emits the three SHA-stamped
derived artifacts (ADR-006) into ``.hobbes/derived/``:

- ``graph.json`` — module nodes + symbol layer, typed edges (``imports``,
  ``env-read`` at module level, ``calls`` at symbol level),
- ``tests.json`` — pytest inventory with static test→symbol reach,
- ``interfaces.json`` — FastAPI/Flask routes and CLI entry points.

No LLM is involved anywhere in this package (P5: deterministic first).
The public entry points are :func:`extract_repo` (pure: tree → documents)
and :func:`ingest` (extract, stamp with the repo's git SHA, write).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hobbes.extract.discover import discover_modules
from hobbes.extract.emit import repo_stamp, write_artifacts
from hobbes.extract.graph import build_graph
from hobbes.extract.interfaces import extract_cli_entry_points, extract_routes
from hobbes.extract.pysource import parse_source
from hobbes.extract.testmap import collect_tests

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Extraction:
    """The three artifact documents, minus the provenance stamp."""

    graph: dict
    tests: dict
    interfaces: dict


def extract_repo(repo_root: Path) -> Extraction:
    """Extract the knowledge skeleton of the Python code under *repo_root*.

    Pure with respect to the working tree: no git access, no writes — the
    stamp and the emission live in :func:`ingest` so tests can exercise
    extraction on unversioned fixtures.
    """
    repo_root = Path(repo_root).resolve()
    modules = discover_modules(repo_root)
    parsed = {
        m.id: parse_source((repo_root / m.path).read_bytes()) for m in modules
    }
    graph = build_graph(modules, parsed)
    return Extraction(
        graph={"language": "python", **graph},
        tests={
            "framework": "pytest",
            "tests": collect_tests(modules, parsed, graph["symbol_edges"]),
        },
        interfaces={
            "routes": extract_routes(modules, parsed),
            "cli_entry_points": extract_cli_entry_points(repo_root),
        },
    )


def ingest(repo_root: Path) -> list[Path]:
    """Extract *repo_root*, stamp with its git SHA, write the artifacts.

    Returns the written paths (``.hobbes/derived/{graph,tests,interfaces}.json``).
    Requires *repo_root* to be a git repo with at least one commit — the SHA
    is the provenance every downstream claim pins to (P3).
    """
    repo_root = Path(repo_root).resolve()
    extraction = extract_repo(repo_root)
    stamp = {"schema_version": SCHEMA_VERSION, **repo_stamp(repo_root)}
    return write_artifacts(
        repo_root,
        {
            "graph.json": {**stamp, **extraction.graph},
            "tests.json": {**stamp, **extraction.tests},
            "interfaces.json": {**stamp, **extraction.interfaces},
        },
    )
