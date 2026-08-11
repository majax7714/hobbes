"""TS/JS extraction (ADR-021): hobbes.extract.tssource.

The join is tested hermetically against canned facts; the helper's own
behavior has its node --test suite in tsextract/. The integration tests
at the bottom run the real helper over the minits fixture and skip when
Node or the helper's node_modules are absent.
"""

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from hobbes.extract.tssource import (
    HELPER_VERSION,
    TsExtractError,
    extract_ts,
    has_ts_files,
    join_facts,
    module_id,
    run_helper,
)

FIXTURE = Path(__file__).parent / "fixtures" / "minits"
HELPER = Path(__file__).parents[2] / "tsextract" / "extract.mjs"


def facts(files):
    return {"helper_version": HELPER_VERSION, "tsconfigs": [], "files": files}


def file_facts(path, **overrides):
    base = {
        "path": path,
        "imports": [],
        "symbols": [],
        "calls": [],
        "env_reads": [],
        "routes": [],
        "test_framework": None,
        "tests": [],
    }
    base.update(overrides)
    return base


class TestModuleId:
    def test_strips_known_extensions_only(self):
        assert module_id("src/flow.js") == "src/flow"
        assert module_id("src/a.test.mjs") == "src/a.test"
        assert module_id("src/data.json") == "src/data.json"


