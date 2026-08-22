"""The owned agent runtime — hobbes/agent/loop.py (ADR-056).

Hermetic: a scripted OpenAI-compatible server on a loopback port plays
the model (it returns tool calls in a fixed order, then a final
answer), and a stdio JSON-RPC script plays the hobbes-proxy for the
MCP path. What is tested is the loop's contract — tool routing, file
confinement, bash withheld under MCP, read-only roles, the result
envelope the benchmark meters — never a model's judgement.
"""

import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hobbes.agent import loop
from hobbes.bench import accounting, arms, instances, workspace

LOOP = Path(loop.__file__)


class ScriptedModel:
    """An OpenAI-compatible /chat/completions that answers from a
    script: each entry is either a list of tool calls or a final text.
    Records every request body so tests can assert what the loop sent."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"body": body, "auth": self.headers.get("Authorization")})
                if not outer.script:
                    step = "nothing left in the script"
                else:
                    step = outer.script.pop(0)
                if isinstance(step, int):  # an HTTP error status
                    self.send_response(step)
                    self.end_headers()
                    self.wfile.write(b'{"error":"scripted"}')
                    return
                if isinstance(step, tuple) and step[0] == "http":  # ("http", status, body)
                    self.send_response(step[1])
                    self.end_headers()
                    self.wfile.write(step[2].encode())
                    return
                if isinstance(step, str):
                    message = {"role": "assistant", "content": step}
                else:
                    message = {"role": "assistant", "content": None, "tool_calls": [
                        {"id": f"call_{i}", "type": "function",
                         "function": {"name": name, "arguments": json.dumps(args)}}
                        for i, (name, args) in enumerate(step)]}
                reply = {"choices": [{"message": message, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler

    def close(self):
        self.server.shutdown()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def f():\n    return 1\n")
    (root / "README").write_text("hi\n")
    return root


def run_loop(model, tree, *extra, prompt="do it"):
    argv = ["--base-url", model.base_url, "--model", "m", "--prompt", prompt, "--workdir", str(tree), *extra]
    return loop.run(loop.parse(argv))


class TestNativeLoop:
    def test_reads_edits_runs_bash_and_reports(self, tree, monkeypatch):
        monkeypatch.setenv("HOBBES_LLM_API_KEY", "k-1")
        model = ScriptedModel([
            [("list_files", {}), ("read_file", {"path": "src/a.py"})],
            [("edit_file", {"path": "src/a.py", "old_text": "return 1", "new_text": "return 2"})],
            [("bash", {"command": "python3 -c 'import sys; sys.path.insert(0,\"src\"); import a; print(a.f())'"})],
            "changed f to return 2",
        ])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert env["is_error"] is False and env["result"] == "changed f to return 2"
        assert env["num_turns"] == 4 and env["tool_calls"] == 4
        assert env["usage"] == {"input_tokens": 400, "output_tokens": 40}
        assert (tree / "src" / "a.py").read_text() == "def f():\n    return 2\n"
        # the bearer token went out; tool results went back in order
        assert model.requests[0]["auth"] == "Bearer k-1"
        names = [t["function"]["name"] for t in model.requests[0]["body"]["tools"]]
        assert {"read_file", "list_files", "write_file", "edit_file", "bash"} <= set(names)
        last = model.requests[-1]["body"]["messages"]
        tool_msgs = [m for m in last if m["role"] == "tool"]
        assert "src/a.py" in tool_msgs[0]["content"] and "return 1" in tool_msgs[1]["content"]
        assert tool_msgs[-1]["content"].rstrip().endswith("[exit 0]") and "2" in tool_msgs[-1]["content"]
        # the meter reads the envelope like Claude Code's
        usage = accounting.from_envelope(env)
        assert usage.total_tokens == 440 and usage.turns == 4

    def test_file_tools_are_confined_and_edits_must_be_unique(self, tree):
        (tree / "src" / "dup.py").write_text("x = 1\nx = 1\n")
        model = ScriptedModel([
            [("read_file", {"path": "../outside"}), ("write_file", {"path": "/etc/passwd", "content": "no"}),
             ("edit_file", {"path": "src/dup.py", "old_text": "x = 1", "new_text": "x = 2"})],
            "gave up",
        ])
        try:
            run_loop(model, tree)
        finally:
            model.close()
        tool_msgs = [m for m in model.requests[-1]["body"]["messages"] if m["role"] == "tool"]
        assert all(m["content"].startswith("ERROR:") for m in tool_msgs)
        assert "outside the working tree" in tool_msgs[0]["content"]
        assert "occurs 2 times" in tool_msgs[2]["content"]
        assert (tree / "src" / "dup.py").read_text() == "x = 1\nx = 1\n"

    def test_read_only_role_gets_no_write_tools(self, tree):
        model = ScriptedModel([[("write_file", {"path": "x", "content": "y"})], "done"])
        try:
            run_loop(model, tree, "--role", "verifier")
        finally:
            model.close()
        names = [t["function"]["name"] for t in model.requests[0]["body"]["tools"]]
        assert "write_file" not in names and "edit_file" not in names
        tool_msgs = [m for m in model.requests[-1]["body"]["messages"] if m["role"] == "tool"]
        assert "not available to this role" in tool_msgs[0]["content"]
        assert not (tree / "x").exists()

    def test_turn_budget_and_server_errors_land_in_the_envelope(self, tree):
        model = ScriptedModel([[("list_files", {})]] * 5)
        try:
            env = run_loop(model, tree, "--max-turns", "2")
        finally:
            model.close()
        assert env["is_error"] and "turn budget (2)" in env["result"] and env["num_turns"] == 2
        model = ScriptedModel([400])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert env["is_error"] and "HTTP 400" in env["result"]

    def test_runs_as_a_script_and_prints_one_envelope_line(self, tree):
        model = ScriptedModel(["hello"])
        try:
            proc = subprocess.run([sys.executable, str(LOOP), "--base-url", model.base_url, "--model", "m",
                                   "--prompt", "hi", "--workdir", str(tree), "--max-nudges", "0"],
                                  capture_output=True, text=True)
        finally:
            model.close()
        assert proc.returncode == 0, proc.stderr
        env = accounting.find_envelope(proc.stdout)
        assert env and env["result"] == "hello" and env["runtime"] == "hobbes-agent-loop"

    def test_text_embedded_tool_calls_are_executed_and_counted(self, tree):
        """A small model that writes the call as a fenced JSON block (seen
        live on Qwen2.5-Coder-7B, ADR-057) still gets its tool run."""
        model = ScriptedModel([
            'I will read it:\n```json\n{"name": "read_file", "arguments": {"path": "README"}}\n```',
            '<tool_call>\n{"name": "edit_file", "arguments": {"path": "README", "old_text": "hi", "new_text": "yo"}}\n</tool_call>',
            "```json\n{\"not\": \"a call\"}\n```\ndone",
        ])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert env["tool_calls"] == 2 and env["text_tool_calls"] == 2 and env["num_turns"] == 3
        assert (tree / "README").read_text() == "yo\n"
        assert env["result"].endswith("done")

    def test_stdlib_only(self):
        """The sandbox image has python3 and nothing else; the loop must
        import nothing outside the standard library."""
        import ast
        tree_ = ast.parse(LOOP.read_text())
        imported = set()
        for node in ast.walk(tree_):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


#: A stdio JSON-RPC server that plays the hobbes-proxy: two tools, and a
#: log of every call so the test can see what reached it.
FAKE_MCP = """\
#!/usr/bin/env python3
import json, sys
log = open(sys.argv[1], "a")
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    m = msg["method"]
    if m == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}
    elif m == "tools/list":
        r = {"tools": [
            {"name": "exec", "description": "run", "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "who_calls", "description": "callers", "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}}}},
            {"name": "reflect", "description": "handoff", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "kind": {"type": "string"}}, "required": ["text"]}},
        ]}
    elif m == "tools/call":
        p = msg["params"]; log.write(json.dumps(p) + "\\n"); log.flush()
        if p["name"] == "exec" and "push" in p["arguments"].get("command", ""):
            r = {"content": [{"type": "text", "text": "denied: pushes are the human's"}], "isError": True}
        else:
            r = {"content": [{"type": "text", "text": f"{p['name']} ok: {p['arguments']}"}]}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": r}) + "\\n"); sys.stdout.flush()
