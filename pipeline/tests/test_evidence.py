"""The evidence IR and the range join (ADR-029).

The join is where "is it a call" (tree-sitter) meets "where does it go"
(SCIP). These cases pin the four rows of the ADR's table, and the two
cases that motivated the whole design: a resolution nothing called is a
reference, and a call nothing resolved is not an edge.
"""

from hobbes.extract import evidence as ev
from hobbes.extract.schema import SEMANTIC, SYNTACTIC


def call(file, line, name, scope="", col=4):
    return ev.Site(ev.TREE_SITTER, ev.CALL_SITE, file, line, name, col, scope)


def imported(file, line, name):
    return ev.Site(ev.TREE_SITTER, ev.IMPORT_SITE, file, line, name, 0)


def resolution(file, line, name, def_file, def_line, col=4):
    return ev.Site(
        ev.SCIP, ev.RESOLUTION, file, line, name, col,
        def_file=def_file, def_line=def_line,
    )


class TestTheTable:
    def test_a_call_scip_resolved_is_a_semantic_call(self):
        out = ev.join(
            [call("a.py", 10, "run", scope="a.main")],
            [resolution("a.py", 10, "run", "b.py", 5)],
        )
        assert len(out) == 1
        got = out[0]
        assert got.kind == "calls"
        assert got.tier == SEMANTIC
        assert (got.def_file, got.def_line) == ("b.py", 5)
        assert got.lanes == (ev.TREE_SITTER, ev.SCIP)
        assert got.scope == "a.main"

    def test_a_call_scip_missed_falls_back_to_lane_a_as_syntactic(self):
        out = ev.join(
            [call("a.py", 10, "run")],
            [],
            fallback={("a.py", 10, "run"): ("b.py", 5)},
        )
        assert out[0].kind == "calls"
        assert out[0].tier == SYNTACTIC
        assert out[0].lanes == (ev.TREE_SITTER,)

    def test_a_call_nobody_resolved_is_not_an_edge(self):
        # ADR-007 unchanged: false edges are worse than missing ones.
        assert ev.join([call("a.py", 10, "mystery")], []) == []

    def test_a_resolution_no_call_claimed_is_a_reference(self):
        # The case that forced this design: `except StampError:` and type
        # annotations resolve, and are not calls.
        out = ev.join([], [resolution("a.py", 3, "StampError", "e.py", 9)])
        assert len(out) == 1
        assert out[0].kind == "references"
        assert out[0].tier == SEMANTIC
        assert out[0].lanes == (ev.SCIP,)

    def test_an_import_statement_scip_resolved_is_a_semantic_import(self):
        out = ev.join(
            [imported("a.py", 1, "core")],
            [resolution("a.py", 1, "core", "core.py", 1)],
        )
        assert out[0].kind == "imports"
        assert out[0].tier == SEMANTIC


class TestDisambiguation:
    def test_a_resolution_with_a_different_name_does_not_match(self):
        # Same line, different symbol: matching on line alone would attach
        # the call to whatever else happened to sit there.
        out = ev.join(
            [call("a.py", 10, "run")],
            [resolution("a.py", 10, "other", "b.py", 5)],
        )
        assert [r.kind for r in out] == ["references"]

    def test_columns_break_ties_between_same_named_resolutions(self):
        # `run(run(x))` — two `run` occurrences on one line.
        out = ev.join(
            [call("a.py", 10, "run", col=20)],
            [
                resolution("a.py", 10, "run", "near.py", 1, col=18),
                resolution("a.py", 10, "run", "far.py", 1, col=4),
            ],
        )
        matched = [r for r in out if r.kind == "calls"]
        assert matched[0].def_file == "near.py"

    def test_a_claimed_resolution_is_not_also_a_reference(self):
        out = ev.join(
            [call("a.py", 10, "run")],
            [resolution("a.py", 10, "run", "b.py", 5)],
        )
        assert [r.kind for r in out] == ["calls"]

    def test_an_unclaimed_resolution_on_a_call_line_still_becomes_a_reference(self):
        # `run(CONFIG)` — the call resolves, CONFIG resolves, both are real.
        out = ev.join(
            [call("a.py", 10, "run", col=0)],
            [
                resolution("a.py", 10, "run", "b.py", 5, col=0),
                resolution("a.py", 10, "CONFIG", "c.py", 2, col=8),
            ],
        )
        kinds = sorted(r.kind for r in out)
        assert kinds == ["calls", "references"]


class TestProviderSeparation:
    def test_definitions_are_not_edges(self):
        out = ev.join([ev.Site(ev.TREE_SITTER, ev.DEFINITION, "a.py", 1, "f")], [])
        assert out == []

    def test_every_result_names_the_providers_behind_it(self):
        out = ev.join(
            [call("a.py", 10, "run")],
            [
                resolution("a.py", 10, "run", "b.py", 5),
                resolution("a.py", 12, "Thing", "c.py", 1),
            ],
        )
        assert all(r.lanes for r in out)
        by_kind = {r.kind: r.lanes for r in out}
        assert by_kind["calls"] == (ev.TREE_SITTER, ev.SCIP)
        assert by_kind["references"] == (ev.SCIP,)
