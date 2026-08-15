"""Lane B: SCIP-proven edges joined onto lane A's structure (§3.2, §3.4).

The helper in ``scip/`` runs an indexer over a staging tree and hands back
definitions and references with file:line coordinates. This module does the
**range join** §3.4 describes: SCIP occurrences carry ranges, lane A's
symbols carry ranges, so a reference at ``file:line`` is attributed to
whichever lane-A symbol encloses it, and pointed at whichever lane-A symbol
its definition starts.

Joining on ranges rather than on ids is what keeps V2.M2 from churning node
identity: the graph's ids stay lane A's, and what lane B contributes is
*confidence* — the same edge, at ``tier: semantic`` instead of
``syntactic``. ADR-028 reserved a ``scip:`` namespace for ids lane B would
have to invent; the range join means M2 barely needs it.

Since ADR-029 the join is not between two finished edge sets but between
two *providers*: tree-sitter's call sites and SCIP's resolutions meet in
the evidence IR (:mod:`hobbes.extract.evidence`) before any graph exists.
This module's job is to get SCIP's facts into that IR and to project the
result back onto lane A's module and symbol ids.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from bisect import bisect_right
from pathlib import Path

from hobbes.extract import staging
from hobbes.extract.evidence import SCIP as SCIP_LANE
from hobbes.extract.schema import LANE_SCIP, LANE_TREE_SITTER, tiered_edge

#: Shell-split command replacing ``node <repo>/scip/index.mjs``.
SCIP_CMD_ENV = "HOBBES_SCIP_CMD"

#: Set to "0" to skip lane B entirely — for boxes without the helper
#: installed, and for the lane-A-only tests.
SCIP_ENABLE_ENV = "HOBBES_SCIP"

#: Facts schema this join understands (helper HELPER_VERSION).
HELPER_VERSION = 1


class ScipError(RuntimeError):
    """The indexer helper could not run, or answered something unusable."""


def enabled() -> bool:
    """Whether lane B should run at all."""
    return os.environ.get(SCIP_ENABLE_ENV, "1") not in ("0", "false", "no")


def _helper_cmd() -> list[str]:
    override = os.environ.get(SCIP_CMD_ENV)
    if override:
        return shlex.split(override)
    helper = Path(__file__).resolve().parents[4] / "scip" / "index.mjs"
    return ["node", str(helper)]


def run_helper(config: dict, timeout: int = 900) -> dict:
    """Run the helper with *config* and return its parsed facts."""
    stage = Path(config["stage"])
    config_path = stage.parent / f"{stage.name}.config.json"
    config_path.write_text(json.dumps(config))
    setup = (
        "the SCIP helper is unusable — install Node and run `npm install` in "
        f"the hobbes repo's scip/, or set ${SCIP_CMD_ENV} (ADR-027)"
    )
    try:
        proc = subprocess.run(
            [*_helper_cmd(), "--config", str(config_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ScipError(f"{setup}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScipError(f"the SCIP indexer timed out on {stage}") from exc
    finally:
        config_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-500:]
        raise ScipError(f"{setup}: helper exited {proc.returncode}: {detail}")
    try:
        facts = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ScipError(f"the SCIP helper emitted invalid JSON: {exc}") from exc
    if facts.get("helper_version") != HELPER_VERSION:
        raise ScipError(
            f"SCIP facts version {facts.get('helper_version')!r} unsupported "
            f"(want {HELPER_VERSION})"
        )
    return facts


class _SymbolIndex:
    """Lane A's symbols, queryable by file and line.

    Two questions, because a reference has two ends: which symbol *encloses*
    this line (the caller), and which symbol *starts* at it (the callee).
    """

    def __init__(self, nodes: list[dict], symbols: list[dict]):
        self.module_of_path = {
            n["path"]: n["id"] for n in nodes if n.get("path")
        }
        self._by_module: dict[str, list[dict]] = {}
        for symbol in symbols:
            self._by_module.setdefault(symbol["module"], []).append(symbol)
        for rows in self._by_module.values():
            rows.sort(key=lambda s: (s["line"], -(s.get("end_line") or s["line"])))
        self._starts = {
            module: [s["line"] for s in rows]
            for module, rows in self._by_module.items()
        }

    def module(self, path: str) -> str | None:
        return self.module_of_path.get(path)

    def enclosing(self, module: str, line: int) -> str | None:
        """The innermost symbol whose range contains *line*."""
        rows = self._by_module.get(module)
        if not rows:
            return None
        cut = bisect_right(self._starts[module], line)
        best = None
        for symbol in rows[:cut]:
            end = symbol.get("end_line") or symbol["line"]
            if symbol["line"] <= line <= end:
                # Later starts are more deeply nested, so the last match wins.
                best = symbol["id"]
        return best

    def starting_at(self, module: str, line: int) -> str | None:
        """The symbol defined at *line*, innermost first."""
        rows = self._by_module.get(module)
        if not rows:
            return None
        matches = [s["id"] for s in rows if s["line"] == line]
        return matches[-1] if matches else None


def resolution_sites(facts: dict) -> list:
    """SCIP's references as evidence-IR resolution sites (ADR-029)."""
    from hobbes.extract.evidence import RESOLUTION, SCIP, Site

    return [
        Site(
            provider=SCIP,
            kind=RESOLUTION,
            file=ref["file"],
            line=ref["line"],
            name=ref.get("name", ""),
            col=ref.get("col", -1),
            def_file=ref["def_file"],
            def_line=ref["def_line"],
        )
        for ref in facts.get("references", [])
    ]


