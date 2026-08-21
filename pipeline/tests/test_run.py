"""The execution half — `hobbes run` and the short-term channel (ADR-054).

Everything here is quota-free and podman-free: a stand-in session
binary plays the sandbox, writing the flight log, the mail, and a
harvested branch the way the real `hobbes-session` does, so the
orchestrator's reading of all three is tested against the shapes the
Go side writes.
"""

import json
import os
import stat
import subprocess

import pytest
import yaml

from hobbes import cli
from hobbes.derive import derive_plan, write_spec
from hobbes.run import agents, mail, orchestrate
from hobbes.run.roles import ROLE_POLICIES, ensure_role_policies
from hobbes.run.spec import SpecError, list_plans, load_spec, plan_dir, resolve_task
from tests.test_changespec import plan_repo  # noqa: F401 — fixture


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def planned(plan_repo):  # noqa: F811
    """plan_repo with a two-unit change-spec written."""
    spec = derive_plan(plan_repo, "improve app.core handle", budget=100)
    write_spec(plan_repo, spec)
    return plan_repo, spec.task


#: A stand-in hobbes-session: records its argv, writes a flight log with
#: one knowledge call in scope and one fault, one exec allow, a
#: reflection, and harvests a branch with one commit that touches one
#: interior file and one file outside the manifest.
FAKE_SESSION = """\
#!/bin/sh
set -e
repo=""; session=""; sessions=""; agent=""; dry=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2;;
    --session) session="$2"; shift 2;;
    --sessions) sessions="$2"; shift 2;;
    --agent-dir) agent="$2"; shift 2;;
    --task) shift 2;;
    --dry-run) dry=1; shift;;
    *) shift;;
  esac
done
echo "$@" > /dev/null
mkdir -p "$sessions/$session"
printf '%s\\n' "$agent" > "$sessions/$session/argv.txt"
[ -n "$dry" ] && { echo "dry run"; exit 0; }
cat > "$sessions/$session/flight.jsonl" <<EOT
{"tool":"graph_neighborhood","argv":["app.core"],"decision":"allow"}
{"tool":"graph_neighborhood","argv":["billing"],"decision":"allow","context_fault":true}
{"tool":"exec","argv":["/bin/sh","-c","git status"],"decision":"allow"}
{"tool":"exec","argv":["/bin/sh","-c","git push"],"decision":"deny"}
{"tool":"reflect","argv":["done: handle retried"],"decision":"allow"}
EOT
cat > "$sessions/$session/mail.jsonl" <<EOT
{"seq":1,"session":"$session","role":"implementer","text":"done: handle retried"}
EOT
wt="$sessions/$session/worktree"
git clone -q --local --no-hardlinks "$repo" "$wt"
git -C "$wt" checkout -q -b "hobbes/$session"
echo "# changed" >> "$wt/src/app/core.py"
echo "stray" > "$wt/src/stray.py"
git -C "$wt" -c user.name=a -c user.email=a@a add -A
git -C "$wt" -c user.name=a -c user.email=a@a commit -qm "feat: retry handle"
git -C "$repo" fetch -q "$wt" "hobbes/$session:hobbes/$session"
rm -rf "$wt"
echo "harvested"
"""


@pytest.fixture
def fake_session(tmp_path):
    path = tmp_path / "hobbes-session"
    path.write_text(FAKE_SESSION)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class TestSpec:
    def test_list_resolve_and_load(self, planned):
        repo, task = planned
        assert list_plans(repo) == [task]
        assert resolve_task(repo, task[:4]) == task
        assert load_spec(repo, task[:4])["task"] == task

    def test_unknown_and_ambiguous_are_errors(self, planned):
        repo, task = planned
        with pytest.raises(SpecError, match="no plan"):
            resolve_task(repo, "zzz")
        write_spec(repo, derive_plan(repo, "improve app.core"))
        with pytest.raises(SpecError, match="ambiguous"):
            resolve_task(repo, "")


