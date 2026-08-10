"""Tests for stamping and end-to-end ingest (hobbes.extract.emit / ingest)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hobbes.extract import ingest
from hobbes.extract.emit import StampError, repo_stamp, write_artifacts

FIXTURE = Path(__file__).parent / "fixtures" / "miniapp"


@pytest.fixture
def git_fixture(tmp_path):
    """The miniapp fixture as a real git repo with one commit."""
    repo = tmp_path / "miniapp"
    shutil.copytree(FIXTURE, repo)
    # Real repos gitignore derived/ (hobbes init writes this); without it the
    # first ingest's own output would dirty the tree for the second.
    (repo / ".gitignore").write_text(".hobbes/derived/\n")
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
            assert doc["schema_version"] == 1
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
        assert doc["language"] == "python"
        node_ids = {n["id"] for n in doc["nodes"]}
        assert {"miniapp.core", "ext:fastapi", "env:MINIAPP_MODE"} <= node_ids
