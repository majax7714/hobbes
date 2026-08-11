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
from hobbes.extract.tssource import extract_ts

#: v2 (M3): "language" became "languages" when the infra layer joined
#: (ADR-010). v3 (M6, ADR-021): tests carry a per-test "framework" field
#: (a repo now mixes pytest with JS frameworks) and the global
#: tests.json "framework" field is gone; "languages" may include
#: typescript/javascript. Consumers reject versions they don't know
#: (ADR-006).
SCHEMA_VERSION = 3


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
    tests = collect_tests(modules, parsed, graph["symbol_edges"])
    routes = extract_routes(modules, parsed)

    infra = extract_terraform(repo_root, modules, tf_plan=tf_plan)
    languages = ["python"]
    if infra["tf_file_count"]:
        languages.append("hcl")
        _merge_layer(graph, infra["nodes"], infra["module_edges"])

    ts = extract_ts(repo_root)
    if ts:
        languages += ts["languages"]
        _merge_layer(graph, ts["nodes"], ts["module_edges"])
        graph["symbols"] = sorted(
            graph["symbols"] + ts["symbols"], key=lambda s: s["id"]
        )
        graph["symbol_edges"] = sorted(
            graph["symbol_edges"] + ts["symbol_edges"],
            key=lambda e: (e["from"], e["to"], e["type"]),
        )
        tests = sorted(tests + ts["tests"], key=lambda t: t["id"])
        routes = sorted(
            routes + ts["routes"], key=lambda r: (r["file"], r.get("line", 0))
        )

    return Extraction(
        graph={"languages": sorted(languages), **graph},
        tests={"tests": tests},
        interfaces={
            "routes": routes,
            "cli_entry_points": extract_cli_entry_points(repo_root),
        },
    )


def _merge_layer(graph: dict, nodes: list[dict], module_edges: list[dict]) -> None:
    """Merge another language layer's nodes and module edges into *graph*."""
    merged = {n["id"]: n for n in graph["nodes"]}
    for node in nodes:
        merged.setdefault(node["id"], node)
    graph["nodes"] = sorted(merged.values(), key=lambda n: n["id"])
    graph["module_edges"] = sorted(
        graph["module_edges"] + module_edges,
        key=lambda e: (e["from"], e["to"], e["type"]),
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