class TestJoinFacts:
    def test_modules_imports_externals_and_env(self):
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "src/main.js",
                        imports=[
                            {
                                "specifier": "./util.js",
                                "resolved": "src/util.js",
                                "external": None,
                                "names": ["helper"],
                                "line": 1,
                            },
                            {
                                "specifier": "express",
                                "resolved": None,
                                "external": "express",
                                "names": [],
                                "line": 2,
                            },
                        ],
                        env_reads=[{"var": "API_URL", "line": 5}],
                    ),
                    file_facts("src/util.js"),
                ]
            )
        )
        assert [n["id"] for n in joined["nodes"]] == [
            "env:API_URL",
            "ext:express",
            "src/main",
            "src/util",
        ]
        assert joined["languages"] == ["javascript"]
        edges = {(e["from"], e["to"], e["type"]) for e in joined["module_edges"]}
        assert edges == {
            ("src/main", "src/util", "imports"),
            ("src/main", "ext:express", "imports"),
            ("src/main", "env:API_URL", "env-read"),
        }

    def test_duplicate_imports_merge_evidence(self):
        imp = {
            "specifier": "./util.js",
            "resolved": "src/util.js",
            "external": None,
            "names": [],
        }
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "src/main.js",
                        imports=[{**imp, "line": 1}, {**imp, "line": 9}],
                    ),
                    file_facts("src/util.js"),
                ]
            )
        )
        (edge,) = joined["module_edges"]
        assert [e["line"] for e in edge["evidence"]] == [1, 9]

    def test_symbols_and_calls_are_module_qualified(self):
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "src/util.js",
                        symbols=[
                            {
                                "name": "helper",
                                "qualname": "helper",
                                "kind": "function",
                                "line": 1,
                                "end_line": 3,
                            }
                        ],
                    ),
                    file_facts(
                        "src/main.js",
                        symbols=[
                            {
                                "name": "run",
                                "qualname": "run",
                                "kind": "function",
                                "line": 2,
                                "end_line": 4,
                            }
                        ],
                        calls=[
                            {
                                "callee": "helper",
                                "callee_path": "src/util.js",
                                "scope": "run",
                                "line": 3,
                            },
                            {
                                "callee": "run",
                                "callee_path": "src/main.js",
                                "scope": None,
                                "line": 6,
                            },
                        ],
                    ),
                ]
            )
        )
        assert [s["id"] for s in joined["symbols"]] == [
            "src/main.run",
            "src/util.helper",
        ]
        assert {(e["from"], e["to"]) for e in joined["symbol_edges"]} == {
            ("src/main.run", "src/util.helper"),
            ("src/main", "src/main.run"),
        }

    def test_languages_ts_and_js(self):
        joined = join_facts(
            facts([file_facts("src/a.ts"), file_facts("src/b.js")])
        )
        assert joined["languages"] == ["javascript", "typescript"]

    def test_routes_module_qualify_resolved_handlers(self):
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "src/server.js",
                        routes=[
                            {
                                "framework": "express",
                                "method": "GET",
                                "path": "/items",
                                "handler": "listItems",
                                "handler_path": "src/server.js",
                                "line": 4,
                            },
                            {
                                "framework": "express",
                                "method": "POST",
                                "path": "/items",
                                "handler": "<inline>",
                                "handler_path": None,
                                "line": 5,
                            },
                        ],
                    )
                ]
            )
        )
        assert [r["handler"] for r in joined["routes"]] == [
            "src/server.listItems",
            "<inline>",
        ]

    def test_tests_file_level_reach_with_closure(self):
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "src/util.js",
                        symbols=[
                            {"name": "helper", "qualname": "helper", "kind": "function", "line": 1, "end_line": 2},
                            {"name": "inner", "qualname": "inner", "kind": "function", "line": 3, "end_line": 4},
                        ],
                        calls=[
                            {"callee": "inner", "callee_path": "src/util.js", "scope": "helper", "line": 2}
                        ],
                    ),
                    file_facts(
                        "tests/util.test.mjs",
                        imports=[
                            {
                                "specifier": "../src/util.js",
                                "resolved": "src/util.js",
                                "external": None,
                                "names": ["helper"],
                                "line": 2,
                            }
                        ],
                        test_framework="node:test",
                        tests=[
                            {"qualname": "helper works", "line": 4},
                            {"qualname": "suite > helper again", "line": 8},
                        ],
                    ),
                ]
            )
        )
        first, second = joined["tests"]
        assert first["id"] == "tests/util.test.mjs::helper works"
        assert first["framework"] == "node:test"
        # Reach seeds on the import and closes over helper -> inner.
        assert first["reaches"] == ["src/util.helper", "src/util.inner"]
        assert first["reaches_modules"] == ["src/util"]
        assert second["reaches"] == first["reaches"]

    def test_test_file_own_symbols_excluded_from_reach(self):
        joined = join_facts(
            facts(
                [
                    file_facts(
                        "tests/x.test.js",
                        symbols=[
                            {"name": "fake", "qualname": "fake", "kind": "function", "line": 1, "end_line": 2}
                        ],
                        calls=[
                            {"callee": "fake", "callee_path": "tests/x.test.js", "scope": None, "line": 3}
                        ],
                        test_framework="jest",
                        tests=[{"qualname": "uses a local fake", "line": 4}],
                    )
                ]
            )
        )
        (record,) = joined["tests"]
        assert record["reaches"] == []
        assert record["reaches_modules"] == []


    def test_imported_module_guarded_even_without_symbol_match(self, tmp_path):
        # A test importing a module guards it even when nothing it names
        # is in the symbol layer (zustand stores, mocked modules).
        joined = join_facts(
            facts(
                [
                    file_facts("src/store.ts"),  # no modeled symbols
                    file_facts(
                        "tests/store.test.ts",
                        imports=[
                            {
                                "specifier": "@/store",
                                "resolved": "src/store.ts",
                                "external": None,
                                "names": ["useStore"],
                                "line": 1,
                            }
                        ],
                        test_framework="vitest",
                        tests=[{"qualname": "store works", "line": 3}],
                    ),
                ]
            )
        )
        (record,) = joined["tests"]
        assert record["reaches"] == []
        assert record["reaches_modules"] == ["src/store"]


