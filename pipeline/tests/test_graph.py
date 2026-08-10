"""Tests for hobbes.extract.graph — typed edges over the miniapp fixture."""

from pathlib import Path

import pytest

from hobbes.extract.discover import discover_modules
from hobbes.extract.graph import build_graph
from hobbes.extract.pysource import parse_source

FIXTURE = Path(__file__).parent / "fixtures" / "miniapp"


@pytest.fixture(scope="module")
def graph():
    modules = discover_modules(FIXTURE)
    parsed = {m.id: parse_source((FIXTURE / m.path).read_bytes()) for m in modules}
    return build_graph(modules, parsed)


def module_edges(graph, edge_type):
    return {(e["from"], e["to"]) for e in graph["module_edges"] if e["type"] == edge_type}


class TestModuleEdges:
    def test_intra_repo_imports(self, graph):
        imports = module_edges(graph, "imports")
        assert ("miniapp.api", "miniapp.core") in imports
        assert ("miniapp.cli", "miniapp.core") in imports
        assert ("miniapp.core", "miniapp.util") in imports
        assert ("tests.test_core", "miniapp.core") in imports
        assert ("tests.test_core", "miniapp.util") in imports

    def test_third_party_becomes_external_nodes(self, graph):
        imports = module_edges(graph, "imports")
        assert ("miniapp.api", "ext:fastapi") in imports
        assert ("miniapp.web", "ext:flask") in imports
        kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
        assert kinds["ext:fastapi"] == "external"

    def test_stdlib_is_dropped(self, graph):
        assert not any(n["id"] == "ext:os" for n in graph["nodes"])

    def test_env_reads(self, graph):
        env = module_edges(graph, "env-read")
        assert ("miniapp.core", "env:MINIAPP_MODE") in env
        assert ("miniapp.util", "env:MINIAPP_HOME") in env
        kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
        assert kinds["env:MINIAPP_MODE"] == "env"

    def test_evidence_carries_file_and_line(self, graph):
        edge = next(
            e
            for e in graph["module_edges"]
            if e["from"] == "miniapp.core" and e["to"] == "miniapp.util"
        )
        assert edge["evidence"] == [{"path": "src/miniapp/core.py", "line": 5}]


class TestSymbolEdges:
    def test_resolution_rules(self, graph):
        calls = {(e["from"], e["to"]) for e in graph["symbol_edges"]}
        # bare local name: top_level() instantiates Engine
        assert ("miniapp.core.top_level", "miniapp.core.Engine") in calls
        # self.method()
        assert ("miniapp.core.Engine.run", "miniapp.core.Engine.check") in calls
        # attribute on an imported repo module: util.normalize
        assert ("miniapp.core.Engine.run", "miniapp.util.normalize") in calls
        # from-imported symbol: top_level in the API handlers
        assert ("miniapp.api.read_item", "miniapp.core.top_level") in calls
        # dotted through `from miniapp import core`: core.top_level()
        assert ("miniapp.cli.main", "miniapp.core.top_level") in calls

    def test_unresolvable_calls_are_omitted(self, graph):
        # engine.run(item) is an instance-attribute call — must NOT edge.
        targets = {
            e["to"] for e in graph["symbol_edges"] if e["from"] == "miniapp.core.top_level"
        }
        assert "miniapp.core.Engine.run" not in targets

    def test_symbol_layer_records(self, graph):
        by_id = {s["id"]: s for s in graph["symbols"]}
        engine = by_id["miniapp.core.Engine"]
        assert engine["kind"] == "class"
        run = by_id["miniapp.core.Engine.run"]
        assert run["kind"] == "method"
        assert run["module"] == "miniapp.core"
        assert run["line"] < run["end_line"]


class TestDeterminism:
    def test_two_builds_identical(self):
        modules = discover_modules(FIXTURE)
        parsed = {
            m.id: parse_source((FIXTURE / m.path).read_bytes()) for m in modules
        }
        assert build_graph(modules, parsed) == build_graph(modules, parsed)


class TestRelativeImports:
    def test_relative_from_resolves_inside_package(self, tmp_path):
        pkg = tmp_path / "pkg"
        (pkg / "sub").mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "helper.py").write_text("def h():\n    pass\n")
        (pkg / "sub" / "__init__.py").write_text("")
        (pkg / "sub" / "deep.py").write_text(
            "from .. import helper\nfrom ..helper import h\n\ndef use():\n    return h()\n"
        )
        modules = discover_modules(tmp_path)
        parsed = {
            m.id: parse_source((tmp_path / m.path).read_bytes()) for m in modules
        }
        graph = build_graph(modules, parsed)
        imports = {
            (e["from"], e["to"])
            for e in graph["module_edges"]
            if e["type"] == "imports"
        }
        assert ("pkg.sub.deep", "pkg.helper") in imports
        calls = {(e["from"], e["to"]) for e in graph["symbol_edges"]}
        assert ("pkg.sub.deep.use", "pkg.helper.h") in calls
