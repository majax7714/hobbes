"""Tests for stamping and end-to-end ingest (hobbes.extract.emit / ingest)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hobbes.extract import ingest
from hobbes.extract.emit import (
    StampError,
    ensure_hobbes_ignored,
    repo_stamp,
    write_artifacts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "miniapp"


@pytest.fixture
def git_fixture(tmp_path):
    """The miniapp fixture as a real git repo with one commit."""
    repo = tmp_path / "miniapp"
    shutil.copytree(FIXTURE, repo)
    # The ADR-012 line, pre-committed: without it the first ingest's own
    # gitignore edit would dirty the tree for the second run.
    (repo / ".gitignore").write_text(".hobbes/\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "fixture"], check=True)
    return repo


class TestStamp:
    def test_clean_tree(self, git_fixture):
        stamp = repo_stamp(git_fixture)
        assert len(stamp["sha"]) == 40
        assert stamp["dirty"] is False

    def test_dirty_tree_flagged(self, git_fixture):
        (git_fixture / "scratch.py").write_text("")
        assert repo_stamp(git_fixture)["dirty"] is True

    def test_non_git_dir_raises(self, tmp_path):
        with pytest.raises(StampError, match="git repo"):
            repo_stamp(tmp_path)


class TestWriteArtifacts:
    def test_deterministic_bytes(self, tmp_path):
        doc = {"b": 2, "a": [3, 1]}
        (first,) = write_artifacts(tmp_path, {"graph.json": doc})
        first_bytes = first.read_bytes()
        (second,) = write_artifacts(tmp_path, {"graph.json": doc})
        assert second.read_bytes() == first_bytes
        assert first_bytes.endswith(b"\n")

    def test_writes_into_derived(self, tmp_path):
        (path,) = write_artifacts(tmp_path, {"tests.json": {}})
        assert path == tmp_path / ".hobbes" / "derived" / "tests.json"


class TestEnsureHobbesIgnored:
    def test_target_repo_gets_whole_dir_ignored(self, git_fixture):
        (git_fixture / ".gitignore").unlink()
        action = ensure_hobbes_ignored(git_fixture)
        assert action == "added .hobbes/ to .gitignore"
        assert ensure_hobbes_ignored(git_fixture) is None  # idempotent

    def test_tracked_hobbes_content_is_respected(self, git_fixture):
        # A repo dogfooding §10 (committed policy) keeps its versioning;
        # only derived/ is ensured.
        (git_fixture / ".gitignore").unlink()
        policy = git_fixture / ".hobbes" / "policies" / "repo.policy"
        policy.parent.mkdir(parents=True)
        policy.write_text("version: 1\nrules: []\n")
        git = ["git", "-C", str(git_fixture), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", ".hobbes"], check=True)
        subprocess.run([*git, "commit", "-qm", "policy"], check=True)

        action = ensure_hobbes_ignored(git_fixture)
        assert action == "added .hobbes/derived/ to .gitignore"

    def test_appends_without_clobbering(self, git_fixture):
        (git_fixture / ".gitignore").write_text("node_modules/")  # no newline
        ensure_hobbes_ignored(git_fixture)
        assert (git_fixture / ".gitignore").read_text() == "node_modules/\n.hobbes/\n"

    def test_non_git_dir_gets_target_posture(self, tmp_path):
        assert ensure_hobbes_ignored(tmp_path) == "added .hobbes/ to .gitignore"

    def test_first_ingest_of_unprotected_repo_adds_line_and_reports_dirty(
        self, git_fixture
    ):
        (git_fixture / ".gitignore").unlink()
        subprocess.run(
            ["git", "-C", str(git_fixture), "-c", "user.name=t", "-c",
             "user.email=t@t", "commit", "-aqm", "drop gitignore"],
            check=True,
        )
        paths = ingest(git_fixture)
        doc = json.loads(paths[0].read_text())
        assert doc["dirty"] is True  # the gitignore edit is honestly visible
        assert ".hobbes/" in (git_fixture / ".gitignore").read_text().splitlines()


class TestIngest:
    def test_writes_all_three_stamped_artifacts(self, git_fixture):
        paths = ingest(git_fixture)
        assert sorted(p.name for p in paths) == [
            "graph.json",
            "interfaces.json",
            "tests.json",
        ]
        sha = repo_stamp(git_fixture)["sha"]
        for path in paths:
            doc = json.loads(path.read_text())
            assert doc["schema_version"] == 3
            assert doc["sha"] == sha
            assert doc["dirty"] is False

    def test_reruns_are_byte_identical(self, git_fixture):
        first = {p.name: p.read_bytes() for p in ingest(git_fixture)}
        second = {p.name: p.read_bytes() for p in ingest(git_fixture)}
        assert first == second

    def test_graph_document_content(self, git_fixture):
        ingest(git_fixture)
        doc = json.loads(
            (git_fixture / ".hobbes" / "derived" / "graph.json").read_text()
        )
        assert doc["languages"] == ["hcl", "python"]
        node_ids = {n["id"] for n in doc["nodes"]}
        assert {
            "miniapp.core",
            "ext:fastapi",
            "env:MINIAPP_MODE",
            "tf:aws_lambda_function.worker",
        } <= node_ids

    def test_cross_layer_env_join_present(self, git_fixture):
        """The §4.1 join: infra env-set and app env-read meet at env:VAR."""
        ingest(git_fixture)
        doc = json.loads(
            (git_fixture / ".hobbes" / "derived" / "graph.json").read_text()
        )
        edges = {(e["from"], e["to"], e["type"]) for e in doc["module_edges"]}
        env = "env:MINIAPP_MODE"
        assert ("tf:aws_lambda_function.worker", env, "env-set") in edges
        assert ("miniapp.core", env, "env-read") in edges
        # And the packages path join: the archive bundles miniapp.cli.
        assert ("tf:data.archive_file.worker", "miniapp.cli", "packages") in edges
