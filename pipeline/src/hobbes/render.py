"""Module-level Mermaid export of graph.json (ADR-008).

:func:`to_mermaid` maps the module layer of a graph document onto a
``flowchart LR``: internal modules clustered by top-level package, external
dependencies and environment variables shape-styled, edges styled by type.
Deterministic — the same document always yields the same text. The symbol
layer is never rendered here (architecture §10: render module-level).
"""

from __future__ import annotations

#: Edge types with dedicated arrow styles; anything new renders labeled so
#: it is visible before it earns bespoke styling (ADR-008).
_EDGE_ARROWS = {"imports": "-->", "env-read": "-.->"}


def to_mermaid(graph: dict) -> str:
    """Render a graph.json document as a Mermaid flowchart."""
    nodes = sorted(graph["nodes"], key=lambda n: n["id"])
    tokens = {node["id"]: f"n{i}" for i, node in enumerate(nodes)}

    lines = ["flowchart LR"]
    lines += _node_lines(nodes, tokens)
    lines += _edge_lines(graph["module_edges"], tokens)
    return "\n".join(lines) + "\n"


def _declaration(node: dict, token: str) -> str:
    label = node["id"].replace('"', "'")
    if node["kind"] == "external":
        return f'{token}[["{label}"]]'
    if node["kind"] == "env":
        return f'{token}(["{label}"])'
    return f'{token}["{label}"]'


def _group_key(node_id: str) -> str:
    """Top-level package of an internal node id. Root-disambiguated ids
    (``pipeline:tests.test_cli``) keep their prefix with the first dotted
    component, so the two ``tests`` packages cluster separately."""
    return node_id.split(".", 1)[0]


def _node_lines(nodes: list[dict], tokens: dict[str, str]) -> list[str]:
    internal = [n for n in nodes if n["kind"] in ("module", "package")]
    other = [n for n in nodes if n["kind"] not in ("module", "package")]

    groups: dict[str, list[dict]] = {}
    for node in internal:
        groups.setdefault(_group_key(node["id"]), []).append(node)

    lines = []
    for i, (key, members) in enumerate(sorted(groups.items())):
        if len(members) == 1:  # one-node boxes are noise (ADR-008)
            lines.append(f"  {_declaration(members[0], tokens[members[0]['id']])}")
            continue
        lines.append(f'  subgraph sg{i}["{key}"]')
        lines += [
            f"    {_declaration(m, tokens[m['id']])}" for m in members
        ]
        lines.append("  end")
    lines += [f"  {_declaration(n, tokens[n['id']])}" for n in other]
    return lines


def _edge_lines(module_edges: list[dict], tokens: dict[str, str]) -> list[str]:
    lines = []
    for edge in sorted(
        module_edges, key=lambda e: (e["from"], e["to"], e["type"])
    ):
        arrow = _EDGE_ARROWS.get(edge["type"], f'--"{edge["type"]}"-->')
        lines.append(f"  {tokens[edge['from']]} {arrow} {tokens[edge['to']]}")
    return lines
