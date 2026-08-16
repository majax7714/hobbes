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
import re
import shlex
import subprocess
from bisect import bisect_right
from pathlib import Path, PurePosixPath

from hobbes.extract import staging
from hobbes.extract.evidence import SCIP as SCIP_LANE
from hobbes.extract.schema import LANE_SCIP, LANE_TREE_SITTER, tiered_edge

#: Shell-split command replacing ``node <repo>/scip/index.mjs``.
SCIP_CMD_ENV = "HOBBES_SCIP_CMD"

#: Set to "0" to skip lane B entirely — for boxes without the helper
#: installed, and for the lane-A-only tests.
SCIP_ENABLE_ENV = "HOBBES_SCIP"

#: Facts schema this join understands (helper HELPER_VERSION).
#: v2 (V2.M3, ADR-032): facts carry ``dependency_coverage`` on every run.
HELPER_VERSION = 2


class ScipError(RuntimeError):
    """The indexer helper could not run, or answered something unusable."""


def declared_dependencies(repo_root: Path) -> list[str]:
    """Third-party packages the repo says it needs (pyproject.toml).

    Fed to the helper so Decision 4's degradation check has something to
    compare against: an index that resolved *none* of a repo's declared
    dependencies is one whose environment is not installed, and its missing
    third-party edges are absent rather than nonexistent. Without this the
    check is inert — which it silently was until the SELENEX ingest.
    """
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text())
    except (OSError, ValueError):
        return []
    project = data.get("project") or {}
    specs = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        specs.extend(extra)
    names = set()
    for spec in specs:
        if not isinstance(spec, str):
            continue
        # "pkg[extra]>=1.2,<2" -> "pkg"; the index reports bare names.
        name = re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0]
        if name:
            names.add(name)
    return sorted(names)


def declared_npm_dependencies(package_json: Path) -> list[str]:
    """Third-party packages a ``package.json`` says it needs.

    The TypeScript half of Decision 4's degradation input. Without it the
    check has nothing to compare against — and with the old all-or-nothing
    threshold it had nothing useful to say either (ADR-032).
    """
    try:
        data = json.loads(package_json.read_text())
    except (OSError, ValueError):
        return []
    names = set()
    for field in ("dependencies", "devDependencies"):
        section = data.get(field)
        if isinstance(section, dict):
            names.update(k for k in section if isinstance(k, str))
    return sorted(names)


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


#: Config filenames staged verbatim alongside a TypeScript zone's sources.
#: Copied rather than parsed: a ``tsconfig.json`` may carry comments and
#: may ``extends`` a sibling, and copying every one of them sidesteps both
#: without a JSON5 dependency. They are tiny.
_TS_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json", "package.json")


def ts_zones(repo_root: Path, files: list[str]) -> dict[str, list[str]]:
    """Group TS/JS *files* by the directory of their nearest tsconfig.

    The M6 zoning lesson, now applied to lane B: per-package compiler
    options — path aliases above all — only resolve the way that package's
    own build does, so each zone is indexed on its own. This is ADR-027's
    "the config is derived, not authored" for TypeScript, and §3.7's
    root-discovery checklist item.

    Files under no tsconfig at all group under ``""`` and get a generated
    config in the stage, which is exactly what the staging tree is for.
    """
    zones: dict[str, list[str]] = {}
    cache: dict[str, str] = {}
    for rel in files:
        directory = str(PurePosixPath(rel).parent)
        if directory not in cache:
            cache[directory] = _nearest_config_dir(repo_root, directory)
        zones.setdefault(cache[directory], []).append(rel)
    return {zone: sorted(paths) for zone, paths in sorted(zones.items())}


def _nearest_config_dir(repo_root: Path, directory: str) -> str:
    """Directory of the nearest tsconfig at or above *directory*, or ""."""
    current = PurePosixPath(directory)
    while True:
        if (repo_root / current / "tsconfig.json").is_file():
            return "" if str(current) == "." else str(current)
        if str(current) == ".":
            return ""
        current = current.parent


def _nearest_node_modules(repo_root: Path, zone: str) -> Path | None:
    """The dependency tree a zone resolves against, walking up to the root.

    Node resolution walks up from the importing file, and the staging tree
    has nothing above it — so the link has to be placed where the *repo*
    would have found one (ADR-032).
    """
    current = repo_root / zone if zone else repo_root
    repo_root = repo_root.resolve()
    while True:
        candidate = current / "node_modules"
        if candidate.is_dir():
            return candidate
        if current.resolve() == repo_root or current.parent == current:
            return None
        current = current.parent


