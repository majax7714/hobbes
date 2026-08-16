"""Enrichment packs, and V2.M4's exit criterion (ADR-035).

The criterion is a property, so it is a test rather than a paragraph:
**removing a pack removes exactly its own contribution and nothing else,
and putting it back reproduces the artifact byte-for-byte.** Everything
here that is not that property exists to make that property meaningful —
a pack that contributed nothing would satisfy it trivially, so each pack
is also checked to produce what it is for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hobbes.extract import extract_repo
from hobbes.extract.packs import (
    REGISTRY,
    Pack,
    PackContext,
    PackRefusal,
    PackResult,
    run_packs,
)
from hobbes.extract.packs import cli_python, http_python, http_ts, terraform
from hobbes.extract.schema import TIERS

MINIAPP = Path(__file__).parent / "fixtures" / "miniapp"
MINITS = Path(__file__).parent / "fixtures" / "minits"
HELPER = Path(__file__).parents[2] / "tsextract" / "extract.mjs"


def helper_available() -> bool:
    """Same guard test_tssource.py uses: the TS helper needs its deps."""
    return (
        shutil.which("node") is not None
        and (HELPER.parent / "node_modules" / "ts-morph").is_dir()
    )


def _context(repo_root: Path, ts=None) -> PackContext:
    """A PackContext built the way extract_repo builds one."""
    from hobbes.extract.discover import discover_modules
    from hobbes.extract.pysource import parse_source

    modules = discover_modules(repo_root)
    parsed = {
        m.id: parse_source((repo_root / m.path).read_bytes()) for m in modules
    }
    return PackContext(repo_root=repo_root, modules=modules, parsed=parsed, ts=ts)


def _artifacts(repo_root: Path, packs) -> dict:
    extraction = extract_repo(repo_root, packs=packs)
    return {
        "graph": extraction.graph,
        "tests": extraction.tests,
        "interfaces": extraction.interfaces,
    }


class TestRegistry:
    """The registry's own invariants — cheap, and each has a failure mode."""

    def test_every_pack_declares_a_known_tier(self):
        # §3.5: packs declare the tier their edges carry. An unknown tier
        # would reach graph.json and a consumer would trust an edge it
        # cannot classify.
        for pack in REGISTRY:
            assert pack.tier in TIERS, pack.name

    def test_pack_names_are_unique(self):
        # `packs` in graph.json is a provenance list; duplicate names would
        # make a contribution unattributable, which is the whole point.
        names = [pack.name for pack in REGISTRY]
        assert len(names) == len(set(names))

    def test_registry_holds_the_four_ported_packs(self):
        assert [pack.name for pack in REGISTRY] == [
            "http-python",
            "cli-python",
            "http-ts",
            "terraform",
        ]


