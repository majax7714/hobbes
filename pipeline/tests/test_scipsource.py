"""Lane B's range join (§3.4): SCIP facts onto lane A's structure.

`join_facts` and `merge_lane` are pure, so these run without an indexer.
The end-to-end path is exercised by the M2 exit check, not here.
"""

import pytest

from hobbes.extract import scipsource
from hobbes.extract.schema import LANE_SCIP, LANE_TREE_SITTER, SEMANTIC, SYNTACTIC

NODES = [
    {"id": "app.core", "kind": "module", "path": "src/app/core.py"},
    {"id": "app.api", "kind": "module", "path": "src/app/api.py"},
    {"id": "ext:requests", "kind": "external"},
]
SYMBOLS = [
    {"id": "app.core.Engine", "module": "app.core", "kind": "class",
     "line": 10, "end_line": 30},
    {"id": "app.core.Engine.run", "module": "app.core", "kind": "function",
     "line": 15, "end_line": 20},
    {"id": "app.api.handler", "module": "app.api", "kind": "function",
     "line": 5, "end_line": 9},
]


def facts(references, **extra):
    return {"references": references, "degraded": [], "packages": {}, **extra}


class TestRangeJoin:
    def test_a_reference_becomes_a_semantic_module_edge(self):
        out = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 7,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        assert len(out["module_edges"]) == 1
        edge = out["module_edges"][0]
        assert (edge["from"], edge["to"], edge["type"]) == ("app.api", "app.core", "imports")
        assert edge["tier"] == SEMANTIC
        assert edge["evidence"] == [
            {"path": "src/app/api.py", "line": 7, "lane": LANE_SCIP}
        ]

    def test_the_caller_is_the_innermost_enclosing_symbol(self):
        # Line 17 sits inside Engine.run (15-20), which sits inside
        # Engine (10-30). The method is the caller, not the class.
        out = scipsource.join_facts(
            facts([{"file": "src/app/core.py", "line": 17,
                    "def_file": "src/app/api.py", "def_line": 5}]),
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["from"] == "app.core.Engine.run"

    def test_module_level_code_is_attributed_to_the_module(self):
        # Line 2 encloses no symbol — lane A's own convention for an
        # unscoped call is the module id.
        out = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 2,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["from"] == "app.api"

    def test_lane_b_says_references_not_calls(self):
        # scip-python populates syntax_kind for 0 of 8575 occurrences, so a
        # call cannot be told from a type annotation or an except clause.
        # Claiming `calls` would be the false edge ADR-007 forbids.
        out = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 7,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["type"] == "references"

    def test_a_reference_to_an_unknown_file_is_dropped(self):
        out = scipsource.join_facts(
            facts([{"file": "vendor/thing.py", "line": 1,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        assert out["module_edges"] == [] and out["symbol_edges"] == []

    def test_self_edges_are_not_emitted(self):
        out = scipsource.join_facts(
            facts([{"file": "src/app/core.py", "line": 16,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        assert out["module_edges"] == []
        assert out["symbol_edges"] == []

    def test_repeated_sightings_merge_into_one_edge(self):
        out = scipsource.join_facts(
            facts([
                {"file": "src/app/api.py", "line": 7,
                 "def_file": "src/app/core.py", "def_line": 15},
                {"file": "src/app/api.py", "line": 8,
                 "def_file": "src/app/core.py", "def_line": 15},
                {"file": "src/app/api.py", "line": 8,
                 "def_file": "src/app/core.py", "def_line": 15},
            ]),
            NODES, SYMBOLS,
        )
        assert len(out["module_edges"]) == 1
        assert len(out["module_edges"][0]["evidence"]) == 2  # deduped

    def test_degradation_is_carried_through(self):
        out = scipsource.join_facts(
            facts([], degraded=[{"stage": "scip-resolve", "message": "nope"}]),
            NODES, SYMBOLS,
        )
        assert out["degraded"][0]["stage"] == "scip-resolve"


class TestMergeUpgradesWhatBothLanesFound:
    def _graph(self):
        from hobbes.extract.schema import tiered_edge

        return {
            "module_edges": [
                tiered_edge("app.api", "app.core", "imports",
                            [{"path": "src/app/api.py", "line": 1}]),
                tiered_edge("app.core", "ext:requests", "imports",
                            [{"path": "src/app/core.py", "line": 2}]),
            ],
            "symbol_edges": [],
        }

    def test_an_edge_both_lanes_found_becomes_semantic(self):
        graph = self._graph()
        lane_b = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 7,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        upgraded = scipsource.merge_lane(graph, lane_b)
        assert ("app.api", "app.core", "imports") in upgraded
        edge = next(e for e in graph["module_edges"] if e["to"] == "app.core")
        assert edge["tier"] == SEMANTIC
        # Lane A's sighting is corroboration, not garbage.
        lanes = {ev["lane"] for ev in edge["evidence"]}
        assert lanes == {LANE_SCIP, LANE_TREE_SITTER}

    def test_an_edge_only_lane_a_found_stays_syntactic(self):
        graph = self._graph()
        scipsource.merge_lane(graph, {"module_edges": [], "symbol_edges": []})
        ext = next(e for e in graph["module_edges"] if e["to"] == "ext:requests")
        assert ext["tier"] == SYNTACTIC

    def test_an_edge_only_lane_b_found_is_added(self):
        graph = {"module_edges": [], "symbol_edges": []}
        lane_b = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 7,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        scipsource.merge_lane(graph, lane_b)
        assert len(graph["module_edges"]) == 1
        assert graph["module_edges"][0]["tier"] == SEMANTIC

    def test_the_merge_keeps_edges_sorted(self):
        graph = self._graph()
        lane_b = scipsource.join_facts(
            facts([{"file": "src/app/api.py", "line": 7,
                    "def_file": "src/app/core.py", "def_line": 15}]),
            NODES, SYMBOLS,
        )
        scipsource.merge_lane(graph, lane_b)
        keys = [(e["from"], e["to"], e["type"]) for e in graph["module_edges"]]
        assert keys == sorted(keys)


class TestLaneBCanBeTurnedOff:
    def test_disabled_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv(scipsource.SCIP_ENABLE_ENV, "0")
        assert scipsource.extract_scip(tmp_path, ["a.py"], ["."], "x", "sha") is None

    def test_no_files_returns_none(self, tmp_path):
        assert scipsource.extract_scip(tmp_path, [], ["."], "x", "sha") is None
