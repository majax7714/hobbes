"""Tests for the hobbes CLI: init/ingest/render/diff behavior, passthrough."""

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hobbes import cli
from tests.conftest import FAKE_RESOLUTION

FIXTURE = Path(__file__).parent / "fixtures" / "miniapp"


class TestInit:
    def test_scaffolds_layout(self, tmp_path, capsys):
        assert cli.main(["init", "--repo", str(tmp_path)]) == 0
        assert (tmp_path / ".hobbes" / "policies" / "repo.policy").is_file()
        assert (tmp_path / ".hobbes" / "invariants").is_dir()
        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".hobbes/" in gitignore.splitlines()  # ADR-012: the whole dir
        assert "*.tfstate" in gitignore

    def test_idempotent_and_preserves_existing(self, tmp_path, capsys):
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        assert cli.main(["init", "--repo", str(tmp_path)]) == 0
        marker = "# custom policy"
        policy_path = tmp_path / ".hobbes" / "policies" / "repo.policy"
        policy_path.write_text(marker)
        capsys.readouterr()

        assert cli.main(["init", "--repo", str(tmp_path)]) == 0
        assert "nothing to do" in capsys.readouterr().out
        assert policy_path.read_text() == marker
        gitignore = (tmp_path / ".gitignore").read_text()
        assert gitignore.startswith("node_modules/\n")
        assert gitignore.count(".hobbes/") == 1


