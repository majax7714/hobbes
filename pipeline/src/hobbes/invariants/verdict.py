"""Invariant verdicts from the module graph (ADR-025).

``hobbes review`` answers "does this rule hold?" in-process, reading
``graph.json`` — not by shelling out to import-linter or semgrep. The
graph already knows who imports whom, so a forbidden-import rule is a
question it can answer; and a review that needs no toolchain runs
anywhere the extractor does, deterministically and without quota.

What the graph cannot see, this refuses to guess. A semgrep rule matches
source patterns and a Rego rule reads a Terraform plan; neither is in
the graph, so those verdicts are ``unknown`` with the reason attached.
**Never a false pass** — an invariant reported green because nothing
checked it is worse than one reported unchecked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hobbes.invariants.schema import Invariant, scope_matches

#: Verdict values, worst first — the order a review sorts by.
FAIL = "fail"
UNKNOWN = "unknown"
SOFT = "soft"
PASS = "pass"
SKIPPED = "skipped"

_SEVERITY = {FAIL: 0, UNKNOWN: 1, SOFT: 2, PASS: 3, SKIPPED: 4}


@dataclass
class Violation:
    """One concrete breach, cited where the extractor saw it."""

    importer: str
    imported: str
    path: str = ""
    line: int = 0

    def cite(self) -> str:
        where = f" [{self.path}:{self.line}]" if self.path else ""
        return f"{self.importer} -> {self.imported}{where}"


@dataclass
class Verdict:
    """The judgement on one invariant."""

    invariant: Invariant
    result: str
    #: Why, in one line — always set for unknown and fail.
    reason: str = ""
    violations: list[Violation] = field(default_factory=list)
    #: Guards from ``guarded_by`` that no longer exist in tests.json.
    missing_guards: list[str] = field(default_factory=list)

    @property
    def severity(self) -> int:
        return _SEVERITY[self.result]


def judge_all(
    invariants: list[Invariant],
    graph: dict,
    test_ids: set[str] | None = None,
) -> list[Verdict]:
    """Judge every invariant against *graph*, worst verdict first."""
    verdicts = [judge(inv, graph, test_ids) for inv in invariants]
    return sorted(verdicts, key=lambda v: (v.severity, v.invariant.id))


def judge(
    invariant: Invariant, graph: dict, test_ids: set[str] | None = None
) -> Verdict:
    """Judge one invariant."""
    missing = sorted(
        g for g in invariant.guarded_by if test_ids is not None and g not in test_ids
    )

    if not invariant.confirmed:
        return Verdict(
            invariant,
            SKIPPED,
            reason=f"status is {invariant.status}; only confirmed records are judged",
            missing_guards=missing,
        )

    if invariant.soft:
        return Verdict(
            invariant,
            SOFT,
            reason="not mechanically checkable — a reviewer session must judge it "
            "and cite evidence",
            missing_guards=missing,
        )

    kind = invariant.kind
    if kind == "forbidden-import":
        return _judge_forbidden_import(invariant, graph, missing)

    # Compiled for CI, unanswerable here — and said so rather than passed.
    where = {
        "pattern-absent": "source patterns, which live in the AST rather than the graph",
        "resource-attribute": "a terraform plan, which the graph does not carry",
    }.get(kind, "something the graph does not record")
    return Verdict(
        invariant,
        UNKNOWN,
        reason=f"{invariant.target} checks {where}; compiled for CI, not judged here",
        missing_guards=missing,
    )


def _judge_forbidden_import(
    invariant: Invariant, graph: dict, missing: list[str]
) -> Verdict:
    """Evaluate a forbidden-import rule against the module graph."""
    rule = invariant.rule
    importers = rule.get("importers") or []
    allowed = set(rule.get("except") or [])
    forbidden = set(rule.get("imported") or [])

    # Scope bounds who the rule is about: `*` means everything under it,
    # not everything in the repo.
    paths = {node["id"]: node.get("path") for node in graph.get("nodes", [])}
    in_scope = {
        node_id
        for node_id, path in paths.items()
        if scope_matches(invariant.scope, path)
    }

    violations: list[Violation] = []
    for edge in graph.get("module_edges", []):
        if edge.get("type") != "imports" or edge.get("to") not in forbidden:
            continue
        source = edge.get("from", "")
        if source in allowed:
            continue
        if not _any_match(importers, source):
            continue
        # An importer with no path (an external or synthetic node) cannot
        # be placed in a scope, so the scope does not bind it.
        if paths.get(source) is not None and source not in in_scope:
            continue
        evidence = (edge.get("evidence") or [{}])[0]
        violations.append(
            Violation(
                importer=source,
                imported=edge.get("to", ""),
                path=evidence.get("path", ""),
                line=evidence.get("line", 0),
            )
        )

    violations.sort(key=lambda v: (v.importer, v.imported, v.line))
    if violations:
        return Verdict(
            invariant,
            FAIL,
            reason=f"{len(violations)} forbidden import(s)",
            violations=violations,
            missing_guards=missing,
        )
    return Verdict(
        invariant,
        PASS,
        reason=f"no module in {invariant.scope} imports "
        f"{', '.join(sorted(forbidden))} outside the exceptions",
        missing_guards=missing,
    )


def _any_match(patterns: list[str], node_id: str) -> bool:
    """Whether *node_id* matches any importer pattern.

    ``*`` is everything; ``prefix.*`` and ``prefix/*`` match a package or
    directory (both id shapes exist — dotted for Python, path for TS/JS,
    ADR-021); anything else is an exact id.
    """
    for pattern in patterns:
        if pattern == "*":
            return True
        for separator in (".", "/"):
            if pattern.endswith(separator + "*"):
                if node_id.startswith(pattern[:-1]):
                    return True
                break
        else:
            if pattern == node_id:
                return True
    return False
