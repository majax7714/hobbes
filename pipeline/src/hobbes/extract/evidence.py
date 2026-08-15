"""The evidence IR and the range join (ADR-029).

Two providers, one shape. **tree-sitter** knows what a thing *is* — this is
a call site, this is an import statement, this symbol spans these lines —
and never what it resolves to. **SCIP** knows what an occurrence *resolves
to* and never what it syntactically was, because scip-python populates
``syntax_kind`` for none of its occurrences.

So neither provider is asked a question it would have to guess at, and the
answer that matters — *a call, pointing where it actually goes* — is
produced by joining them on ranges before any graph exists:

    tree-sitter ─┐
                 ├─► evidence IR ──(join)──► semantic IR ──► graph builder
    SCIP ────────┘

A post-hoc merge of finished edges could never produce that: it can only
compare edges that already exist, and the edge wanted here belongs to
neither lane alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

#: Providers. Values double as the ``lane`` on emitted evidence, so the
#: artifact says which of them saw each sighting (P3).
TREE_SITTER = "tree-sitter"
SCIP = "scip"

#: Evidence kinds a syntax provider emits.
CALL_SITE = "call-site"
IMPORT_SITE = "import-site"
DEFINITION = "definition"

#: Evidence kinds a semantic provider emits.
RESOLUTION = "resolution"


@dataclass(frozen=True)
class Site:
    """One range-anchored observation.

    *name* is the identifying text the provider saw — a callee's last
    segment for a call site, a symbol's terminal descriptor for a
    resolution. It is what disambiguates several sightings sharing a line.
    """

    provider: str
    kind: str
    file: str
    line: int
    name: str = ""
    col: int = -1
    #: Syntax provider only: the symbol id enclosing this site, if any.
    scope: str = ""
    #: Semantic provider only: where the resolved definition lives.
    def_file: str = ""
    def_line: int = 0


@dataclass
class Resolved:
    """One semantic-IR fact: a role, a target, and the tier it earned."""

    kind: str
    source_file: str
    line: int
    scope: str
    def_file: str
    def_line: int
    tier: str
    lanes: tuple[str, ...]
    evidence: list[dict] = field(default_factory=list)


def index_resolutions(sites: list[Site]) -> dict[tuple[str, int], list[Site]]:
    """SCIP resolutions, bucketed by the line they sit on."""
    buckets: dict[tuple[str, int], list[Site]] = defaultdict(list)
    for site in sites:
        if site.kind == RESOLUTION:
            buckets[(site.file, site.line)].append(site)
    return buckets


def match_resolution(
    site: Site, buckets: dict[tuple[str, int], list[Site]]
) -> Site | None:
    """The resolution for a syntax *site*, or None.

    Line alone is ambiguous — one line routinely holds several references —
    so the name must agree too. Column breaks the remaining ties by
    proximity, which is why the evidence IR carries it.
    """
    candidates = buckets.get((site.file, site.line), [])
    if not candidates:
        return None
    named = [c for c in candidates if c.name and c.name == site.name]
    if not named:
        return None
    if len(named) == 1 or site.col < 0:
        return named[0]
    return min(named, key=lambda c: abs(c.col - site.col) if c.col >= 0 else 1 << 30)


def join(
    syntax: list[Site],
    semantic: list[Site],
    fallback: dict[tuple[str, int, str], tuple[str, int]] | None = None,
) -> list[Resolved]:
    """Join syntax sites against semantic resolutions (ADR-029's table).

    *fallback* is lane A's own resolution for a site, keyed by
    ``(file, line, name)`` — used only where SCIP resolved nothing, and
    marked ``syntactic`` when it is. Sites nothing resolves are dropped:
    an unresolved call is not an edge, which is ADR-007's rule unchanged.
    """
    from hobbes.extract.schema import SEMANTIC, SYNTACTIC

    buckets = index_resolutions(semantic)
    fallback = fallback or {}
    out: list[Resolved] = []
    claimed: set[tuple[str, int, str]] = set()

    for site in syntax:
        if site.kind not in (CALL_SITE, IMPORT_SITE):
            continue
        kind = "calls" if site.kind == CALL_SITE else "imports"
        hit = match_resolution(site, buckets)
        if hit is not None:
            claimed.add((hit.file, hit.line, hit.name))
            out.append(
                Resolved(
                    kind=kind,
                    source_file=site.file,
                    line=site.line,
                    scope=site.scope,
                    def_file=hit.def_file,
                    def_line=hit.def_line,
                    tier=SEMANTIC,
                    lanes=(TREE_SITTER, SCIP),
                    evidence=[{"path": site.file, "line": site.line}],
                )
            )
            continue
        guess = fallback.get((site.file, site.line, site.name))
        if guess is None:
            continue  # unresolved: not an edge, ADR-007 unchanged
        out.append(
            Resolved(
                kind=kind,
                source_file=site.file,
                line=site.line,
                scope=site.scope,
                def_file=guess[0],
                def_line=guess[1],
                tier=SYNTACTIC,
                lanes=(TREE_SITTER,),
                evidence=[{"path": site.file, "line": site.line}],
            )
        )

    # Every resolution no syntax site claimed is a real use — a type
    # annotation, an `except` clause, a value passed by name. True, useful
    # for dependency questions, and emphatically not a call.
    for (file, line), sites in sorted(buckets.items()):
        for hit in sites:
            if (hit.file, hit.line, hit.name) in claimed:
                continue
            out.append(
                Resolved(
                    kind="references",
                    source_file=file,
                    line=line,
                    scope="",
                    def_file=hit.def_file,
                    def_line=hit.def_line,
                    tier=SEMANTIC,
                    lanes=(SCIP,),
                    evidence=[{"path": file, "line": line}],
                )
            )
    return out