"""


@pytest.fixture
def mcp_config(tmp_path):
    server = tmp_path / "fake-mcp.py"
    server.write_text(FAKE_MCP)
    server.chmod(server.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "mcp.log"
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"hobbes": {"command": sys.executable, "args": [str(server), str(log)]}}}))
    return cfg, log


class TestMCPLoop:
    def test_mcp_tools_are_listed_routed_and_bash_is_withheld(self, tree, mcp_config):
        cfg, log = mcp_config
        model = ScriptedModel([
            [("who_calls", {"target": "app.core"}), ("exec", {"command": "git status"})],
            [("bash", {"command": "id"}), ("exec", {"command": "git push"})],
            [("read_file", {"path": "README"})],
            "done",
        ])
        try:
            env = run_loop(model, tree, "--mcp-config", str(cfg))
        finally:
            model.close()
        assert env["is_error"] is False
        names = [t["function"]["name"] for t in model.requests[0]["body"]["tools"]]
        assert "exec" in names and "who_calls" in names and "bash" not in names
        calls = [json.loads(l) for l in log.read_text().splitlines()]
        assert [c["name"] for c in calls] == ["who_calls", "exec", "exec"]  # bash never reached the server
        tool_msgs = [m for m in model.requests[-1]["body"]["messages"] if m["role"] == "tool"]
        assert "not available in this session; use the exec tool" in tool_msgs[2]["content"]
        assert tool_msgs[3]["content"].startswith("ERROR: denied")
        assert "hi" in tool_msgs[4]["content"]  # native read still works beside MCP


class TestReadOnlyRoleDiscipline:
    """Harness restructure, phase 1: a read-only role's deliverable is a
    reflect handoff — the discipline nudges toward it and never toward
    an edit, and a handoff counts as acting."""

    def test_planner_gets_no_write_tools_and_is_nudged_toward_reflect(self, tree, mcp_config):
        cfg, log = mcp_config
        model = ScriptedModel([
            "Plan: change src/a.py f() to return 2; run tests/test_a.py.",   # prose, no handoff
            [("reflect", {"text": "files: src/a.py; approach: return 2", "kind": "handoff"})],
            "done",
        ])
        try:
            env = run_loop(model, tree, "--mcp-config", str(cfg), "--role", "planner")
        finally:
            model.close()
        names = [t["function"]["name"] for t in model.requests[0]["body"]["tools"]]
        assert "reflect" in names and "write_file" not in names and "edit_file" not in names
        assert env["nudges"] == 1 and env["reflected"] is True and env["edited"] is False
        assert not env["is_error"] and env["role"] == "planner"
        nudge = [m for m in model.requests[1]["body"]["messages"] if m["role"] == "user"][-1]["content"]
        assert "reflect" in nudge and "write_file" not in nudge

    def test_a_progress_reflection_is_not_the_handoff(self, tree, mcp_config):
        cfg, _ = mcp_config
        model = ScriptedModel([
            [("reflect", {"text": "looking", "kind": "progress"})],
            [("read_file", {"path": "README"})],
            [("read_file", {"path": "src/a.py"})],
            [("who_calls", {"target": "x"})],
            [("who_calls", {"target": "y"})],
            [("who_calls", {"target": "z"})],
        ])
        try:
            env = run_loop(model, tree, "--mcp-config", str(cfg), "--role", "verifier",
                           "--max-nudges", "0", "--stall-after", "4", "--max-turns", "20")
        finally:
            model.close()
        assert env["is_error"] and "without a handoff" in env["result"]
        assert env["reflected"] is False

    def test_implementer_discipline_is_unchanged_by_reflect(self, tree, mcp_config):
        cfg, _ = mcp_config
        model = ScriptedModel([
            [("reflect", {"text": "I would change f", "kind": "handoff"})],
            "all done",
        ])
        try:
            env = run_loop(model, tree, "--mcp-config", str(cfg), "--max-nudges", "1")
        finally:
            model.close()
        # an implementer that only reflects is still nudged toward editing
        assert env["nudges"] == 1 and env["edited"] is False


class TestBenchRuntime:
    def test_runtime_validation_and_session_args(self):
        with pytest.raises(ValueError, match="base_url"):
            arms.Runtime(kind="openai")
        with pytest.raises(ValueError, match="one of"):
            arms.Runtime(kind="ollama")
        rt = arms.Runtime(kind="openai", base_url="http://x/v1")
        # the turn budget reaches the harness sessions too (the first
        # full-stage probe ran them at the loop's default 60 vs pure's 40)
        assert rt.session_args() == ["--runtime", str(arms.LOOP_PATH), "--llm-base-url", "http://x/v1",
                                     "--max-turns", "60"]
        assert arms.Runtime().session_args() == []

    def test_pure_arm_on_the_owned_loop(self, tmp_path, monkeypatch):
        # a local upstream for the checkout
        base = tmp_path / "gh"
        repo = base / "acme" / "app"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "core.py").write_text("def handle():\n    return None\n")
        g = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*g[:3], "init", "-q"], check=True)
        subprocess.run([*g, "add", "."], check=True)
        subprocess.run([*g, "commit", "-qm", "b"], check=True)
        sha = subprocess.run([*g[:3], "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        monkeypatch.setenv(workspace.GIT_BASE_ENV, str(base) + "/")
        monkeypatch.setenv(workspace.CACHE_ENV, str(tmp_path / "cache"))
        inst = instances.parse_instance({"instance_id": "acme__app-1", "repo": "acme/app", "base_commit": sha,
                                         "problem_statement": "handle() should return 1"})
        ws = workspace.checkout(inst, tmp_path / "ws")
        model = ScriptedModel([
            [("edit_file", {"path": "src/core.py", "old_text": "return None", "new_text": "return 1"})],
            "fixed",
        ])
        try:
            result = arms.run_pure_arm(inst, ws, "qwen", runtime=arms.Runtime(kind="openai", base_url=model.base_url))
        finally:
            model.close()
        assert result.outcome == "patch" and result.patch_files == ["src/core.py"], result.error
        assert result.usage.total_tokens == 220 and result.usage.turns == 2
        assert result.detail["runtime"] == "openai"
        assert inst.problem_statement in model.requests[0]["body"]["messages"][1]["content"]


class TestContextWindow:
    """ADR-058: the loop fits the model's window instead of dying on it."""

    OVERFLOW = ('{"error":{"message":"This model\'s maximum context length is 32768 tokens and your '
                'request has %d input tokens (4096 > 32768 - %d). None","type":"BadRequestError"}}')

    def test_length_refusal_retries_with_fitted_max_tokens(self, tree):
        model = ScriptedModel([("http", 400, self.OVERFLOW % (30000, 30000)), "done"])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert not env["is_error"] and env["context_fitted"] == 1 and env["context_elided"] == 0
        assert model.requests[0]["body"]["max_tokens"] == 4096
        assert model.requests[1]["body"]["max_tokens"] == 32768 - 30000 - 16

    def test_no_room_elides_the_oldest_tool_result_and_says_so(self, tree):
        model = ScriptedModel([
            [("read_file", {"path": "src/a.py"})],
            [("read_file", {"path": "README"})],
            ("http", 400, self.OVERFLOW % (32700, 32700)),   # nothing left for a completion
            "done",
        ])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert not env["is_error"] and env["context_elided"] == 1
        tools = [m for m in model.requests[-1]["body"]["messages"] if m["role"] == "tool"]
        assert tools[0]["content"] == loop.ELIDED and "hi" in tools[1]["content"]

    def test_nothing_to_elide_is_the_error(self, tree):
        model = ScriptedModel([("http", 400, self.OVERFLOW % (32700, 32700))])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert env["is_error"] and "maximum context length" in env["result"]

    def test_tool_results_are_clipped_with_the_cut_stated(self, tree):
        (tree / "big.txt").write_text("x" * 50_000)
        model = ScriptedModel([[("read_file", {"path": "big.txt"})], "done"])
        try:
            env = run_loop(model, tree, "--max-result-chars", "1000")
        finally:
            model.close()
        content = [m for m in model.requests[-1]["body"]["messages"] if m["role"] == "tool"][0]["content"]
        assert len(content) < 1200 and "truncated:" in content and "more characters" in content


