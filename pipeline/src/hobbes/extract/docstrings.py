"""Module docstring extraction, for the narrative pass's context.

The cartographer currently sees a module's symbols but not the prose the
author already wrote about it. A module docstring is the one piece of
narrative that is authored rather than inferred, so feeding it into the
M5 prompt should cut the cases where a generated purpose restates what
the docstring already says better.
"""

from __future__ import annotations

import tree_sitter_python
from tree_sitter import Language, Parser

_PARSER = Parser(Language(tree_sitter_python.language()))


def module_docstring(source: bytes) -> str | None:
    """The module-level docstring, or None when there isn't one.

    A module docstring is the first statement in the file and a bare
    string expression; anything else means the module has none.
    """
    root = _PARSER.parse(source).root_node
    for child in root.named_children:
        if child.type != "expression_statement":
            return None
        inner = child.named_children[0] if child.named_children else None
        if inner is None or inner.type != "string":
            return None
        text = (inner.text or b"").decode("utf-8", "replace")
        return _strip_quotes(text)
    return None


def _strip_quotes(literal: str) -> str:
    """The docstring's content, without its quoting."""
    for quote in ('"""', "'''", '"', "'"):
        if literal.startswith(quote) and literal.endswith(quote):
            return literal[len(quote) : -len(quote)].strip()
    return literal.strip()