def _staged_ts_configs(repo_root: Path, files: list[str]) -> list[str]:
    """Every tsconfig/package.json at or above a staged TS file."""
    wanted: set[str] = set()
    for rel in files:
        current = PurePosixPath(rel).parent
        while True:
            for name in _TS_CONFIG_NAMES:
                candidate = current / name if str(current) != "." else PurePosixPath(name)
                if (repo_root / candidate).is_file():
                    wanted.add(str(candidate))
            if str(current) == ".":
                break
            current = current.parent
    return sorted(wanted)


def _generated_tsconfig(files: list[str], zone: str) -> dict:
    """A config for files the repo never gave one.

    Mirrors `tsextract`'s zone-less default project, so both lanes see the
    same language dialect. ``files`` is explicit rather than a glob: a
    root-level config with a default include would swallow every other
    zone's sources and index them under the wrong compiler options.
    """
    prefix = f"{zone}/" if zone else ""
    return {
        "compilerOptions": {
            "allowJs": True,
            "checkJs": False,
            "module": "ESNext",
            "moduleResolution": "Bundler",
            "target": "ES2022",
            "jsx": "preserve",
            "noEmit": True,
            "skipLibCheck": True,
        },
        "files": [
            rel[len(prefix):] if prefix and rel.startswith(prefix) else rel
            for rel in files
        ],
    }


def extract_scip_typescript(
    repo_root: Path, files: list[str], sha: str = ""
) -> dict | None:
    """Index every TypeScript zone and return one merged facts document.

    One indexer run per zone, because a zone is a separate TypeScript
    program (M6). Zones are merged rather than reconciled: they resolve
    independently, so a cross-zone import resolves in neither — which is
    C-12, unchanged by this milestone and now true of both lanes.
    """
    if not enabled() or not files:
        return None
    repo_root = Path(repo_root).resolve()
    merged: dict = {
        "definitions": [],
        "references": [],
        "external_refs": [],
        "packages": {},
        "degraded": [],
        "dependency_coverage": {"declared": 0, "resolved": 0, "missing": []},
    }
    for zone, zone_files in ts_zones(repo_root, files).items():
        facts = _index_ts_zone(repo_root, zone, zone_files, sha)
        if facts is None:
            continue
        for key in ("definitions", "references", "external_refs", "degraded"):
            merged[key].extend(facts.get(key, []))
        for name, count in (facts.get("packages") or {}).items():
            merged["packages"][name] = merged["packages"].get(name, 0) + count
        zone_coverage = facts.get("dependency_coverage") or {}
        merged["dependency_coverage"]["declared"] += zone_coverage.get("declared", 0)
        merged["dependency_coverage"]["resolved"] += zone_coverage.get("resolved", 0)
        merged["dependency_coverage"]["missing"].extend(
            zone_coverage.get("missing", [])
        )
    merged["dependency_coverage"]["missing"] = sorted(
        set(merged["dependency_coverage"]["missing"])
    )
    return merged


def go_modules(repo_root: Path, files: list[str]) -> dict[str, list[str]]:
    """Group Go *files* by the directory of their nearest ``go.mod``.

    The TS zoning lesson, a language later: a Go module is the unit the
    loader understands, and this repo is the worked example — its
    ``go.mod`` is at ``go/``, not the root, so indexing from the repo root
    would find no module at all. Files under no module group under ``""``
    and are skipped rather than guessed at, because a Go file outside a
    module cannot be type-checked and inventing a ``go.mod`` would invent
    its dependencies too.
    """
    modules: dict[str, list[str]] = {}
    cache: dict[str, str | None] = {}
    for rel in files:
        directory = str(PurePosixPath(rel).parent)
        if directory not in cache:
            cache[directory] = _nearest_go_module(repo_root, directory)
        root = cache[directory]
        if root is None:
            continue
        modules.setdefault(root, []).append(rel)
    return {root: sorted(paths) for root, paths in sorted(modules.items())}


def _nearest_go_module(repo_root: Path, directory: str) -> str | None:
    """Directory of the nearest ``go.mod`` at or above *directory*."""
    current = PurePosixPath(directory)
    while True:
        if (repo_root / current / "go.mod").is_file():
            return "" if str(current) == "." else str(current)
        if str(current) == ".":
            return None
        current = current.parent