class TestRoles:
    def test_scaffolds_missing_and_never_overwrites(self, plan_repo):  # noqa: F811
        assert sorted(ensure_role_policies(plan_repo)) == sorted(ROLE_POLICIES)
        path = plan_repo / ".hobbes/policies/roles/implementer.policy"
        path.write_text("version: 1\nscope: role\nrules: []\n")
        assert ensure_role_policies(plan_repo) == []
        assert path.read_text() == "version: 1\nscope: role\nrules: []\n"

    def test_every_role_policy_declares_role_scope(self):
        for role, text in ROLE_POLICIES.items():
            doc = yaml.safe_load(text)
            assert doc["scope"] == "role", role
            assert doc["version"] == 1


class TestMail:
    def test_post_read_and_fold_back(self, tmp_path):
        inbox = tmp_path / "U1"
        first = mail.post(inbox, "orchestrator", "what does handle return?")
        second = mail.post(inbox, "human", "use the existing retry helper", kind="reply")
        assert (first["seq"], second["seq"]) == (1, 2)
        assert [m["from"] for m in mail.read(inbox)] == ["orchestrator", "human"]
        session = tmp_path / "sess"
        session.mkdir()
        (session / "mail.jsonl").write_text('{"seq":1,"text":"blocked on K1"}\n')
        orchestrator = tmp_path / "orchestrator"
        assert mail.fold_back(orchestrator, "U1", mail.reflections(session)) == 1
        folded = mail.read(orchestrator)[0]
        assert folded["from"] == "U1" and folded["kind"] == "reflection"
        assert mail.reflections(tmp_path / "nowhere") == []


class TestAgents:
    def test_materialize_writes_policy_context_and_inbox(self, planned):
        repo, task = planned
        spec = load_spec(repo, task)
        tests = json.loads((repo / ".hobbes/derived/tests.json").read_text())
        dirs = agents.materialize(plan_dir(repo, task), spec, tests)
        assert set(dirs) == {u["name"] for u in spec["units"]}
        for unit, directory in dirs.items():
            policy = yaml.safe_load((directory / "policy.yaml").read_text())
            assert policy["scope"] == "agent" and policy["default"] == "escalate"
            # The guarantees come first, as denies (P10).
            assert [r["decision"] for r in policy["rules"][:3]] == ["deny"] * 3
            assert policy["rules"][1]["pattern"] == "git push*"
            context = json.loads((directory / "context.json").read_text())
            assert context["unit"] == unit
            assert context["interior"] and context["paths"]
            text = (directory / "context.md").read_text()
            assert "What Hobbes cannot see here" in text
            assert "C-38" in text
            assert (directory / mail.INBOX).is_file()
        assert (agents.agent_dir(plan_dir(repo, task), "orchestrator") / mail.INBOX).is_file()

    def test_guarding_tests_become_allow_rules(self, planned):
        repo, task = planned
        spec = load_spec(repo, task)
        tests = json.loads((repo / ".hobbes/derived/tests.json").read_text())
        guarded = next(c for c in spec["contexts"] if c["guarding_tests"])
        policy = agents.build_policy(spec, guarded["unit"],
                                     {t["id"]: t["file"] for t in tests["tests"]})
        allows = [r for r in policy["rules"] if r["decision"] == "allow"]
        assert allows and allows[0]["pattern"].startswith("uv run pytest tests/")

    def test_human_first_denies_every_write(self, planned):
        repo, task = planned
        spec = load_spec(repo, task)
        spec["contexts"][0]["human_first"] = True
        spec["contexts"][0]["human_first_reason"] = "blind"
        policy = agents.build_policy(spec, spec["contexts"][0]["unit"], {})
        denied = {r["pattern"] for r in policy["rules"] if r["decision"] == "deny"}
        assert {"git commit*", "git add *"} <= denied

    def test_boundary_is_the_far_side_of_each_contract(self, planned):
        repo, task = planned
        spec = load_spec(repo, task)
        for unit in spec["units"]:
            context = agents.build_context_json(spec, unit["name"])
            assert not set(context["boundary"]) & set(context["interior"])
        if spec["contracts"]:
            c = spec["contracts"][0]
            consumer = c["from_unit"] if c["owner"] == c["to_unit"] else c["to_unit"]
            far = agents.build_context_json(spec, consumer)["boundary"]
            assert far, "a consumer's boundary names the owner's declaration"

    def test_brief_carries_both_horizons_and_obligations(self, planned):
        repo, task = planned
        spec = load_spec(repo, task)
        unit = spec["units"][0]["name"]
        brief = agents.render_brief(spec, unit, "implementer",
                                    [{"seq": 1, "from": "orchestrator", "kind": "request",
                                      "text": "report the return type of handle"}], "s1")
        assert "single-use implementer" in brief
        assert "report the return type of handle" in brief
        assert "reflect" in brief and "hobbes/s1" in brief
        assert "Standing context" in brief and "What Hobbes cannot see" in brief
        empty = agents.render_brief(spec, unit, "implementer", [], "s1")
        assert "inbox" in empty and "empty" in empty