class TestProsePlanNudge:
    """ADR-058, fifth finding: a small model that describes a fix without
    editing is nudged to act, bounded so it still terminates."""

    def test_prose_before_editing_is_nudged_then_edits(self, tree):
        model = ScriptedModel([
            "Here is how I would fix it: change f to return 2.",   # prose, no tools
            [("write_file", {"path": "src/a.py", "content": "def f():\n    return 2\n"})],
            "Done: f now returns 2.",
        ])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert not env["is_error"] and env["nudges"] == 1 and env["edited"] is True
        # the nudge is a user message the model saw before it acted
        second = model.requests[1]["body"]["messages"]
        assert any(m["role"] == "user" and "not changed any files" in m["content"] for m in second)
        assert (tree / "src" / "a.py").read_text() == "def f():\n    return 2\n"

    def test_nudge_is_bounded_and_a_non_editing_model_terminates(self, tree):
        model = ScriptedModel(["plan one", "plan two", "plan three", "plan four"])
        try:
            env = run_loop(model, tree, "--max-nudges", "2")
        finally:
            model.close()
        assert env["edited"] is False and env["nudges"] == 2
        # 1 real turn + 2 nudged retries = 3 completions, then it gives up
        assert len(model.requests) == 3

    def test_a_model_that_edits_immediately_is_not_nudged(self, tree):
        model = ScriptedModel([
            [("write_file", {"path": "src/a.py", "content": "x\n"})],
            "done",
        ])
        try:
            env = run_loop(model, tree)
        finally:
            model.close()
        assert env["nudges"] == 0 and env["edited"] is True


