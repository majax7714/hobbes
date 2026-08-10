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
from hobbes.extract.emit import ensure_hobbes_ignored, repo_stamp, write_artifacts
from hobbes.extract.graph import build_graph
from hobbes.extract.interfaces import extract_cli_entry_points, extract_routes
from hobbes.extract.pysource import parse_source
from hobbes.extract.terraform import extract_terraform
from hobbes.extract.testmap import collect_tests

#: v2 (M3): "language" became "languages" when the infra layer joined
#: (ADR-010); consumers reject versions they don't know (ADR-006).
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Extraction:
    """The three artifact documents, minus the provenance stamp."""

    graph: dict
    tests: dict
    interfaces: dict


def extract_repo(repo_root: Path, tf_plan: Path | None = None) -> Extraction:
    """Extract the knowledge skeleton (app + infra layers) under *repo_root*.

    Pure with respect to the working tree: no git access, no writes — the
    stamp and the emission live in :func:`ingest` so tests can exercise
    extraction on unversioned fixtures. *tf_plan* optionally names a
    ``terraform show -json`` file for plan enrichment (ADR-010).
    """
    repo_root = Path(repo_root).resolve()
    modules = discover_modules(repo_root)
    parsed = {
        m.id: parse_source((repo_root / m.path).read_bytes()) for m in modules
    }
    graph = build_graph(modules, parsed)

    infra = extract_terraform(repo_root, modules, tf_plan=tf_plan)
    languages = ["python"]
    if infra["tf_file_count"]:
        languages.append("hcl")
        nodes = {n["id"]: n for n in graph["nodes"]}
        for node in infra["nodes"]:
            nodes.setdefault(node["id"], node)
        graph["nodes"] = sorted(nodes.values(), key=lambda n: n["id"])
        graph["module_edges"] = sorted(
            graph["module_edges"] + infra["module_edges"],
            key=lambda e: (e["from"], e["to"], e["type"]),
        )

    return Extraction(
        graph={"languages": sorted(languages), **graph},
        tests={
            "framework": "pytest",
            "tests": collect_tests(modules, parsed, graph["symbol_edges"]),
        },
        interfaces={
            "routes": extract_routes(modules, parsed),
            "cli_entry_points": extract_cli_entry_points(repo_root),
        },
    )


def ingest(repo_root: Path, tf_plan: Path | None = None) -> list[Path]:
    """Extract *repo_root*, stamp with its git SHA, write the artifacts.

    Returns the written paths (``.hobbes/derived/{graph,tests,interfaces}.json``).
    Requires *repo_root* to be a git repo with at least one commit — the SHA
    is the provenance every downstream claim pins to (P3). Always ensures
    the repo gitignores Hobbes files first (ADR-012), so the stamp's
    ``dirty`` flag reflects that edit when it happens.
    """
    repo_root = Path(repo_root).resolve()
    ensure_hobbes_ignored(repo_root)
    extraction = extract_repo(repo_root, tf_plan=tf_plan)
    stamp = {"schema_version": SCHEMA_VERSION, **repo_stamp(repo_root)}
    return write_artifacts(
        repo_root,
        {
            "graph.json": {**stamp, **extraction.graph},
            "tests.json": {**stamp, **extraction.tests},
            "interfaces.json": {**stamp, **extraction.interfaces},
        },
    )