class TestOrder:
    def test_owner_before_consumer(self):
        spec = {"units": [{"name": "U1"}, {"name": "U2"}, {"name": "U3"}],
                "contracts": [{"from_unit": "U1", "to_unit": "U3", "owner": "U3"},
                              {"from_unit": "U2", "to_unit": "U1", "owner": "U1"}]}
        assert orchestrate.order_units(spec) == ["U3", "U1", "U2"]

    def test_a_cycle_falls_back_to_name_order(self):
        spec = {"units": [{"name": "U2"}, {"name": "U1"}],
                "contracts": [{"from_unit": "U1", "to_unit": "U2", "owner": "U2"},
                              {"from_unit": "U2", "to_unit": "U1", "owner": "U1"}]}
        assert orchestrate.order_units(spec) == ["U1", "U2"]


class TestRun:
    def test_dry_run_writes_agents_briefs_and_record_without_spawning(self, planned, tmp_path):
        repo, task = planned
        record = orchestrate.run_task(repo, task, dry_run=True, session_bin=None,
                                      sessions_root=tmp_path / "sessions")
        assert all(not u["spawned"] for u in record["units"])
        assert record["integration"] == {"skipped": "dry run"}
        pdir = plan_dir(repo, task)
        assert (pdir / orchestrate.RECORD).is_file()
        for unit in record["order"]:
            d = agents.agent_dir(pdir, unit)
            assert (d / "brief.md").is_file() and (d / "spawn.txt").is_file()
            assert "--agent-dir" in (d / "spawn.txt").read_text()
        assert (repo / ".hobbes/policies/roles/implementer.policy").is_file()
        assert "re-ingest" in record["standing_context"]

    def test_full_loop_reads_flight_mail_and_branch(self, planned, fake_session, tmp_path):
        repo, task = planned
        sessions = tmp_path / "sessions"
        record = orchestrate.run_task(repo, task, session_bin=fake_session, sessions_root=sessions)
        units = {u["unit"]: u for u in record["units"]}
        for unit, u in units.items():
            assert u["spawned"] and u["exit"] == 0
            assert u["knowledge_calls"] == 2 and u["context_faults"] == 1
            assert u["exec"] == {"allow": 1, "deny": 1, "escalate": 0}
            assert u["reflections"] == ["done: handle retried"]
            assert u["commits"] == 1
            assert "src/stray.py" in u["rework_files"]
            # the agent dir reached the session binary
            assert (sessions / u["session"] / "argv.txt").read_text().strip().endswith(unit)
        # reflections folded into the orchestrator's inbox
        inbox = mail.read(agents.agent_dir(plan_dir(repo, task), "orchestrator"))
        assert [m["kind"] for m in inbox].count("reflection") == len(units)
        # integration: the first branch merges; the second touches the same
        # lines and conflicts — recorded at the cut, never guessed
        integ = record["integration"]
        assert integ["branch"] == f"hobbes/{task}"
        assert len(integ["merged"]) + len(integ["failed"]) == len(units)
        assert git(repo, "rev-parse", "--verify", integ["branch"])
        assert "contract_failures" in record["loss"]["terms"]
        assert record["loss"]["unobserved"] == ["tokens", "wall_time"]
        assert record["loss"]["value"] > 0  # rework alone makes it positive
        # the human's checkout was never touched
        assert [l for l in git(repo, "status", "--porcelain").splitlines()
                if not l.endswith(".hobbes/")] == []

    def test_human_first_unit_is_not_spawned(self, planned, fake_session, tmp_path):
        repo, task = planned
        path = plan_dir(repo, task) / "change-spec.yaml"
        spec = yaml.safe_load(path.read_text())
        spec["contexts"][0]["human_first"] = True
        spec["contexts"][0]["human_first_reason"] = "blind scope"
        path.write_text(yaml.safe_dump(spec, sort_keys=False))
        flagged = spec["contexts"][0]["unit"]
        record = orchestrate.run_task(repo, task, session_bin=fake_session,
                                      sessions_root=tmp_path / "sessions", only_units=[flagged])
        (u,) = record["units"]
        assert not u["spawned"] and u["reason"].startswith("human-first")
        notices = [m for m in mail.read(agents.agent_dir(plan_dir(repo, task), "orchestrator"))
                   if m["kind"] == "human-first"]
        assert notices and notices[0]["from"] == flagged

    def test_stale_plan_warns_in_the_orchestrator_inbox(self, planned, tmp_path):
        repo, task = planned
        (repo / "src/app/auth.py").write_text("def token():\n    return 2\n")
        git(repo, "commit", "-qam", "two")
        orchestrate.run_task(repo, task, dry_run=True, session_bin=None,
                             sessions_root=tmp_path / "sessions")
        inbox = mail.read(agents.agent_dir(plan_dir(repo, task), "orchestrator"))
        assert any(m["kind"] == "warning" and "stale" in m["text"] for m in inbox)

    def test_no_session_binary_is_an_error_unless_dry(self, planned, tmp_path, monkeypatch):
        repo, task = planned
        monkeypatch.delenv("HOBBES_SESSION_BIN", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(orchestrate.RunError, match="hobbes-session not found"):
            orchestrate.run_task(repo, task, sessions_root=tmp_path / "s")


class TestCLI:
    def test_run_dry_and_mail_round_trip(self, planned, tmp_path, capsys):
        repo, task = planned
        assert cli.main(["mail", "post", task[:4], "U1", "check the retry helper first",
                         "--repo", str(repo)]) == 0
        assert cli.main(["mail", "read", task, "U1", "--repo", str(repo)]) == 0
        assert "check the retry helper first" in capsys.readouterr().out
        code = cli.main(["run", task, "--dry-run", "--sessions", str(tmp_path / "s"),
                         "--repo", str(repo)])
        out = capsys.readouterr().out
        assert code == 0
        assert f"run {task}" in out and "loss (declared weights, C-35)" in out
        brief = (agents.agent_dir(plan_dir(repo, task), "U1") / "brief.md").read_text()
        assert "check the retry helper first" in brief

    def test_unknown_task_is_2(self, plan_repo, capsys):  # noqa: F811
        assert cli.main(["run", "nope", "--dry-run", "--repo", str(plan_repo)]) == 2
        assert "no plan" in capsys.readouterr().err

    def test_full_loop_exit_reflects_integration(self, planned, fake_session, tmp_path, capsys):
        repo, task = planned
        code = cli.main(["run", task, "--session-bin", fake_session,
                         "--sessions", str(tmp_path / "s"), "--repo", str(repo), "--json"])
        record = json.loads(capsys.readouterr().out)
        expected = 1 if (record["integration"]["failed"] or record["review"].get("needs_attention")) else 0
        assert code == expected
