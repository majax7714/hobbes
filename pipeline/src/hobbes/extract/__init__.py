"""Deterministic extraction pipeline (build plan M1).

Walks a repo with tree-sitter (ADR-005) and emits the three SHA-stamped
derived artifacts (ADR-006) into ``.hobbes/derived/``:

- ``graph.json`` — module nodes + symbol layer, typed edges (``imports``,
  ``env-read`` at module level, ``calls`` at symbol level), plus whatever
  the enrichment packs contributed and a ``packs`` list naming them,
- ``tests.json`` — pytest inventory with static test→symbol reach,
- ``interfaces.json`` — HTTP routes and CLI entry points, all of which
  now come from packs (ADR-035) rather than from the pipeline itself.

No LLM is involved anywhere in this package (P5: deterministic first).
The public entry points are :func:`extract_repo` (pure: tree → documents)
and :func:`ingest` (extract, stamp with the repo's git SHA, write).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hobbes.extract import evidence as ev
from hobbes.extract import scipsource, staging
from hobbes.extract.discover import discover_modules
from hobbes.extract.emit import ensure_hobbes_ignored, repo_stamp, write_artifacts
from hobbes.extract.graph import build_graph, resolve_call_sites
from hobbes.extract.packs import REGISTRY as PACK_REGISTRY
from hobbes.extract.packs import Pack, PackContext, run_packs
from hobbes.extract.pysource import parse_source
from hobbes.extract.testmap import collect_tests
from hobbes.extract.tssource import collect_ts_tests, extract_ts

#: v2 (M3): "language" became "languages" when the infra layer joined
#: (ADR-010). v3 (M6, ADR-021): tests carry a per-test "framework" field
#: (a repo now mixes pytest with JS frameworks) and the global
#: tests.json "framework" field is gone; "languages" may include
#: typescript/javascript. v4 (V2.M1, ADR-028): every edge carries a
#: ``tier`` and every evidence entry a ``lane`` (architecture §3.4) —
#: additive over v3, so a reader that ignores unknown fields still reads
#: v4 correctly. Consumers reject versions they don't know (ADR-006), and
#: as of v4 they actually do: see :mod:`hobbes.artifacts`.
SCHEMA_VERSION = 4


@dataclass(frozen=True)
class Extraction:
    """The three artifact documents, minus the provenance stamp."""

    graph: dict
    tests: dict
    interfaces: dict


def extract_repo(
    repo_root: Path,
    tf_plan: Path | None = None,
    packs: tuple[Pack, ...] = PACK_REGISTRY,
) -> Extraction:
    """Extract the knowledge skeleton (lanes + packs) under *repo_root*.

    Pure with respect to the working tree: no git access, no writes — the
    stamp and the emission live in :func:`ingest` so tests can exercise
    extraction on unversioned fixtures. *tf_plan* optionally names a
    ``terraform show -json`` file for plan enrichment (ADR-010).

    The order is load-bearing since V2.M3. **All of lane A first**, across
    every language, so the node and symbol space is complete; **then the
    packs** (V2.M4), which read those facts and add framework knowledge on
    top; **then the range join**, which is the only producer of symbol edges
    and needs the node space to project onto; **then the test map**, whose
    reach is measured over the edges the join produced. Running lane B per
    language as each was parsed — the M2 shape — could not work for
    TypeScript, because its nodes did not exist yet when the join ran.

    *packs* is a seam for the exit criterion (ADR-035): the suite extracts
    with a pack and without it, and asserts the difference is exactly that
    pack's contribution. Callers have no reason to pass it.
    """
    repo_root = Path(repo_root).resolve()
    modules = discover_modules(repo_root)
    parsed = {
        m.id: parse_source((repo_root / m.path).read_bytes()) for m in modules
    }
    graph = build_graph(modules, parsed)
    degraded: list[dict] = []

    # Languages reflect what the repo actually contains — a TS-only repo
    # (M6) must not claim python.
    languages = ["python"] if modules else []

    ts = extract_ts(repo_root)
    if ts:
        languages += ts["languages"]
        degraded += list(ts["errors"])
        degraded += _merge_layer(graph, ts["nodes"], ts["module_edges"])
        graph["symbols"] = _merge_symbols(graph["symbols"], ts["symbols"])

    # Lane A is complete. Packs read it and add framework knowledge; the
    # graph builder itself knows nothing about FastAPI, Express or HCL.
    enriched = run_packs(
        PackContext(
            repo_root=repo_root,
            modules=modules,
            parsed=parsed,
            ts=ts,
            tf_plan=tf_plan,
        ),
        packs,
    )
    languages += enriched.languages
    degraded += enriched.errors
    degraded += _merge_layer(graph, enriched.nodes, enriched.module_edges)
    graph["packs"] = enriched.ran

    degraded += _build_symbol_layer(repo_root, graph, modules, parsed, ts)

    tests = collect_tests(modules, parsed, graph["symbol_edges"])
    if ts:
        tests = sorted(
            tests
            + collect_ts_tests(ts["files"], ts["symbols"], graph["symbol_edges"]),
            key=lambda t: t["id"],
        )
    if degraded:
        # Sorted, not append-ordered: which pass reported first is an
        # accident of pipeline order, and an artifact that changes with it
        # is not reproducible in the sense P1 means (ADR-035).
        graph["extraction_errors"] = sorted(
            degraded, key=lambda d: (d["stage"], d["path"], d["message"])
        )

    return Extraction(
        graph={"languages": sorted(languages), **graph},
        tests={"tests": tests},
        interfaces={
            "routes": sorted(
                enriched.routes, key=lambda r: (r["file"], r.get("line", 0))
            ),
            "cli_entry_points": enriched.cli_entry_points,
        },
    )


def _syntax_sites(modules, parsed) -> list:
    """Lane A's call sites, in evidence-IR shape (ADR-029)."""
    return [
        ev.Site(
            provider=ev.TREE_SITTER,
            kind=ev.CALL_SITE,
            file=module.path,
            line=call.line,
            name=call.callee.split(".")[-1],
            col=call.col,
            scope=f"{module.id}.{call.scope}" if call.scope else module.id,
        )
        for module in modules
        for call in parsed[module.id].calls
    ]


