"""Impact set → work units (ADR-051; agent-mapping §3.2).

Minimize cut coupling subject to a per-unit context budget:

- **node weight** — representation cost: the module's file, its
  guarding test files, and its module doc, estimated in tokens
  (bytes/4). What an agent must *hold* to own the module.
- **edge weight** — coupling: tier × edge-type weight × reference
  count × co-change factor. What separating two modules would *cost*.
- **constraint** — a unit's total weight fits the budget, held well
  below the window ceiling because accuracy degrades before capacity.

**Agent count is the partition's output, not a parameter.** A contained
change yields one unit; a cross-cutting one yields several; the
codebase decides. The merge is agglomerative and greedy — strongest
coupling first, deterministic tie-breaks — because the weights are
declared guesses (C-35) and a solver's optimality would be precision
painted onto numbers that have never been validated.

Two explicit failure rules from the design's §7: a unit whose contract
overhead reaches its interior weight merges into its strongest
neighbor (over-decomposition — coordination that costs more than the
code it coordinates), and a single module larger than the budget is
flagged ``oversize`` rather than split — the partition's grain is the
module, a stated D1 limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hobbes.derive.cochange import CoChange
from hobbes.derive.impact import edge_factor, module_adjacency

#: Estimated tokens per unit (ADR-051, C-35). Overridable per plan.
DEFAULT_BUDGET = 60_000

#: Estimated cost of holding one pinned contract (ADR-051, C-35) —
#: the over-decomposition rule's currency.
CONTRACT_OVERHEAD = 300

#: Partitionable node kinds: things that are files someone edits.
#: env/ext/tf nodes are impact facts, not work.
_UNIT_KINDS = {"module", "package"}


@dataclass
class Unit:
    """One work unit: a single-use agent's whole responsibility."""

    name: str
    modules: list[str]
    weight: int
    flags: list[str] = field(default_factory=list)


def unit_modules(graph: dict, scores: dict[str, float]) -> list[str]:
    """The impact nodes that are partitionable work, sorted."""
    kinds = {n["id"]: n.get("kind") for n in graph.get("nodes", [])}
    return sorted(m for m in scores if kinds.get(m) in _UNIT_KINDS)


def guarding_tests(graph: dict, tests: dict) -> dict[str, list[str]]:
    """module id -> ids of tests whose reach includes one of its symbols."""
    owners: dict[str, str] = {}
    for symbol in graph.get("symbols", []):
        owners[symbol["id"]] = symbol.get("module", "")
    guards: dict[str, list[str]] = {}
    for test in tests.get("tests", []):
        for reached in test.get("reaches", []):
            module = owners.get(reached)
            if module:
                bucket = guards.setdefault(module, [])
                if test["id"] not in bucket:
                    bucket.append(test["id"])
    return guards


def node_weights(
    repo_root: Path, graph: dict, tests: dict
) -> dict[str, int]:
    """module id -> representation cost in estimated tokens (bytes/4).

    Counts the module's own file, each guarding test's file (once per
    module), and its module doc when narrate has produced one. A file
    the tree no longer holds counts zero — the graph is stamped at a
    SHA and the tree may have moved; the plan reflects what is there.
    """
    paths = {n["id"]: n.get("path") for n in graph.get("nodes", [])}
    test_files = {t["id"]: t.get("file", "") for t in tests.get("tests", [])}
    guards = guarding_tests(graph, tests)

    def size(rel: str | None) -> int:
        if not rel:
            return 0
        target = Path(repo_root) / rel
        return target.stat().st_size if target.is_file() else 0

    weights: dict[str, int] = {}
    for module, path in paths.items():
        if path is None:
            continue
        total = size(path)
        for file in sorted({test_files.get(t, "") for t in guards.get(module, [])}):
            total += size(file)
        doc = Path(repo_root) / ".hobbes/derived/docs/modules" / f"{module}.json"
        if doc.is_file():
            total += doc.stat().st_size
        weights[module] = total // 4
    return weights


