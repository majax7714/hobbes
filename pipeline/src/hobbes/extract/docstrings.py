"""Module docstring normalization, for the narrative pass's context.

The cartographer currently sees a module's symbols but not the prose the
author already wrote. A module docstring is the one piece of narrative
that is authored rather than inferred, so feeding it into the M5 prompt
should cut the cases where a generated purpose restates what the
docstring already says better.

This module takes the literal :mod:`hobbes.extract.pysource` captured
during its walk and normalizes it. It does not parse: a second parser
could disagree with the first about what the file says, and only the two
source extractors own that job (I-4).
"""

from __future__ import annotations

from hobbes.extract.pysource import ParsedFile

_QUOTES = ('"""', "'''", '"', "'")


def module_docstring(parsed: ParsedFile) -> str | None:
    """The module's docstring text, unquoted, or None when it has none."""
    if parsed.docstring is None:
        return None
    return _strip_quotes(parsed.docstring)


def summary(parsed: ParsedFile) -> str | None:
    """The docstring's first paragraph on one line — the prompt-sized part.

    A module docstring's opening paragraph is its thesis; the rest is
    detail the cartographer can read from the code.
    """
    text = module_docstring(parsed)
    if not text:
        return None
    paragraph = text.split("\n\n", 1)[0]
    return " ".join(paragraph.split()) or None


def _strip_quotes(literal: str) -> str:
    """The docstring's content, without its quoting or prefix."""
    body = literal.lstrip("rRbBuUfF")
    for quote in _QUOTES:
        if body.startswith(quote) and body.endswith(quote) and len(body) >= 2 * len(quote):
            return body[len(quote) : -len(quote)].strip()
    return body.strip()