class TestStrictPipeline:
    """ADR-058, sixth finding: the pipeline refuses repeated read-only
    calls and stops a non-editing stall instead of burning the budget."""

    def test_identical_readonly_call_is_refused_not_rerun(self, tree):
        model = ScriptedModel([
            [("read_file", {"path": "src/a.py"})],
            [("read_file", {"path": "src/a.py"})],   # exact repeat
            [("write_file", {"path": "src/a.py", "content": "def f():\n    return 2\n"})],
            "done",
        ])
        try:
            env = run_loop(model, tree, "--max-nudges", "0")
        finally:
            model.close()
        assert env["repeats_refused"] == 1 and env["edited"] is True and not env["is_error"]
        # the refusal reached the model as the tool result for the repeat
        msgs = model.requests[2]["body"]["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert any("Stop repeating it" in m["content"] for m in tool_msgs)

    def test_refused_repeats_after_an_edit_still_stop(self, tree):
        # the full-stage probe's U6: one commit, then 57 of 60 turns on
        # refused repeats — "acted" held, so the dry-turn stall never fired
        model = ScriptedModel([
            [("write_file", {"path": "src/a.py", "content": "def f():\n    return 2\n"})],
            *([[("read_file", {"path": "src/a.py"})]] * 12),
            "done",
        ])
        try:
            env = run_loop(model, tree, "--max-nudges", "0", "--stall-after", "4", "--max-turns", "30")
        finally:
            model.close()
        assert env["edited"] is True and env["is_error"]
        assert "refused repeated calls" in env["result"] and env["repeats_refused"] == 4
        assert len(model.requests) <= 7  # 1 edit + 1 first read + 4 refused, then stopped

    def test_a_nonediting_loop_stops_with_a_reason(self, tree):
        # tests_guarding-style: a read-only call repeated forever, never editing
        model = ScriptedModel([[("read_file", {"path": "README"})]] * 12)
        try:
            env = run_loop(model, tree, "--max-nudges", "1", "--nudge-after", "2", "--stall-after", "5", "--max-turns", "20")
        finally:
            model.close()
        assert env["is_error"] and "no progress" in env["result"]
        assert env["edited"] is False
        # it stopped well before the turn budget, not at turn 20
        assert env["num_turns"] < 20

    def test_a_dry_run_of_reads_then_an_edit_is_fine(self, tree):
        model = ScriptedModel([
            [("read_file", {"path": "src/a.py"})],
            [("list_files", {"path": "src"})],
            [("write_file", {"path": "src/a.py", "content": "x\n"})],
            "done",
        ])
        try:
            env = run_loop(model, tree, "--max-nudges", "0", "--nudge-after", "2")
        finally:
            model.close()
        assert env["edited"] is True and not env["is_error"] and env["repeats_refused"] == 0
