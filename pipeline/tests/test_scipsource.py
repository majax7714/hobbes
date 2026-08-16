"""Lane B's SCIP facts, and their projection onto lane A's ids (ADR-029).

The join itself lives in `test_evidence.py` — this covers getting SCIP's
references *into* the evidence IR, and projecting the joined result back
onto module and symbol ids. Both are pure, so no indexer runs here; the
end-to-end path is the M2 exit check.
"""

import pytest

from hobbes.extract import evidence as ev
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


class TestResolutionSites:
    def test_references_become_evidence_ir_sites(self):
        sites = scipsource.resolution_sites(
            {"references": [{"file": "a.py", "line": 3, "col": 8, "name": "run",
                             "def_file": "b.py", "def_line": 5}]}
        )
        assert len(sites) == 1
        site = sites[0]
        assert (site.provider, site.kind) == (ev.SCIP, ev.RESOLUTION)
        assert (site.file, site.line, site.col, site.name) == ("a.py", 3, 8, "run")
        assert (site.def_file, site.def_line) == ("b.py", 5)

    def test_facts_without_references_yield_nothing(self):
        assert scipsource.resolution_sites({}) == []


def resolved(kind, file, line, def_file, def_line, tier=SEMANTIC, scope="",
             lanes=(ev.TREE_SITTER, ev.SCIP)):
    return ev.Resolved(kind, file, line, scope, def_file, def_line, tier, lanes)


