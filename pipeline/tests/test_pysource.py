"""Tests for hobbes.extract.pysource — the per-file tree-sitter walk."""

from hobbes.extract.pysource import (
    FromImport,
    PlainImport,
    parse_source,
)


def parse(text: str):
    return parse_source(text.encode())


class TestImports:
    def test_plain_aliased_and_multiple(self):
        p = parse("import os, sys\nimport a.b as ab\n")
        assert p.imports == [
            PlainImport("os", None, 1),
            PlainImport("sys", None, 1),
            PlainImport("a.b", "ab", 2),
        ]

    def test_from_imports(self):
        p = parse("from x.y import f, g as h\n")
        assert p.imports == [
            FromImport("x.y", 0, (("f", "f"), ("g", "h")), 1)
        ]

    def test_relative_and_wildcard(self):
        p = parse("from . import sibling\nfrom ..pkg import thing\nfrom z import *\n")
        assert p.imports == [
            FromImport("", 1, (("sibling", "sibling"),), 1),
            FromImport("pkg", 2, (("thing", "thing"),), 2),
            FromImport("z", 0, (("*", "*"),), 3),
        ]

    def test_function_level_imports_count(self):
        p = parse("def f():\n    import late\n")
        assert p.imports == [PlainImport("late", None, 2)]


class TestSymbols:
    def test_kinds_and_qualnames(self):
        p = parse(
            "def func():\n"
            "    def inner():\n"
            "        pass\n"
            "class C:\n"
            "    def method(self):\n"
            "        pass\n"
            "    class Nested:\n"
            "        def deep(self):\n"
            "            pass\n"
        )
        got = {(s.qualname, s.kind) for s in p.symbols}
        assert got == {
            ("func", "function"),
            ("func.inner", "function"),
            ("C", "class"),
            ("C.method", "method"),
            ("C.Nested", "class"),
            ("C.Nested.deep", "method"),
        }

    def test_lines_span_the_definition(self):
        p = parse("def f():\n    a = 1\n    return a\n")
        (symbol,) = p.symbols
        assert (symbol.line, symbol.end_line) == (1, 3)

    def test_decorators_with_string_args_and_kwargs(self):
        p = parse(
            '@app.route("/admin", methods=["GET", "POST"])\n'
            "@property\n"
            "def handler():\n"
            "    pass\n"
        )
        (symbol,) = p.symbols
        route, prop = symbol.decorators
        assert route.dotted == "app.route"
        assert route.args == ("/admin",)
        assert route.kwargs == {"methods": ("GET", "POST")}
        assert prop.dotted == "property"

    def test_fstring_decorator_arg_is_skipped(self):
        p = parse('@app.get(f"/items/{prefix}")\ndef h():\n    pass\n')
        (symbol,) = p.symbols
        assert symbol.decorators[0].args == ()


class TestCalls:
    def test_scopes(self):
        p = parse(
            "top()\n"
            "def f():\n"
            "    mid()\n"
            "class C:\n"
            "    def m(self):\n"
            "        self.n()\n"
        )
        assert {(c.scope, c.callee) for c in p.calls} == {
            (None, "top"),
            ("f", "mid"),
            ("C.m", "self.n"),
        }

    def test_nested_and_chained_calls(self):
        p = parse("def f():\n    return outer(inner(3))\n")
        assert {c.callee for c in p.calls} == {"outer", "inner"}

    def test_dynamic_callees_are_skipped(self):
        p = parse("def f(handlers):\n    handlers[0]()\n    getattr(x, 'y')()\n")
        # subscript-call and call-of-call yield no dotted callee; the inner
        # getattr call itself is a plain name and is recorded.
        assert {c.callee for c in p.calls} == {"getattr"}

    def test_decorator_expressions_do_not_pollute_calls(self):
        p = parse('@app.get("/x")\ndef h():\n    pass\n')
        assert p.calls == []


class TestEnvReads:
    def test_all_four_patterns(self):
        p = parse(
            'import os\n'
            'a = os.getenv("A")\n'
            'b = os.environ["B"]\n'
            'c = os.environ.get("C")\n'
            'from os import environ, getenv\n'
            'd = getenv("D")\n'
            'e = environ["E"]\n'
        )
        assert [(r.var, r.line) for r in p.env_reads] == [
            ("A", 2),
            ("B", 3),
            ("C", 4),
            ("D", 6),
            ("E", 7),
        ]

    def test_dynamic_var_names_are_skipped(self):
        p = parse('import os\nx = os.getenv(name)\ny = os.environ[f"PRE_{n}"]\n')
        assert p.env_reads == []


class TestResilience:
    def test_syntax_errors_yield_partial_facts(self):
        p = parse("def ok():\n    pass\n\ndef broken(:\n")
        assert any(s.qualname == "ok" for s in p.symbols)

    def test_empty_file(self):
        p = parse("")
        assert (p.imports, p.symbols, p.calls, p.env_reads) == ([], [], [], [])