def module_coupling(
    graph: dict, modules: list[str], cochange: CoChange
) -> dict[tuple[str, str], float]:
    """Pairwise coupling among *modules*: tier × type × refs × co-change."""
    paths = {n["id"]: n.get("path") for n in graph.get("nodes", [])}
    adjacency = module_adjacency(graph)
    wanted = set(modules)
    coupling: dict[tuple[str, str], float] = {}
    for a in modules:
        for b, edges in adjacency.get(a, {}).items():
            if b not in wanted or b <= a:
                continue
            # adjacency[a][b] holds each crossing edge once; the b <= a
            # guard above means every pair is visited once too.
            strength = sum(
                edge_factor(e) * max(len(e.get("evidence") or []), 1)
                for e in edges
            )
            coupling[(a, b)] = strength * cochange.factor(paths.get(a), paths.get(b))
    return coupling


def build_units(
    modules: list[str],
    weights: dict[str, int],
    coupling: dict[tuple[str, str], float],
    budget: int = DEFAULT_BUDGET,
) -> list[Unit]:
    """Agglomerative merge under *budget*; returns named, ordered units."""
    members: dict[int, list[str]] = {i: [m] for i, m in enumerate(modules)}
    home = {m: i for i, m in enumerate(modules)}

    def unit_weight(i: int) -> int:
        return sum(weights.get(m, 0) for m in members[i])

    def pair_coupling(i: int, j: int) -> float:
        total = 0.0
        for a in members[i]:
            for b in members[j]:
                key = (a, b) if a < b else (b, a)
                total += coupling.get(key, 0.0)
        return total

    def strongest_mergeable() -> tuple[int, int] | None:
        best: tuple[float, str, int, int] | None = None
        ids = sorted(members)
        for x, i in enumerate(ids):
            for j in ids[x + 1:]:
                strength = pair_coupling(i, j)
                if strength <= 0.0:
                    continue
                if unit_weight(i) + unit_weight(j) > budget:
                    continue
                # Ties break on the smallest member id, so runs repeat.
                first = min(members[i][0], members[j][0])
                if best is None or (-strength, first) < (best[0], best[1]):
                    best = (-strength, first, i, j)
        return (best[2], best[3]) if best else None

    while (pair := strongest_mergeable()) is not None:
        i, j = pair
        absorbed = members.pop(j)
        for m in absorbed:
            home[m] = i
        members[i] = sorted(members[i] + absorbed)

    # Over-decomposition (design §7): a unit whose contract overhead
    # reaches its interior merges into its strongest neighbor if that
    # still fits; otherwise it stays, flagged — never silently.
    def neighbor_contracts(i: int) -> dict[int, float]:
        out: dict[int, float] = {}
        for j in members:
            if j != i and (c := pair_coupling(i, j)) > 0:
                out[j] = c
        return out

    for i in sorted(members):
        if i not in members:
            continue
        neighbors = neighbor_contracts(i)
        overhead = CONTRACT_OVERHEAD * _cut_degree(members[i], coupling)
        if not neighbors or unit_weight(i) > overhead:
            continue
        j = max(sorted(neighbors), key=lambda n: (neighbors[n], -n))
        if unit_weight(i) + unit_weight(j) <= budget:
            for m in members.pop(i):
                home[m] = j
            members[j] = sorted({m for m, h in home.items() if h == j})

    units: list[Unit] = []
    ordered = sorted(members.values(), key=lambda ms: (-sum(
        weights.get(m, 0) for m in ms), ms[0]))
    for index, ms in enumerate(ordered, start=1):
        weight = sum(weights.get(m, 0) for m in ms)
        flags: list[str] = []
        if len(ms) == 1 and weight > budget:
            flags.append(
                "oversize: one module exceeds the budget alone; the "
                "partition's grain is the module (D1 limit)"
            )
        interior = weight
        overhead = CONTRACT_OVERHEAD * _cut_degree(ms, coupling)
        if overhead and interior <= overhead:
            flags.append(
                "coordination-heavy: contract overhead rivals the interior "
                "and no neighbor had room to absorb it"
            )
        units.append(Unit(name=f"U{index}", modules=ms, weight=weight,
                          flags=flags))
    return units


def _cut_degree(modules: list[str], coupling: dict[tuple[str, str], float]) -> int:
    """How many coupled pairs cross this member set's boundary."""
    inside = set(modules)
    return sum(
        1 for (a, b) in coupling
        if (a in inside) != (b in inside)
    )