class TestProjection:
    def test_a_call_projects_onto_symbol_ids(self):
        out = scipsource.project(
            [resolved("calls", "src/app/api.py", 7, "src/app/core.py", 15)],
            NODES, SYMBOLS,
        )
        edge = out["symbol_edges"][0]
        assert (edge["from"], edge["to"]) == ("app.api.handler", "app.core.Engine.run")
        assert edge["type"] == "calls"
        assert edge["tier"] == SEMANTIC
        assert edge["evidence"][0]["lane"] == LANE_SCIP

    def test_a_cross_module_fact_also_makes_a_module_edge(self):
        out = scipsource.project(
            [resolved("calls", "src/app/api.py", 7, "src/app/core.py", 15)],
            NODES, SYMBOLS,
        )
        edge = out["module_edges"][0]
        assert (edge["from"], edge["to"], edge["type"]) == ("app.api", "app.core", "imports")

    def test_a_same_module_fact_makes_no_module_edge(self):
        out = scipsource.project(
            [resolved("calls", "src/app/core.py", 16, "src/app/core.py", 15)],
            NODES, SYMBOLS,
        )
        assert out["module_edges"] == []

    def test_an_explicit_scope_wins_over_the_enclosing_lookup(self):
        # tree-sitter already knows the enclosing definition; when it says
        # so, that is better evidence than a range lookup.
        out = scipsource.project(
            [resolved("calls", "src/app/core.py", 17, "src/app/api.py", 5,
                      scope="app.core.Engine")],
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["from"] == "app.core.Engine"

    def test_module_level_code_is_attributed_to_the_module(self):
        out = scipsource.project(
            [resolved("calls", "src/app/api.py", 2, "src/app/core.py", 15)],
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["from"] == "app.api"

    def test_a_file_lane_a_never_discovered_is_dropped(self):
        out = scipsource.project(
            [resolved("calls", "vendor/x.py", 1, "src/app/core.py", 15)],
            NODES, SYMBOLS,
        )
        assert out["module_edges"] == [] and out["symbol_edges"] == []

    def test_a_syntactic_fact_keeps_its_tier_and_lane(self):
        out = scipsource.project(
            [resolved("calls", "src/app/api.py", 7, "src/app/core.py", 15,
                      tier=SYNTACTIC, lanes=(ev.TREE_SITTER,))],
            NODES, SYMBOLS,
        )
        edge = out["symbol_edges"][0]
        assert edge["tier"] == SYNTACTIC
        assert edge["evidence"][0]["lane"] == LANE_TREE_SITTER

    def test_references_stay_a_distinct_edge_type(self):
        out = scipsource.project(
            [resolved("uses", "src/app/api.py", 7, "src/app/core.py", 15,
                      lanes=(ev.SCIP,))],
            NODES, SYMBOLS,
        )
        assert out["symbol_edges"][0]["type"] == "uses"

    def test_facts_of_different_tiers_do_not_collapse(self):
        # One proven, one guessed, same endpoints: two claims, not one.
        out = scipsource.project(
            [
                resolved("calls", "src/app/api.py", 7, "src/app/core.py", 15),
                resolved("calls", "src/app/api.py", 8, "src/app/core.py", 15,
                         tier=SYNTACTIC, lanes=(ev.TREE_SITTER,)),
            ],
            NODES, SYMBOLS,
        )
        tiers = sorted(e["tier"] for e in out["symbol_edges"])
        assert tiers == [SEMANTIC, SYNTACTIC]

    def test_repeated_sightings_merge_into_one_edge(self):
        out = scipsource.project(
            [
                resolved("calls", "src/app/api.py", 7, "src/app/core.py", 15),
                resolved("calls", "src/app/api.py", 8, "src/app/core.py", 15),
                resolved("calls", "src/app/api.py", 8, "src/app/core.py", 15),
            ],
            NODES, SYMBOLS,
        )
        assert len(out["symbol_edges"]) == 1
        assert len(out["symbol_edges"][0]["evidence"]) == 2  # deduped


class TestLaneBCanBeTurnedOff:
    def test_disabled_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv(scipsource.SCIP_ENABLE_ENV, "0")
        assert scipsource.extract_scip(tmp_path, ["a.py"], ["."], "x", "sha") is None

    def test_no_files_returns_none(self, tmp_path):
        assert scipsource.extract_scip(tmp_path, [], ["."], "x", "sha") is None


class TestDeclaredDependencies:
    """Decision 4's degradation check needs something to compare against.

    Without these, an index that resolved nothing looks exactly like one
    with nothing to resolve — the conflation that let SELENEX report 72.7%
    coverage with no warning at all.
    """

    def _write(self, tmp_path, body):
        (tmp_path / "pyproject.toml").write_text(body)
        return tmp_path

    def test_reads_project_dependencies(self, tmp_path):
        repo = self._write(tmp_path, '[project]\ndependencies = ["pyyaml>=6", "httpx"]\n')
        assert scipsource.declared_dependencies(repo) == ["httpx", "pyyaml"]

    def test_includes_optional_groups(self, tmp_path):
        repo = self._write(
            tmp_path,
            '[project]\ndependencies = ["a"]\n'
            '[project.optional-dependencies]\ndev = ["pytest>=8"]\n',
        )
        assert scipsource.declared_dependencies(repo) == ["a", "pytest"]

    def test_strips_extras_and_version_specifiers(self, tmp_path):
        repo = self._write(
            tmp_path, '[project]\ndependencies = ["uvicorn[standard]==0.30.0"]\n'
        )
        assert scipsource.declared_dependencies(repo) == ["uvicorn"]

    def test_no_pyproject_is_not_an_error(self, tmp_path):
        assert scipsource.declared_dependencies(tmp_path) == []

    def test_malformed_pyproject_is_not_an_error(self, tmp_path):
        repo = self._write(tmp_path, "this is not toml {{{")
        assert scipsource.declared_dependencies(repo) == []

    def test_subdirectory_manifests_are_walked(self, tmp_path):
        # C-16 (lifted): a src-layout repo whose manifest lives below the
        # root — this repo's own shape, deps in pipeline/pyproject.toml —
        # must not run the degradation check against an empty list.
        sub = tmp_path / "pipeline"
        sub.mkdir()
        (sub / "pyproject.toml").write_text(
            '[project]\ndependencies = ["tree-sitter<0.26"]\n'
        )
        assert scipsource.declared_dependencies(tmp_path) == ["tree-sitter"]

    def test_manifests_union_across_packages(self, tmp_path):
        self._write(tmp_path, '[project]\ndependencies = ["httpx"]\n')
        sub = tmp_path / "worker"
        sub.mkdir()
        (sub / "pyproject.toml").write_text('[project]\ndependencies = ["httpx", "redis"]\n')
        assert scipsource.declared_dependencies(tmp_path) == ["httpx", "redis"]

    def test_find_venv_at_the_repo_root(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
        assert scipsource.find_venv(tmp_path) == (str(tmp_path.resolve()), ".venv")

    def test_find_venv_beside_a_subdirectory_manifest(self, tmp_path):
        # C-27's discovery: this repo's own shape, venv at pipeline/.venv.
        sub = tmp_path / "pipeline"
        sub.mkdir()
        (sub / "pyproject.toml").write_text('[project]\nname = "x"\n')
        (sub / ".venv").mkdir()
        (sub / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
        assert scipsource.find_venv(tmp_path) == (str(sub.resolve()), ".venv")

    def test_find_venv_requires_the_pyvenv_marker(self, tmp_path):
        # A directory merely named .venv is not an environment, and handing
        # it to the indexer would trade one silent zero for another.
        (tmp_path / ".venv").mkdir()
        assert scipsource.find_venv(tmp_path) is None

    def test_find_venv_prefers_the_root_and_dot_venv(self, tmp_path):
        for name in (".venv", "venv"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "pyvenv.cfg").write_text("home = /usr\n")
        assert scipsource.find_venv(tmp_path) == (str(tmp_path.resolve()), ".venv")

    def test_venv_environment_lists_the_venvs_own_distributions(self, tmp_path):
        # C-27: the listing must come from the venv's interpreter, because
        # scip-python's fallback (first pip3 on PATH) describes whatever
        # environment the shell happens to have. A fake venv whose python
        # is this suite's interpreter answers with this suite's packages.
        import sys

        venv = tmp_path / ".venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /usr\n")
        (venv / "bin" / "python").symlink_to(sys.executable)

        listing = scipsource.venv_environment(str(tmp_path), ".venv")
        assert listing is not None
        by_name = {d["name"] for d in listing}
        assert "pytest" in by_name
        sample = next(d for d in listing if d["name"] == "pytest")
        assert sample["version"] and isinstance(sample["files"], list)

    def test_venv_environment_degrades_to_none_without_an_interpreter(self, tmp_path):
        # No python in the venv: attribution is skipped, never guessed —
        # the index still runs and dependency_coverage reports the gap.
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
        assert scipsource.venv_environment(str(tmp_path), ".venv") is None

    def test_walk_prunes_hidden_and_vendored_directories(self, tmp_path):
        # node_modules can be 222 MB on a real app; a dependency's own
        # manifest is not this repo's declaration either way.
        hidden = tmp_path / ".venv"
        vendored = tmp_path / "node_modules" / "pkg"
        for d in (hidden, vendored):
            d.mkdir(parents=True)
            (d / "pyproject.toml").write_text('[project]\ndependencies = ["wrong"]\n')
        assert scipsource.declared_dependencies(tmp_path) == []
