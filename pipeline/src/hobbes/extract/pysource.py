"""Single-file Python extraction: the tree-sitter walk (ADR-005).

:func:`parse_source` turns one file's bytes into the raw facts later stages
assemble into graphs: imports, symbols (with decorators, for routes and test
detection), call sites, and environment-variable reads. Everything here is
per-file and unresolved — cross-module resolution is :mod:`hobbes.extract.graph`'s
job (ADR-007).

Tree-sitter parses error-tolerantly, so files with syntax errors yield
partial facts instead of failing the ingest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python
from tree_sitter import Language, Node, Parser

_PARSER = Parser(Language(tree_sitter_python.language()))

#: Dotted callee texts recognized as environment reads (ADR-007). Pattern
#: match on the text, not on whether `os` is really the os module — the
#: false-positive risk (a local `os` that isn't the module) is negligible
#: against the value of the env: join keys for M3's cross-layer edges.
_ENV_CALLS = {"os.getenv", "getenv", "os.environ.get", "environ.get"}
_ENV_SUBSCRIPTS = {"os.environ", "environ"}


@dataclass(frozen=True)
class PlainImport:
    """``import a.b`` / ``import a.b as c``."""

    module: str
    alias: str | None
    line: int


@dataclass(frozen=True)
class FromImport:
    """``from a.b import x as y, z`` / ``from . import x`` / ``from a import *``.

    ``names`` holds (imported name, bound name) pairs; a wildcard import is
    the single pair ``("*", "*")``. ``level`` counts leading dots.
    """

    module: str
    level: int
    names: tuple[tuple[str, str], ...]
    line: int


@dataclass(frozen=True)
class Decorator:
    """One decorator site, pre-digested for route/test detection.

    ``dotted`` is the decorator's name chain (``app.get`` for
    ``@app.get("/x")``), or None when the expression is not a plain
    name/attribute (subscripts, lambdas). ``args`` holds the positional
    *string-literal* arguments only; ``kwargs`` maps keyword names to a
    string or tuple of strings, dropping anything not statically literal.
    """

    dotted: str | None
    args: tuple[str, ...]
    kwargs: dict
    line: int


@dataclass(frozen=True)
class Symbol:
    """A function, method, or class definition."""

    qualname: str
    name: str
    kind: str  # "function" | "method" | "class"
    line: int
    end_line: int
    decorators: tuple[Decorator, ...]


@dataclass(frozen=True)
class Call:
    """A call site whose callee is a plain name/attribute chain.

    ``scope`` is the qualname of the innermost enclosing definition, or None
    for module-body calls (attributed to the module node itself, ADR-007).
    """

    scope: str | None
    callee: str
    line: int


@dataclass(frozen=True)
class EnvRead:
    """A statically visible environment-variable read."""

    var: str
    line: int


@dataclass
class ParsedFile:
    """Everything one walk collects from one file."""

    imports: list = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    env_reads: list[EnvRead] = field(default_factory=list)
    #: The module docstring's literal, exactly as written, or None.
    #: Normalizing it is hobbes.extract.docstrings' job — this module
    #: extracts, it does not interpret.
    docstring: str | None = None


def parse_source(source: bytes) -> ParsedFile:
    """Walk one file's source and collect its raw facts."""
    parsed = ParsedFile()
    root = _PARSER.parse(source).root_node
    parsed.docstring = _module_docstring(root)
    _walk(root, [], parsed, ())
    return parsed


def _module_docstring(root: Node) -> str | None:
    """The module docstring literal: the file's first statement, if it is
    a bare string. Anything else means the module has none."""
    for child in root.named_children:
        if child.type != "expression_statement":
            return None
        inner = child.named_children[0] if child.named_children else None
        if inner is None or inner.type != "string":
            return None
        return (inner.text or b"").decode("utf-8", "replace")
    return None


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", "replace")


def _line(node: Node) -> int:
    return node.start_point.row + 1


def _dotted(node: Node) -> str | None:
    """The text of a pure identifier/attribute chain, else None."""
    if node.type == "identifier":
        return _text(node)
    if node.type == "attribute":
        obj = _dotted(node.child_by_field_name("object"))
        if obj is None:
            return None
        return f"{obj}.{_text(node.child_by_field_name('attribute'))}"
    return None


def _string_literal(node: Node) -> str | None:
    """A plain string literal's content; None for f-strings and non-strings."""
    if node is None or node.type != "string":
        return None
    parts = []
    for child in node.children:
        if child.type == "interpolation":
            return None
        if child.type == "string_content":
            parts.append(_text(child))
    return "".join(parts)