def _build_symbol_layer(
    repo_root: Path, graph: dict, modules, parsed, ts: dict | None
) -> list[dict]:
    """Join every lane's evidence and project it onto the graph's ids.

    **The only producer of symbol edges** (ADR-031), and it runs whether or
    not lane B does: with no semantic resolutions every call site falls to
    the fallback arm and the graph is lane A's, at ``syntactic`` tier. That
    is P6 satisfied by construction rather than by a second code path — the
    degraded case is the normal case with an empty input.

    Both languages' evidence is pooled before joining. They cannot collide:
    the join buckets by ``(file, line)`` and no file belongs to two
    languages.

    Returns degradation records; never raises. A missing indexer, a crashed
    one, or an uninstalled environment must not fail an ingest.
    """
    degraded: list[dict] = []
    syntax: list[ev.Site] = []
    resolutions: list[ev.Site] = []
    fallback: dict[tuple, tuple] = {}
    external: list[dict] = []

    if modules:
        syntax += _syntax_sites(modules, parsed)
        fallback.update(resolve_call_sites(modules, parsed))
    if ts:
        syntax += ts["call_sites"]
        fallback.update(ts["call_fallback"])

    for facts in _lane_b_facts(repo_root, modules, ts, degraded):
        resolutions += scipsource.resolution_sites(facts)
        external += facts.get("external_refs") or []
        for record in facts.get("degraded", []):
            degraded.append(
                {"path": ".", "stage": record["stage"], "message": record["message"]}
            )
        coverage = facts.get("dependency_coverage") or {}
        if coverage.get("declared"):
            graph.setdefault("dependency_coverage", []).append(coverage)

    resolved = ev.join(syntax, resolutions, fallback=fallback)
    projected = scipsource.project(resolved, graph["nodes"], graph["symbols"])
    graph["lane_agreement"] = _lane_agreement(
        syntax, resolutions, fallback, graph["module_edges"], projected["module_edges"]
    )
    graph["symbol_edges"] = projected["symbol_edges"]
    graph["module_edges"] = _merge_module_edges(
        graph["module_edges"], projected["module_edges"]
    )
    graph["resolution_coverage"] = [
        {
            "file": row.file,
            "sites": row.sites,
            "resolved": row.resolved,
            "external": row.external,
            "unresolved": row.unresolved,
        }
        for row in ev.coverage(syntax, resolutions, external)
    ]
    return degraded


#: Node id prefixes only lane A can produce — third-party packages,
#: environment variables, and the Terraform layer. Lane B never sees them,
#: so their absence from its edge set is not a disagreement.
_LANE_A_ONLY = ("ext:", "env:", "tf:")


def _lane_agreement(
    syntax, resolutions, fallback, lane_a_edges, lane_b_edges
) -> dict:
    """The §3.4 self-test: where both lanes can answer, they must agree.

    Two comparisons, because the lanes overlap in two places. Call sites
    both resolved (the sharp one, ADR-029) and module-level import edges
    both could produce. Only edges between two repo modules are compared —
    ``ext:``/``env:``/``tf:`` nodes are lane A's alone, and counting them
    would report hundreds of false disagreements and bury the real ones.
    """
    compared, disagreements = ev.agreement(syntax, resolutions, fallback)

    def repo_imports(edges):
        return {
            (e["from"], e["to"])
            for e in edges
            if e["type"] == "imports"
            and not e["from"].startswith(_LANE_A_ONLY)
            and not e["to"].startswith(_LANE_A_ONLY)
        }

    a, b = repo_imports(lane_a_edges), repo_imports(lane_b_edges)
    return {
        "sites_compared": compared,
        "site_disagreements": [
            {
                "file": d.file,
                "line": d.line,
                "name": d.name,
                "syntactic": f"{d.syntactic_file}:{d.syntactic_line}",
                "semantic": f"{d.semantic_file}:{d.semantic_line}",
            }
            for d in disagreements
        ],
        # Only meaningful when lane B ran at all; an empty lane B would
        # otherwise report every module edge as "lane A only".
        "module_edges_compared": len(a | b) if b else 0,
        "module_edges_lane_a_only": (
            [{"from": f, "to": t} for f, t in sorted(a - b)] if b else []
        ),
        "module_edges_lane_b_only": [
            {"from": f, "to": t} for f, t in sorted(b - a)
        ],
    }