class TestExitCriterion:
    """V2.M4's exit: a pack is exactly and only its own contribution."""

    @pytest.mark.parametrize(
        "pack",
        [http_python.PACK, cli_python.PACK, terraform.PACK],
        ids=lambda p: p.name,
    )
    def test_removing_a_pack_removes_exactly_its_contribution(self, pack: Pack):
        without = tuple(p for p in REGISTRY if p is not pack)
        full_docs = _artifacts(MINIAPP, REGISTRY)
        less_docs = _artifacts(MINIAPP, without)

        # What the pack itself claims to contribute, asked directly.
        contribution = pack.run(_context(MINIAPP))

        # 1. The pack ran in one and not the other.
        assert pack.name in full_docs["graph"]["packs"]
        assert pack.name not in less_docs["graph"]["packs"]

        # 2. Nothing appears that the pack's absence should not have caused.
        #    Removal must never *add* an element.
        full_nodes = {n["id"] for n in full_docs["graph"]["nodes"]}
        less_nodes = {n["id"] for n in less_docs["graph"]["nodes"]}
        assert not (less_nodes - full_nodes)

        # 3. Every node that disappeared was one the pack produced. Nodes
        #    it shares with another producer (env:VAR that Python also
        #    reads) correctly survive, which is why this is a subset check
        #    and not an equality.
        produced_nodes = {n["id"] for n in contribution.nodes}
        assert (full_nodes - less_nodes) <= produced_nodes

        # 4. Same for edges, keyed the way the graph keys them.
        def edge_keys(docs):
            return {
                (e["from"], e["to"], e["type"])
                for e in docs["graph"]["module_edges"]
            }

        produced_edges = {
            (e["from"], e["to"], e["type"]) for e in contribution.module_edges
        }
        assert not (edge_keys(less_docs) - edge_keys(full_docs))
        assert (edge_keys(full_docs) - edge_keys(less_docs)) <= produced_edges

        # 5. Interface rows are wholly owned — no other producer shares them.
        for field, produced in (
            ("routes", contribution.routes),
            ("cli_entry_points", contribution.cli_entry_points),
        ):
            full_rows = full_docs["interfaces"][field]
            less_rows = less_docs["interfaces"][field]
            assert [r for r in full_rows if r not in less_rows] == list(produced)

        # 6. Everything that survived is *unchanged*. A pack that mutated a
        #    shared edge's evidence in passing would satisfy every check
        #    above and still be wrong.
        surviving = {
            (e["from"], e["to"], e["type"]): e
            for e in full_docs["graph"]["module_edges"]
        }
        for edge in less_docs["graph"]["module_edges"]:
            key = (edge["from"], edge["to"], edge["type"])
            assert surviving[key] == edge

    @pytest.mark.parametrize(
        "pack",
        [http_python.PACK, cli_python.PACK, terraform.PACK],
        ids=lambda p: p.name,
    )
    def test_adding_a_pack_back_restores_the_artifact_byte_for_byte(self, pack):
        # The second half of the criterion, and the one that catches a
        # non-deterministic pack: removal and restoration must be a
        # round trip, not an approximation.
        before = json.dumps(_artifacts(MINIAPP, REGISTRY), sort_keys=True)
        _ = _artifacts(MINIAPP, tuple(p for p in REGISTRY if p is not pack))
        after = json.dumps(_artifacts(MINIAPP, REGISTRY), sort_keys=True)
        assert before == after

    def test_no_packs_at_all_still_yields_a_graph(self):
        # P6 at the pack tier: packs enrich, they do not constitute. A repo
        # extracted with an empty registry keeps its modules, imports and
        # symbol edges, and simply knows nothing about frameworks.
        docs = _artifacts(MINIAPP, ())
        assert docs["graph"]["packs"] == []
        assert docs["graph"]["nodes"]
        assert docs["graph"]["module_edges"]
        assert docs["interfaces"]["routes"] == []
        assert docs["interfaces"]["cli_entry_points"] == []
        # ...and claims no HCL, because the pack that proves it never ran.
        assert "hcl" not in docs["graph"]["languages"]