def _decorator(node: Node) -> Decorator:
    """Digest one ``decorator`` node."""
    expr = node.children[-1]  # after the "@"
    if expr.type != "call":
        return Decorator(_dotted(expr), (), {}, _line(node))
    dotted = _dotted(expr.child_by_field_name("function"))
    args: list[str] = []
    kwargs: dict = {}
    arguments = expr.child_by_field_name("arguments")
    for arg in arguments.named_children if arguments else []:
        if arg.type == "string":
            literal = _string_literal(arg)
            if literal is not None:
                args.append(literal)
        elif arg.type == "keyword_argument":
            key = _text(arg.child_by_field_name("name"))
            value = arg.child_by_field_name("value")
            literal = _string_literal(value)
            if literal is not None:
                kwargs[key] = literal
            elif value is not None and value.type == "list":
                items = [_string_literal(el) for el in value.named_children]
                if items and all(i is not None for i in items):
                    kwargs[key] = tuple(items)
    return Decorator(dotted, tuple(args), kwargs, _line(node))


def _scope_qualname(stack: list[tuple[str, str]]) -> str | None:
    return ".".join(name for name, _ in stack) or None


def _walk(
    node: Node,
    stack: list[tuple[str, str]],
    parsed: ParsedFile,
    pending_decorators: tuple[Decorator, ...],
) -> None:
    kind = node.type

    if kind == "import_statement":
        line = _line(node)
        for child in node.named_children:
            if child.type == "dotted_name":
                parsed.imports.append(PlainImport(_text(child), None, line))
            elif child.type == "aliased_import":
                parsed.imports.append(
                    PlainImport(
                        _text(child.child_by_field_name("name")),
                        _text(child.child_by_field_name("alias")),
                        line,
                    )
                )
        return

    if kind == "import_from_statement":
        module_node = node.child_by_field_name("module_name")
        level, module = 0, ""
        if module_node.type == "relative_import":
            for child in module_node.children:
                if child.type == "import_prefix":
                    level = len(_text(child))
                elif child.type == "dotted_name":
                    module = _text(child)
        else:
            module = _text(module_node)
        names: list[tuple[str, str]] = []
        if any(c.type == "wildcard_import" for c in node.children):
            names.append(("*", "*"))
        else:
            for child in node.children_by_field_name("name"):
                if child.type == "dotted_name":
                    name = _text(child)
                    names.append((name, name))
                elif child.type == "aliased_import":
                    names.append(
                        (
                            _text(child.child_by_field_name("name")),
                            _text(child.child_by_field_name("alias")),
                        )
                    )
        parsed.imports.append(FromImport(module, level, tuple(names), _line(node)))
        return

    if kind == "decorated_definition":
        decorators = tuple(
            _decorator(c) for c in node.children if c.type == "decorator"
        )
        definition = node.child_by_field_name("definition")
        if definition is not None:
            # Decorator expressions themselves are not walked: @app.get("/x")
            # is a call, but recording it would pollute the call graph.
            _walk(definition, stack, parsed, decorators)
        return

    if kind in ("function_definition", "class_definition"):
        name = _text(node.child_by_field_name("name"))
        qualname = ".".join([*(n for n, _ in stack), name])
        if kind == "class_definition":
            symbol_kind = "class"
        elif stack and stack[-1][1] == "class":
            symbol_kind = "method"
        else:
            symbol_kind = "function"
        parsed.symbols.append(
            Symbol(
                qualname=qualname,
                name=name,
                kind=symbol_kind,
                line=_line(node),
                end_line=node.end_point.row + 1,
                decorators=pending_decorators,
            )
        )
        body = node.child_by_field_name("body")
        if body is not None:
            child_stack = [*stack, (name, "class" if kind == "class_definition" else "function")]
            for child in body.children:
                _walk(child, child_stack, parsed, ())
        return

    if kind == "call":
        function = node.child_by_field_name("function")
        dotted = _dotted(function) if function is not None else None
        if dotted is not None:
            line = _line(node)
            if dotted in _ENV_CALLS:
                arguments = node.child_by_field_name("arguments")
                first = arguments.named_children[0] if arguments and arguments.named_children else None
                var = _string_literal(first)
                if var is not None:
                    parsed.env_reads.append(EnvRead(var, line))
            parsed.calls.append(Call(_scope_qualname(stack), dotted, line))
        for child in node.children:
            _walk(child, stack, parsed, ())
        return

    if kind == "subscript":
        value = node.child_by_field_name("value")
        dotted = _dotted(value) if value is not None else None
        if dotted in _ENV_SUBSCRIPTS:
            var = _string_literal(node.child_by_field_name("subscript"))
            if var is not None:
                parsed.env_reads.append(EnvRead(var, _line(node)))
        for child in node.children:
            _walk(child, stack, parsed, ())
        return

    for child in node.children:
        _walk(child, stack, parsed, ())