class TestHasTsFiles:
    def test_finds_and_skips(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x.js").write_text("")
        assert not has_ts_files(tmp_path)
        (tmp_path / "app.mjs").write_text("")
        assert has_ts_files(tmp_path)


class TestRunHelper:
    def fake_helper(self, tmp_path, monkeypatch, body):
        script = tmp_path / "fake-tsextract"
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("HOBBES_TSEXTRACT_CMD", str(script))
        return script

    def test_canned_facts_roundtrip(self, tmp_path, monkeypatch):
        canned = facts([file_facts("src/a.js")])
        self.fake_helper(
            tmp_path, monkeypatch, f"cat <<'EOF'\n{json.dumps(canned)}\nEOF"
        )
        assert run_helper(tmp_path) == canned

    def test_missing_binary_says_how_to_fix(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOBBES_TSEXTRACT_CMD", "/nonexistent/helper")
        with pytest.raises(TsExtractError, match="npm install"):
            run_helper(tmp_path)

    def test_nonzero_exit_carries_stderr(self, tmp_path, monkeypatch):
        self.fake_helper(tmp_path, monkeypatch, "echo doom >&2\nexit 3")
        with pytest.raises(TsExtractError, match="exited 3: doom"):
            run_helper(tmp_path)

    def test_wrong_version_rejected(self, tmp_path, monkeypatch):
        self.fake_helper(
            tmp_path, monkeypatch, 'echo \'{"helper_version": 99, "files": []}\''
        )
        with pytest.raises(TsExtractError, match="version 99"):
            run_helper(tmp_path)

    def test_extract_ts_none_without_ts_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOBBES_TSEXTRACT_CMD", "/nonexistent/helper")
        (tmp_path / "only.py").write_text("x = 1\n")
        assert extract_ts(tmp_path) is None


def helper_available() -> bool:
    return (
        shutil.which("node") is not None
        and (HELPER.parent / "node_modules" / "ts-morph").is_dir()
    )


@pytest.fixture(scope="module")
def joined(tmp_path_factory):
    if not helper_available():
        pytest.skip("node/ts-morph not installed")
    # Copy the fixture so the repo root is exactly minits.
    root = tmp_path_factory.mktemp("minits-repo")
    shutil.copytree(FIXTURE, root / "minits")
    return extract_ts(root / "minits")


@pytest.mark.skipif(not helper_available(), reason="node/ts-morph not installed")
class TestIntegrationMinits:
    """The real helper over the minits fixture (ADR-021 end to end)."""

    def test_languages_and_nodes(self, joined):
        assert joined["languages"] == ["javascript", "typescript"]
        ids = [n["id"] for n in joined["nodes"]]
        assert "src/server" in ids and "src/util" in ids
        assert "ext:express" in ids and "ext:@nestjs/common" in ids
        assert "env:MINITS_API_URL" in ids

    def test_import_and_env_edges(self, joined):
        edges = {(e["from"], e["to"], e["type"]) for e in joined["module_edges"]}
        assert ("src/server", "src/util", "imports") in edges
        assert ("src/items.controller", "src/util", "imports") in edges
        assert ("src/util", "env:MINITS_API_URL", "env-read") in edges

    def test_call_edge_into_util(self, joined):
        assert {
            (e["from"], e["to"]) for e in joined["symbol_edges"]
        } >= {("src/server.listItems", "src/util.normalize")}

    def test_routes_express_and_nest(self, joined):
        routes = {(r["framework"], r["method"], r["path"]) for r in joined["routes"]}
        assert routes == {
            ("express", "GET", "/items"),
            ("express", "POST", "/items"),
            ("nest", "GET", "/items/:id"),
        }

    def test_test_inventory_both_frameworks(self, joined):
        by_framework = {}
        for t in joined["tests"]:
            by_framework.setdefault(t["framework"], []).append(t)
        assert len(by_framework["node:test"]) == 2
        assert by_framework["node:test"][0]["reaches_modules"] == ["src/util"]
        assert [t["id"] for t in by_framework["vitest"]] == [
            "src/math.spec.ts::math > adds"
        ]


@pytest.mark.skipif(not helper_available(), reason="node/ts-morph not installed")
class TestIntegrationIngest:
    def test_full_ingest_merges_layers(self, tmp_path):
        repo = tmp_path / "repo"
        shutil.copytree(FIXTURE, repo)
        (repo / "app.py").write_text("import json\nVALUE = 1\n")
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git[:3], "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "one"], check=True)

        from hobbes.extract import ingest

        paths = {p.name: json.loads(p.read_text()) for p in ingest(repo)}
        graph = paths["graph.json"]
        assert graph["schema_version"] == 3
        assert graph["languages"] == ["javascript", "python", "typescript"]
        ids = {n["id"] for n in graph["nodes"]}
        assert {"app", "src/server", "src/util"} <= ids
        tests = paths["tests.json"]["tests"]
        assert {t["framework"] for t in tests} == {"node:test", "vitest"}
        assert "framework" not in paths["tests.json"]
        routes = paths["interfaces.json"]["routes"]
        assert {r["framework"] for r in routes} == {"express", "nest"}

    def test_ts_only_repo_claims_no_python(self, tmp_path):
        repo = tmp_path / "tsrepo"
        shutil.copytree(FIXTURE, repo)
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git[:3], "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "one"], check=True)

        from hobbes.extract import ingest

        graph = {p.name: json.loads(p.read_text()) for p in ingest(repo)}["graph.json"]
        assert graph["languages"] == ["javascript", "typescript"]