class TestPackContributions:
    """Each pack produces the thing it exists for."""

    def test_http_python_finds_decorator_routes(self):
        result = http_python.PACK.run(_context(MINIAPP))
        assert result.routes
        assert {r["framework"] for r in result.routes} <= {"fastapi", "flask", "unknown"}

    def test_http_python_applies_only_when_a_framework_is_imported(self, tmp_path):
        (tmp_path / "plain.py").write_text("import os\n\ndef f():\n    return os\n")
        assert not http_python.PACK.applies(_context(tmp_path))
        (tmp_path / "api.py").write_text("from fastapi import FastAPI\n")
        assert http_python.PACK.applies(_context(tmp_path))

    def test_cli_python_reads_every_pyproject_not_just_the_root(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "root"\n[project.scripts]\nroot-cmd = "root:main"\n'
        )
        nested = tmp_path / "packages" / "inner"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text(
            '[project]\nname = "inner"\n[project.scripts]\ninner-cmd = "inner:main"\n'
        )
        names = {e["name"] for e in cli_python.PACK.run(_context(tmp_path)).cli_entry_points}
        assert names == {"root-cmd", "inner-cmd"}

    def test_terraform_contributes_hcl_and_tf_nodes(self):
        result = terraform.PACK.run(_context(MINIAPP))
        assert result.languages == ["hcl"]
        assert any(n["id"].startswith("tf:") for n in result.nodes)

    def test_terraform_does_not_apply_without_tf_files(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        assert not terraform.PACK.applies(_context(tmp_path))

    def test_http_ts_claims_the_helper_rows_rather_than_re_deriving(self):
        # The one pack whose detection lives in the Node helper (ADR-035):
        # it adopts the rows verbatim, so what the helper found is exactly
        # what reaches interfaces.json.
        rows = [{"framework": "express", "method": "GET", "path": "/x",
                 "handler": "h", "file": "src/server.js", "line": 3}]
        ctx = PackContext(repo_root=MINITS, modules=[], parsed={}, ts={"routes": rows})
        assert http_ts.PACK.applies(ctx)
        assert http_ts.PACK.run(ctx).routes == rows

    def test_http_ts_does_not_apply_without_a_ts_layer(self):
        assert not http_ts.PACK.applies(_context(MINIAPP))
        assert not http_ts.PACK.applies(
            PackContext(repo_root=MINITS, modules=[], parsed={}, ts={"routes": []})
        )


class TestDegradation:
    """A pack failing is a degraded ingest, never a failed one (P6)."""

    def test_a_raising_pack_is_reported_and_the_rest_still_run(self):
        def boom(ctx):
            raise RuntimeError("no framework here")

        broken = Pack(
            name="broken", tier="syntactic", applies=lambda ctx: True, run=boom
        )
        out = run_packs(_context(MINIAPP), (broken, terraform.PACK))

        assert out.ran == ["terraform"]  # the survivor still ran
        assert len(out.errors) == 1
        error = out.errors[0]
        assert error["stage"] == "pack:broken"
        assert "no framework here" in error["message"]

    def test_a_raising_applies_is_caught_too(self):
        def boom(ctx):
            raise OSError("cannot stat")

        broken = Pack(
            name="broken-detect", tier="syntactic", applies=boom, run=lambda c: PackResult()
        )
        out = run_packs(_context(MINIAPP), (broken,))
        assert out.ran == []
        assert out.errors[0]["stage"] == "pack:broken-detect"

    def test_a_pack_failure_reaches_extraction_errors(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        broken = Pack(
            name="broken",
            tier="syntactic",
            applies=lambda ctx: True,
            run=lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        graph = extract_repo(tmp_path, packs=(broken,)).graph
        stages = {e["stage"] for e in graph["extraction_errors"]}
        assert "pack:broken" in stages

    def test_a_refusal_is_re_raised_rather_than_degraded(self):
        # The regression this test exists for: wrapping packs in a blanket
        # `except Exception` turned the .tfstate refusal (I-1, ADR-011)
        # into a warning, and `ingest --tf-plan prod.tfstate` started
        # succeeding. A refusal is not a breakage.
        refusing = Pack(
            name="refuser",
            tier="syntactic",
            applies=lambda ctx: True,
            run=lambda ctx: (_ for _ in ()).throw(PackRefusal("declined")),
        )
        with pytest.raises(PackRefusal, match="declined"):
            run_packs(_context(MINIAPP), (refusing,))

    def test_a_tfstate_plan_is_still_refused_through_the_pack(self, tmp_path):
        state = tmp_path / "prod.tfstate"
        state.write_text("{}")
        ctx = PackContext(
            repo_root=MINIAPP, modules=[], parsed={}, tf_plan=state
        )
        with pytest.raises(PackRefusal, match="refusing anything that looks like"):
            run_packs(ctx, (terraform.PACK,))

    def test_extraction_errors_are_sorted_not_pipeline_ordered(self, tmp_path):
        # ADR-035: which pass reported first is an accident of pipeline
        # order, and an artifact that changes with it is not reproducible.
        (tmp_path / "app.py").write_text("x = 1\n")
        packs = tuple(
            Pack(
                name=name,
                tier="syntactic",
                applies=lambda ctx: True,
                run=lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")),
            )
            for name in ("zeta", "alpha", "mid")
        )
        errors = extract_repo(tmp_path, packs=packs).graph["extraction_errors"]
        keys = [(e["stage"], e["path"], e["message"]) for e in errors]
        assert keys == sorted(keys)


class TestProvenance:
    """`packs` in graph.json is what makes a contribution attributable."""

    def test_graph_records_which_packs_ran(self):
        graph = extract_repo(MINIAPP).graph
        assert graph["packs"] == ["http-python", "cli-python", "terraform"]

    def test_packs_that_do_not_apply_are_absent_from_the_list(self):
        # miniapp has no TypeScript, so http-ts must not claim to have run.
        assert "http-ts" not in extract_repo(MINIAPP).graph["packs"]


@pytest.mark.skipif(not helper_available(), reason="node/ts-morph not installed")
class TestTypeScriptPackEndToEnd:
    """http-ts over the real helper — the rows really do come from a pack."""

    def test_removing_http_ts_removes_exactly_the_ts_routes(self):
        full = _artifacts(MINITS, REGISTRY)
        without = _artifacts(MINITS, tuple(p for p in REGISTRY if p is not http_ts.PACK))

        assert "http-ts" in full["graph"]["packs"]
        assert full["interfaces"]["routes"]
        assert without["interfaces"]["routes"] == []
        # Nothing else moved: the graph itself is the TS lane's, not the pack's.
        assert full["graph"]["nodes"] == without["graph"]["nodes"]
        assert full["graph"]["module_edges"] == without["graph"]["module_edges"]