@pytest.fixture
def git_fixture(tmp_path):
    """The miniapp fixture as a real git repo with one commit."""
    repo = tmp_path / "miniapp"
    shutil.copytree(FIXTURE, repo)
    (repo / ".gitignore").write_text(".hobbes/\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "fixture"], check=True)
    return repo


class TestIngest:
    def test_ingests_and_summarizes(self, git_fixture, capsys):
        assert cli.main(["ingest", "--repo", str(git_fixture)]) == 0
        out = capsys.readouterr().out
        assert "graph.json" in out and "module edges" in out
        assert (git_fixture / ".hobbes" / "derived" / "graph.json").is_file()

    def test_non_git_repo_is_a_clear_error(self, tmp_path, capsys):
        assert cli.main(["ingest", "--repo", str(tmp_path)]) == 1
        assert "git repo" in capsys.readouterr().err

    def test_tf_plan_enriches_graph(self, git_fixture, capsys):
        plan = Path(__file__).parent / "fixtures" / "plans" / "miniapp-plan.json"
        code = cli.main(
            ["ingest", "--repo", str(git_fixture), "--tf-plan", str(plan)]
        )
        assert code == 0
        doc = json.loads(
            (git_fixture / ".hobbes" / "derived" / "graph.json").read_text()
        )
        assert any(
            n["id"] == "tf:aws_cloudwatch_log_group.worker" for n in doc["nodes"]
        )

    def test_tfstate_plan_refused(self, git_fixture, tmp_path, capsys):
        lookalike = tmp_path / "prod.tfstate"
        lookalike.write_text("{}")
        code = cli.main(
            ["ingest", "--repo", str(git_fixture), "--tf-plan", str(lookalike)]
        )
        assert code == 1
        assert "state" in capsys.readouterr().err


class TestRender:
    def test_renders_after_ingest(self, git_fixture, capsys):
        assert cli.main(["ingest", "--repo", str(git_fixture)]) == 0
        capsys.readouterr()
        assert cli.main(["render", "--repo", str(git_fixture)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("flowchart LR")
        assert '"miniapp.core"' in out

    def test_missing_artifact_says_run_ingest(self, git_fixture, capsys):
        assert cli.main(["render", "--repo", str(git_fixture)]) == 1
        assert "hobbes ingest" in capsys.readouterr().err


class TestDiff:
    @pytest.fixture
    def two_commit_fixture(self, git_fixture):
        git = ["git", "-C", str(git_fixture), "-c", "user.name=t", "-c", "user.email=t@t"]
        (git_fixture / "src" / "miniapp" / "extra.py").write_text(
            "from miniapp import util\n"
        )
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "add extra"], check=True)
        return git_fixture

    def test_delta_prints_and_exits_one(self, two_commit_fixture, capsys):
        code = cli.main(["diff", "HEAD~1..HEAD", "--repo", str(two_commit_fixture)])
        assert code == 1
        out = capsys.readouterr().out
        assert "+ module miniapp.extra" in out
        assert "+ imports miniapp.extra -> miniapp.util" in out

    def test_bare_base_means_head(self, two_commit_fixture, capsys):
        assert cli.main(["diff", "HEAD~1", "--repo", str(two_commit_fixture)]) == 1
        assert "miniapp.extra" in capsys.readouterr().out

    def test_no_delta_exits_zero(self, two_commit_fixture, capsys):
        code = cli.main(["diff", "HEAD..HEAD", "--repo", str(two_commit_fixture)])
        assert code == 0
        assert "no architectural changes" in capsys.readouterr().out

    def test_json_output(self, two_commit_fixture, capsys):
        code = cli.main(
            ["diff", "HEAD~1..HEAD", "--json", "--repo", str(two_commit_fixture)]
        )
        assert code == 1
        delta = json.loads(capsys.readouterr().out)
        assert [n["id"] for n in delta["nodes_added"]] == ["miniapp.extra"]

    def test_bad_ref_exits_two(self, git_fixture, capsys):
        assert cli.main(["diff", "nope..HEAD", "--repo", str(git_fixture)]) == 2
        assert "nope" in capsys.readouterr().err

    def test_three_dot_range_rejected(self, git_fixture):
        with pytest.raises(SystemExit, match="three-dot"):
            cli.main(["diff", "a...b", "--repo", str(git_fixture)])


class TestPolicyResolve:
    def test_propagates_decision_exit_and_prints_json(
        self, fake_policy_bin, monkeypatch, capsys
    ):
        payload = dict(FAKE_RESOLUTION, decision="deny")
        monkeypatch.setenv("HOBBES_POLICY_BIN", fake_policy_bin(10, payload))
        code = cli.main(["policy", "resolve", "git push --force origin main"])
        assert code == 10
        printed = json.loads(capsys.readouterr().out)
        assert printed["decision"] == "deny"
        assert printed["rule"]["pattern"] == "git push --force*"

    def test_allow_exits_zero(self, fake_policy_bin, monkeypatch):
        payload = dict(FAKE_RESOLUTION, decision="allow")
        monkeypatch.setenv("HOBBES_POLICY_BIN", fake_policy_bin(0, payload))
        assert cli.main(["policy", "resolve", "git status"]) == 0

    def test_missing_binary_is_a_clear_error(self, no_real_binary, capsys):
        assert cli.main(["policy", "resolve", "git status"]) == 1
        assert "go build" in capsys.readouterr().err

    def test_binary_runtime_error_reported(
        self, fake_policy_bin, monkeypatch, capsys
    ):
        monkeypatch.setenv("HOBBES_POLICY_BIN", fake_policy_bin(1))
        assert cli.main(["policy", "resolve", "git status"]) == 1
        assert "exited 1" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


class TestInvariantsCommand:
    """`hobbes invariants list | check | compile` (ADR-024)."""

    def _repo(self, tmp_path, record):
        import yaml

        directory = tmp_path / ".hobbes" / "invariants"
        directory.mkdir(parents=True)
        (directory / "I-1-x.yaml").write_text(yaml.safe_dump(record, sort_keys=False))
        return tmp_path

    def _record(self, **overrides):
        record = {
            "id": "I-1",
            "statement": "Only the parser parses.",
            "scope": "src",
            "status": "confirmed",
            "compile": {
                "target": "import-linter",
                "rule": {
                    "kind": "forbidden-import",
                    "importers": ["*"],
                    "imported": ["ext:tree_sitter"],
                },
            },
            "guarded_by": [],
        }
        record.update(overrides)
        return record

    def test_check_passes_on_valid_records(self, tmp_path, capsys):
        repo = self._repo(tmp_path, self._record())
        assert cli.main(["invariants", "check", "--repo", str(repo)]) == 0
        assert "1 record(s) valid" in capsys.readouterr().out

    def test_check_exits_one_and_names_every_problem(self, tmp_path, capsys):
        repo = self._repo(tmp_path, {"id": "I-1", "compile": {"target": "nope"}})
        assert cli.main(["invariants", "check", "--repo", str(repo)]) == 1
        err = capsys.readouterr().err
        assert "problem(s)" in err
        assert "compile.target" in err

    def test_list_hides_unconfirmed_unless_asked(self, tmp_path, capsys):
        repo = self._repo(tmp_path, self._record(status="retired"))
        cli.main(["invariants", "list", "--repo", str(repo)])
        assert "no confirmed invariants" in capsys.readouterr().out
        cli.main(["invariants", "list", "--repo", str(repo), "--all"])
        assert "I-1" in capsys.readouterr().out

    def test_compile_without_ingest_says_so(self, tmp_path, capsys):
        repo = self._repo(tmp_path, self._record())
        assert cli.main(["invariants", "compile", "--repo", str(repo)]) == 1
        assert "hobbes ingest" in capsys.readouterr().err

    def test_compile_writes_configs_and_a_manifest(self, tmp_path, capsys):
        repo = self._repo(tmp_path, self._record())
        derived = repo / ".hobbes" / "derived"
        derived.mkdir(parents=True, exist_ok=True)
        (derived / "graph.json").write_text(
            json.dumps(
                {
                    "sha": "abc",
                    "dirty": False,
                    "nodes": [{"id": "app.core", "kind": "module", "path": "src/core.py"}],
                    "module_edges": [],
                }
            )
        )
        assert cli.main(["invariants", "compile", "--repo", str(repo)]) == 0
        assert "importlinter.ini" in capsys.readouterr().out
        manifest = json.loads((derived / "compiled" / "manifest.json").read_text())
        assert manifest["outputs"][0]["invariants"] == ["I-1"]


class TestProgressIsNotBuffered:
    """`up` and `narrate` print while they work, so a redirected run has to
    show those lines as they happen rather than at exit."""

    def test_main_line_buffers_a_redirected_stdout(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        log = tmp_path / "out.log"
        with open(log, "w") as handle:
            # A real file object, as a redirect gives — block-buffered by
            # default, which is the papercut.
            assert handle.line_buffering is False
            monkeypatch.setattr("sys.stdout", handle)
            assert cli.main(["init", "--repo", str(repo)]) == 0
            assert handle.line_buffering is True
            # Already on disk, with the command still running.
            assert log.read_text() != ""

    def test_a_captured_stdout_without_reconfigure_still_works(
        self, tmp_path, monkeypatch
    ):
        # pytest's capsys and a plain StringIO have no reconfigure; buffering
        # is not their problem, and main must not assume the attribute.
        buffer = io.StringIO()
        assert not hasattr(buffer, "reconfigure")
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.setattr("sys.stdout", buffer)
        assert cli.main(["init", "--repo", str(repo)]) == 0
        assert buffer.getvalue() != ""