def extract_scip_go(
    repo_root: Path, files: list[str], sha: str = ""
) -> dict | None:
    """Index every Go module and return one merged facts document.

    One run per ``go.mod``, for the reason TS runs one per tsconfig: the
    module is what the loader resolves against. Paths come back relative to
    the module root and are re-rooted at the repo by :func:`_rebase`, the
    same correction that made or broke the TS lane at V2.M3.
    """
    if not enabled() or not files:
        return None
    repo_root = Path(repo_root).resolve()
    merged: dict = {
        "definitions": [],
        "references": [],
        "external_refs": [],
        "packages": {},
        "degraded": [],
        "dependency_coverage": {"declared": 0, "resolved": 0, "missing": []},
    }
    for module_root, module_files in go_modules(repo_root, files).items():
        facts = _index_go_module(repo_root, module_root, module_files, sha)
        if facts is None:
            continue
        for key in ("definitions", "references", "external_refs", "degraded"):
            merged[key].extend(facts.get(key, []))
        for name, count in (facts.get("packages") or {}).items():
            merged["packages"][name] = merged["packages"].get(name, 0) + count
    return merged


def _index_go_module(
    repo_root: Path, module_root: str, module_files: list[str], sha: str
) -> dict | None:
    """Stage and index one Go module.

    ``go.mod`` and ``go.sum`` are staged with the source: without them the
    loader has no module to root at and no dependency versions to resolve,
    and scip-go fails loudly rather than producing a thin index — which is
    the degradation being visible rather than silent (P6).
    """
    manifest = f"{module_root}/go.mod" if module_root else "go.mod"
    sums = f"{module_root}/go.sum" if module_root else "go.sum"
    staged = set(module_files) | {manifest}
    if (repo_root / sums).is_file():
        staged.add(sums)

    stage = staging.build_stage(repo_root, sorted(staged), sha=sha)
    try:
        facts = run_helper(
            {
                "stage": str(stage / module_root if module_root else stage),
                "language": "go",
                "projectName": repo_root.name,
                # Pinned for the third time, under a third flag name
                # (ADR-037): scip-go's --module-version defaults to the git
                # revision exactly as scip-python's --project-version does.
                "projectVersion": "0",
                "output": str(stage.parent / f"{stage.name}.scip"),
                "declaredDeps": [],
            }
        )
    finally:
        staging.remove_stage(stage)
    return _rebase(facts, module_root)


def _index_ts_zone(
    repo_root: Path, zone: str, zone_files: list[str], sha: str
) -> dict | None:
    """Stage and index one TypeScript zone."""
    staged = sorted(set(zone_files) | set(_staged_ts_configs(repo_root, zone_files)))
    links = {}
    dependencies = _nearest_node_modules(repo_root, zone)
    if dependencies is not None:
        # Placed where the repo would have found one, relative to the zone.
        anchor = dependencies.parent.relative_to(repo_root).as_posix()
        rel = "node_modules" if anchor == "." else f"{anchor}/node_modules"
        links[rel] = str(dependencies.resolve())

    configs = {}
    zone_config = f"{zone}/tsconfig.json" if zone else "tsconfig.json"
    if not (repo_root / zone_config).is_file():
        configs[zone_config] = _generated_tsconfig(zone_files, zone)

    package_json = repo_root / (f"{zone}/package.json" if zone else "package.json")
    declared = (
        declared_npm_dependencies(package_json) if package_json.is_file() else []
    )

    stage = staging.build_stage(repo_root, staged, sha=sha, configs=configs, links=links)
    try:
        facts = run_helper(
            {
                "stage": str(stage / zone if zone else stage),
                "language": "typescript",
                "projectName": repo_root.name,
                "projectVersion": "0",
                "output": str(stage.parent / f"{stage.name}.scip"),
                "declaredDeps": declared,
            }
        )
    finally:
        staging.remove_stage(stage)
    return _rebase(facts, zone)


def _rebase(facts: dict, zone: str) -> dict:
    """Re-root a zone's file paths at the repo.

    A zone is indexed with ``--cwd`` at *its own* directory, so SCIP
    reports ``src/App.tsx`` where lane A says ``web/src/App.tsx``. The two
    providers must speak the same paths or the range join silently matches
    nothing — which is not an error, just a graph with no semantic TS
    edges and a coverage denominator full of holes. Python never hit this
    because its ``--cwd`` is the stage root, where the two already agree.
    """
    if not zone:
        return facts
    def at(path: str) -> str:
        return f"{zone}/{path}" if path else path

    for ref in facts.get("references", []):
        ref["file"] = at(ref["file"])
        ref["def_file"] = at(ref["def_file"])
    for definition in facts.get("definitions", []):
        definition["file"] = at(definition["file"])
    for ref in facts.get("external_refs", []):
        ref["file"] = at(ref["file"])
    return facts


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