def _lane_b_facts(repo_root: Path, modules, ts: dict | None, degraded: list[dict]):
    """Every semantic provider's facts, skipping the ones that cannot run."""
    if not scipsource.enabled():
        return
    runs = []
    if modules:
        files = sorted({m.path for m in modules})
        roots = sorted({m.root for m in modules})
        runs.append(
            (
                "python",
                lambda: scipsource.extract_scip(
                    repo_root,
                    files,
                    roots,
                    project_name=repo_root.name,
                    sha="",
                    declared_deps=scipsource.declared_dependencies(repo_root),
                ),
            )
        )
    if ts:
        ts_files = sorted({f["path"] for f in ts["files"]})
        runs.append(
            ("typescript", lambda: scipsource.extract_scip_typescript(repo_root, ts_files))
        )

    for language, run in runs:
        try:
            facts = run()
        except (scipsource.ScipError, staging.StagingError, OSError) as exc:
            degraded.append(
                {
                    "path": ".",
                    "stage": f"scip-{language}",
                    "message": f"lane B did not run for {language}: {exc}",
                }
            )
            continue
        if facts is not None:
            yield facts


def _merge_module_edges(lane_a: list[dict], lane_b: list[dict]) -> list[dict]:
    """Keep lane A's module edges, upgrading the ones lane B also proved.

    Lane A's import statements are syntactic facts about the source — an
    ``import x`` really is an import — and they reach ``ext:``/``env:``
    nodes lane B cannot see. So lane A stays the spine here and lane B
    raises the tier where it agrees.
    """
    by_key = {(e["from"], e["to"], e["type"]): e for e in lane_a}
    for edge in lane_b:
        key = (edge["from"], edge["to"], edge["type"])
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = edge
            continue
        seen = {(s["path"], s["line"], s["lane"]) for s in edge["evidence"]}
        merged = dict(edge)
        merged["evidence"] = edge["evidence"] + [
            s for s in prior["evidence"]
            if (s["path"], s["line"], s["lane"]) not in seen
        ]
        by_key[key] = merged
    return sorted(by_key.values(), key=lambda e: (e["from"], e["to"], e["type"]))


def _merge_layer(
    graph: dict, nodes: list[dict], module_edges: list[dict]
) -> list[dict]:
    """Merge another language layer's nodes and module edges into *graph*.

    Each language owns its own files (discovery is by extension, so no
    parser ever sees another's source) and its facts are merged, never
    re-derived — a second parse can't contradict the first because it
    never happens.

    Node ids can still collide *across* layers, though: a repo-root
    ``widget.py`` and ``widget.ts`` both want the id ``widget``. The
    first layer keeps it, and the loser is **reported**, not dropped in
    silence — resolution by pipeline order is an accident, and an
    accident that is invisible is a lie about the graph (P1). Returns
    one degradation record per collision.
    """
    merged = {n["id"]: n for n in graph["nodes"]}
    collisions = []
    for node in nodes:
        existing = merged.get(node["id"])
        if existing is None:
            merged[node["id"]] = node
            continue
        if existing.get("path") != node.get("path"):
            collisions.append(
                {
                    "path": node.get("path", node["id"]),
                    "stage": "layer-merge",
                    "message": (
                        f"module id {node['id']!r} is already held by "
                        f"{existing.get('path')!r}; this file is omitted from the "
                        "graph. Rename one of them, or move it out of the repo root."
                    ),
                }
            )
    graph["nodes"] = sorted(merged.values(), key=lambda n: n["id"])
    graph["module_edges"] = sorted(
        graph["module_edges"] + module_edges,
        key=lambda e: (e["from"], e["to"], e["type"]),
    )
    return collisions


def _merge_symbols(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge a layer's symbols, keeping ids unique.

    A colliding module id drags its symbols with it; emitting both would
    put two rows under one id in the artifact and leave one of them
    pointing at a module the node list does not contain.
    """
    merged = {s["id"]: s for s in existing}
    for symbol in incoming:
        merged.setdefault(symbol["id"], symbol)
    return sorted(merged.values(), key=lambda s: s["id"])


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