def project(resolved: list, nodes: list[dict], symbols: list[dict]) -> dict:
    """Project semantic-IR facts onto lane A's module and symbol ids.

    The IR speaks in files and lines because that is what both providers
    can agree on; the graph speaks in ids. This is the only place the two
    vocabularies meet, and it resolves ends the same way for every fact
    kind — the source is whatever symbol encloses the site, the target is
    whatever symbol the definition starts.
    """
    index = _SymbolIndex(nodes, symbols)
    module_evidence: dict[tuple, list] = {}
    symbol_evidence: dict[tuple, list] = {}

    for fact in resolved:
        source_module = index.module(fact.source_file)
        target_module = index.module(fact.def_file)
        if source_module is None or target_module is None:
            continue  # a file lane A never discovered; not ours to name
        lane = LANE_SCIP if SCIP_LANE in fact.lanes else LANE_TREE_SITTER
        site = {"path": fact.source_file, "line": fact.line}

        if source_module != target_module:
            key = (source_module, target_module, "imports", fact.tier, lane)
            module_evidence.setdefault(key, []).append(site)

        caller = fact.scope or index.enclosing(source_module, fact.line) or source_module
        callee = index.starting_at(target_module, fact.def_line)
        if callee is None or caller == callee:
            continue
        key = (caller, callee, fact.kind, fact.tier, lane)
        symbol_evidence.setdefault(key, []).append(site)

    return {
        "module_edges": _edges(module_evidence),
        "symbol_edges": _edges(symbol_evidence),
    }


def _edges(evidence: dict[tuple, list]) -> list[dict]:
    """Collapse sightings into edges, keeping tier and lane distinct.

    Two facts with the same endpoints but different tiers are two different
    claims — one proven, one guessed — so they stay separable here, and the
    graph decides which survives rather than this function guessing.
    """
    out = []
    for (source, target, edge_type, tier, lane), sightings in sorted(evidence.items()):
        unique = sorted({(s["path"], s["line"]) for s in sightings})
        out.append(
            tiered_edge(
                source,
                target,
                edge_type,
                [{"path": path, "line": line} for path, line in unique],
                tier=tier,
                lane=lane,
            )
        )
    return out


def extract_scip(
    repo_root: Path,
    files: list[str],
    roots: list[str],
    project_name: str,
    sha: str,
    declared_deps: list[str] | None = None,
) -> dict | None:
    """Stage *files*, index them, and return joined facts — or None.

    Returns None when lane B is disabled. Every write lands in the staging
    tree (ADR-027): the repo is read and never touched.
    """
    if not enabled() or not files:
        return None
    stage = staging.build_stage(
        repo_root,
        files,
        config={
            "extraPaths": roots,
            # Absolute, so third-party resolution survives staging — without
            # it every dependency edge silently vanishes (ADR-027 Decision 4).
            "venvPath": str(Path(repo_root).resolve()),
            "venv": ".venv",
        },
        sha=sha,
    )
    try:
        facts = run_helper(
            {
                "stage": str(stage),
                "language": "python",
                "projectName": project_name,
                # Pinned, never defaulted: the default is the git revision,
                # which would change every moniker on every commit.
                "projectVersion": "0",
                "output": str(stage.parent / f"{stage.name}.scip"),
                "declaredDeps": declared_deps or [],
            }
        )
    finally:
        staging.remove_stage(stage)
    return facts
