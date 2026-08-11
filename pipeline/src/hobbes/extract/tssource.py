"""TS/JS extraction: invoke the tsextract helper, join its facts (ADR-021).

The Node helper (``tsextract/extract.mjs``, ts-morph) does discovery and
checker-grade resolution and emits facts JSON; this module turns those
facts into the same graph/tests/interfaces shapes the Python extractor
produces. Module ids are repo-relative paths sans extension
(``src/flow``), symbol ids ``<module-id>.<qualname>``.

Setup is explicit, never silent: a repo with TS/JS files and no usable
helper fails ingest with instructions (skipping would make graph content
depend on the environment). ``HOBBES_TSEXTRACT_CMD`` overrides the
helper invocation — the ``HOBBES_POLICY_BIN`` precedent; tests use it
for canned facts.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

from hobbes.extract.discover import SKIPPED_DIR_NAMES

#: Environment variable holding a shell-split command prefix that replaces
#: ``node <repo>/tsextract/extract.mjs``.
TSEXTRACT_CMD_ENV = "HOBBES_TSEXTRACT_CMD"

#: The facts schema this join understands (helper HELPER_VERSION).
HELPER_VERSION = 1

#: Extensions the helper extracts; used only for the cheap "does this repo
#: have TS/JS at all" scan that decides whether the helper must run.
_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_TS_EXTENSIONS = {".ts", ".tsx"}


class TsExtractError(RuntimeError):
    """The helper could not run or answered garbage — with the fix."""


def has_ts_files(repo_root: Path) -> bool:
    """Cheap scan: does the repo contain any TS/JS source at all?"""
    stack = [Path(repo_root)]
    while stack:
        directory = stack.pop()
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name not in SKIPPED_DIR_NAMES:
                    stack.append(child)
            elif child.suffix in _EXTENSIONS:
                return True
    return False


def _helper_cmd() -> list[str]:
    override = os.environ.get(TSEXTRACT_CMD_ENV)
    if override:
        return shlex.split(override)
    helper = Path(__file__).resolve().parents[4] / "tsextract" / "extract.mjs"
    return ["node", str(helper)]


def run_helper(repo_root: Path) -> dict:
    """Run the helper on *repo_root* and return its parsed facts."""
    cmd = _helper_cmd()
    setup = (
        "TS/JS files found but the tsextract helper is unusable — install "
        "Node and run `npm install` in the hobbes repo's tsextract/, or set "
        f"${TSEXTRACT_CMD_ENV} (ADR-021)"
    )
    try:
        proc = subprocess.run(
            [*cmd, "--repo", str(repo_root)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise TsExtractError(f"{setup}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TsExtractError(f"tsextract helper timed out on {repo_root}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-500:]
        raise TsExtractError(f"{setup}: helper exited {proc.returncode}: {detail}")
    try:
        facts = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise TsExtractError(f"tsextract helper emitted invalid JSON: {exc}") from exc
    version = facts.get("helper_version")
    if version != HELPER_VERSION:
        raise TsExtractError(
            f"tsextract facts version {version!r} unsupported (want {HELPER_VERSION})"
        )
    return facts


def module_id(path: str) -> str:
    """Repo-relative path sans extension: the ADR-021 module id."""
    pure = PurePosixPath(path)
    return str(pure.with_suffix("")) if pure.suffix in _EXTENSIONS else str(pure)


def join_facts(facts: dict) -> dict:
    """Join helper facts into graph/tests/routes pieces (pure).

    Returns ``{"nodes", "module_edges", "symbols", "symbol_edges",
    "tests", "routes", "languages"}`` — empty lists when the repo has no
    TS/JS files.
    """
    files = facts.get("files", [])
    languages = set()
    for f in files:
        suffix = PurePosixPath(f["path"]).suffix
        if suffix in _TS_EXTENSIONS:
            languages.add("typescript")
        elif suffix in _EXTENSIONS:
            languages.add("javascript")

    nodes: dict[str, dict] = {}
    module_edges: dict[tuple, list] = defaultdict(list)
    symbols: list[dict] = []
    symbol_edges: dict[tuple, list] = defaultdict(list)
    routes: list[dict] = []

    for f in files:
        mid = module_id(f["path"])
        nodes[mid] = {"id": mid, "kind": "module", "path": f["path"]}
        for imp in f["imports"]:
            if imp["resolved"]:
                target = module_id(imp["resolved"])
            elif imp["external"]:
                target = f"ext:{imp['external']}"
                nodes.setdefault(target, {"id": target, "kind": "external"})
            else:
                continue
            module_edges[(mid, target, "imports")].append(
                {"path": f["path"], "line": imp["line"]}
            )
        for read in f["env_reads"]:
            env_node = f"env:{read['var']}"
            nodes.setdefault(
                env_node, {"id": env_node, "kind": "env", "name": read["var"]}
            )
            module_edges[(mid, env_node, "env-read")].append(
                {"path": f["path"], "line": read["line"]}
            )
        for sym in f["symbols"]:
            symbols.append(
                {
                    "id": f"{mid}.{sym['qualname']}",
                    "module": mid,
                    "kind": sym["kind"],
                    "name": sym["name"],
                    "qualname": sym["qualname"],
                    "line": sym["line"],
                    "end_line": sym["end_line"],
                }
            )
        for call in f["calls"]:
            source = f"{mid}.{call['scope']}" if call["scope"] else mid
            target = f"{module_id(call['callee_path'])}.{call['callee']}"
            symbol_edges[(source, target, "calls")].append(
                {"path": f["path"], "line": call["line"]}
            )
        for route in f["routes"]:
            handler = route["handler"]
            if route.get("handler_path"):
                handler = f"{module_id(route['handler_path'])}.{handler}"
            routes.append(
                {
                    "file": f["path"],
                    "framework": route["framework"],
                    "handler": handler,
                    "line": route["line"],
                    "method": route["method"],
                    "path": route["path"],
                }
            )

    return {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "module_edges": _edge_list(module_edges),
        "symbols": sorted(symbols, key=lambda s: s["id"]),
        "symbol_edges": _edge_list(symbol_edges),
        "tests": _collect_tests(files, symbols, symbol_edges),
        "routes": sorted(routes, key=lambda r: (r["file"], r["line"], r["path"])),
        "languages": sorted(languages),
    }


def _edge_list(edges: dict[tuple, list]) -> list[dict]:
    """Mirror of graph._edge_list: sorted typed edges with merged evidence."""
    return [
        {
            "from": source,
            "to": target,
            "type": edge_type,
            "evidence": sorted(evidence, key=lambda e: (e["path"], e["line"])),
        }
        for (source, target, edge_type), evidence in sorted(edges.items())
    ]


def _collect_tests(
    files: list[dict], symbols: list[dict], symbol_edges: dict[tuple, list]
) -> list[dict]:
    """tests.json rows for JS/TS tests, with file-level static reach.

    JS test cases are anonymous closures, not symbols, so reach is
    computed once per test *file* — every symbol its imports name plus
    every call it makes, closed over the call graph — and shared by the
    file's cases. Coarser than pytest's per-test reach; honest about
    what static analysis of closures gives us (ADR-021).
    """
    test_files = {f["path"] for f in files if f["test_framework"]}
    test_module_ids = {module_id(p) for p in test_files}
    symbol_module = {s["id"]: s["module"] for s in symbols}
    symbols_by_module = defaultdict(set)
    for s in symbols:
        symbols_by_module[s["module"]].add(s["qualname"])

    adjacency = defaultdict(set)
    for (source, target, _), _evidence in symbol_edges.items():
        adjacency[source].add(target)

    records = []
    for f in files:
        if not f["test_framework"]:
            continue
        mid = module_id(f["path"])
        seeds: set[str] = set()
        for imp in f["imports"]:
            if not imp["resolved"]:
                continue
            target_mid = module_id(imp["resolved"])
            for name in imp["names"]:
                bare = name.removeprefix("* as ")
                if bare in symbols_by_module[target_mid]:
                    seeds.add(f"{target_mid}.{bare}")
        for call in f["calls"]:
            seeds.add(f"{module_id(call['callee_path'])}.{call['callee']}")

        reached = set(seeds)
        frontier = list(seeds)
        while frontier:
            current = frontier.pop()
            for target in adjacency.get(current, ()):
                if target not in reached:
                    reached.add(target)
                    frontier.append(target)
        reached = {
            s for s in reached if symbol_module.get(s) not in test_module_ids
        }
        reaches = sorted(reached)
        reaches_modules = sorted(
            {symbol_module[s] for s in reached if s in symbol_module}
        )
        for case in f["tests"]:
            records.append(
                {
                    "id": f"{f['path']}::{case['qualname']}",
                    "file": f["path"],
                    "framework": f["test_framework"],
                    "line": case["line"],
                    "symbol": f"{mid}.{case['qualname']}",
                    "reaches": reaches,
                    "reaches_modules": reaches_modules,
                }
            )
    return sorted(records, key=lambda r: r["id"])


def extract_ts(repo_root: Path) -> dict | None:
    """The TS/JS layer for *repo_root*, or None when it has no TS/JS.

    Raises :class:`TsExtractError` when TS/JS files exist but the helper
    can't run — never silently skips (P1).
    """
    repo_root = Path(repo_root)
    if not has_ts_files(repo_root):
        return None
    return join_facts(run_helper(repo_root))
