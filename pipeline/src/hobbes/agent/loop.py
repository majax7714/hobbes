#!/usr/bin/env python3
"""A minimal agent loop over an OpenAI-compatible chat endpoint (ADR-056).

**Stdlib only, one file.** ``hobbes-session`` copies this file into the
session dir and runs it inside the sandbox with the image's ``python3``;
the pure benchmark arm runs it on the host. Either way it is the same
loop:

1. send the system prompt, the task, and the tool schemas;
2. execute every tool call the model returns — MCP tools through the
   hobbes-proxy over stdio (the sandbox's policy-checked ``exec`` and
   the knowledge tools), native ``bash`` only when no MCP config is
   given (the pure arm), and confined file tools either way;
3. feed the results back; stop when the model answers without tool
   calls or the turn budget runs out.

It prints one **result envelope** on stdout in Claude Code's shape
(``type: result``, ``usage``, ``duration_ms``, ``num_turns``,
``is_error``), so the benchmark's meter reads both runtimes with one
reader. Everything else goes to stderr.

Usage::

    loop.py --base-url URL --model NAME [--api-key-env VAR]
            (--prompt TEXT | --prompt-file FILE)
            [--mcp-config FILE] [--role ROLE] [--workdir DIR]
            [--max-turns N] [--max-tokens N] [--timeout SEC]

The API key is read from the environment variable named by
``--api-key-env`` (default ``HOBBES_LLM_API_KEY``); an unset variable
sends no ``Authorization`` header, which is what a private endpoint
wants.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

SYSTEM_PROMPT = """\
You are a software engineer working in a git checkout at {workdir}.
Use the tools to read code, change it, and run commands; do the task
in the prompt and nothing else. Work in small verified steps: read
before you edit, run the relevant tests after you edit. When the task
is done, reply with a short plain-text summary of what you changed
and what you could not verify, and stop calling tools. Call tools
through the tool-calling interface, never by writing JSON in your
message.
"""

#: Roles whose worktree is read-only and whose *job is a handoff*: they
#: do their work through reflect, never through an edit (harness
#: restructure, phase 1). Mirrors go/internal/sandbox ReadOnlyRoles.
READ_ONLY_ROLES = {"reviewer", "verifier", "planner"}

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```|<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def text_tool_calls(content: str) -> list[dict]:
    """Tool calls a model wrote *as text* — a fenced JSON object or a
    ``<tool_call>`` block with ``name`` and ``arguments`` — in the
    shape of structured ones. Small models do this; refusing them
    would measure the chat template, not the model. The loop counts
    how often it happened (``text_tool_calls`` in the envelope) so the
    accommodation is visible in every record."""
    out = []
    for n, match in enumerate(_FENCED.finditer(content or "")):
        raw = match.group(1) or match.group(2)
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("name"), str):
            continue
        args = doc.get("arguments", doc.get("parameters", {}))
        if not isinstance(args, dict):
            continue
        out.append({"id": f"text_{n}", "type": "function",
                    "function": {"name": doc["name"], "arguments": json.dumps(args)}})
    return out


# --------------------------------------------------------------------------
# MCP over stdio (newline-delimited JSON-RPC, the go-sdk's stdio transport)

class MCPClient:
    """The one MCP server a session has: the hobbes-proxy from the
    wrapper's ``mcp.json``. Tools are listed from it, never assumed."""

    def __init__(self, config_path: str):
        cfg = json.load(open(config_path))["mcpServers"]
        name, server = next(iter(cfg.items()))
        self.proc = subprocess.Popen(
            [server["command"], *server.get("args", [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, text=True,
        )
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "hobbes-agent-loop", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed the connection")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"MCP {method}: {msg['error']}")
                return msg.get("result", {})

    def tools(self) -> list[dict]:
        """MCP tool descriptors as OpenAI function tools."""
        out = []
        for tool in self._rpc("tools/list", {}).get("tools", []):
            out.append({"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }})
        return out

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        result = self._rpc("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        return text, bool(result.get("isError"))

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except Exception:  # noqa: BLE001 — shutting down
            self.proc.kill()


# --------------------------------------------------------------------------
# Native tools: confined file access, and bash only for the pure arm

def _confine(workdir: str, path: str) -> str:
    full = os.path.realpath(os.path.join(workdir, path))
    root = os.path.realpath(workdir)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"{path!r} is outside the working tree")
    return full


FILE_TOOLS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file in the working tree (path relative to it). Returns the text with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "1-based first line (default 1)"},
            "end_line": {"type": "integer", "description": "1-based last line (default: end)"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_files", "description": "List files under a directory of the working tree (default: its root), recursively, up to 500 entries.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
]

WRITE_TOOLS = [
    {"type": "function", "function": {
        "name": "write_file", "description": "Create or overwrite a file in the working tree with the given content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "Replace one exact occurrence of old_text with new_text in a file. Fails if old_text is absent or ambiguous — include enough context to be unique.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"]}}},
]

BASH_TOOL = {"type": "function", "function": {
    "name": "bash", "description": "Run a shell command in the working tree and return its output (stdout+stderr, exit code).",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string"}, "timeout": {"type": "integer", "description": "seconds (default 300)"}},
        "required": ["command"]}}}


def native_call(name: str, args: dict, workdir: str, allow_bash: bool, allow_write: bool) -> tuple[str, bool]:
    """Execute a native tool; returns (text, is_error)."""
    try:
        if name == "read_file":
            full = _confine(workdir, args["path"])
            lines = open(full, encoding="utf-8", errors="replace").read().splitlines()
            start = max(int(args.get("start_line") or 1), 1)
            end = min(int(args.get("end_line") or len(lines)), len(lines))
            body = "\n".join(f"{n:6d}\t{lines[n - 1]}" for n in range(start, end + 1))
            return (body or "(empty file)"), False
        if name == "list_files":
            full = _confine(workdir, args.get("path") or ".")
            out = []
            for root, dirs, files in os.walk(full):
                dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".hobbes"))
                for f in sorted(files):
                    out.append(os.path.relpath(os.path.join(root, f), workdir))
                    if len(out) >= 500:
                        return "\n".join(out) + "\n… truncated at 500", False
            return "\n".join(out) or "(no files)", False
        if name in ("write_file", "edit_file"):
            if not allow_write:
                return f"{name} is not available to this role", True
            full = _confine(workdir, args["path"])
            if name == "write_file":
                os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(args["content"])
                return f"wrote {args['path']} ({len(args['content'])} bytes)", False
            text = open(full, encoding="utf-8").read()
            count = text.count(args["old_text"])
            if count != 1:
                return (f"old_text occurs {count} times in {args['path']}; it must occur exactly once"), True
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text.replace(args["old_text"], args["new_text"], 1))
            return f"edited {args['path']}", False
        if name == "bash":
            if not allow_bash:
                return "bash is not available in this session; use the exec tool", True
            timeout = int(args.get("timeout") or 300)
            proc = subprocess.run(args["command"], shell=True, cwd=workdir, capture_output=True,
                                  text=True, timeout=timeout)
            out = (proc.stdout + proc.stderr)[-20000:]
            return f"{out}\n[exit {proc.returncode}]", proc.returncode != 0
        return f"unknown tool {name}", True
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}", True


# --------------------------------------------------------------------------
# The endpoint

#: What a context-length refusal looks like (vLLM's wording, also
#: OpenAI's): the window and the request's input, both in tokens.
CONTEXT_LENGTH_RE = re.compile(r"maximum context length is (\d+) tokens.*?(\d+) input tokens", re.S)
#: Below this many completion tokens a fitted call is not worth making;
#: the loop elides old tool results instead.
MIN_COMPLETION = 256
ELIDED = "[tool result elided to fit the model's context window]"
#: Tool names that mutate the tree — an edit is what a patch is made of.
#: `write_file`/`edit_file` are the loop's; `mcp__hobbes__exec` is the
#: sandbox's shell (used to apply changes or run tests). A model that
#: stops before calling one of these has described a fix, not made one.
MUTATING_TOOLS = {"write_file", "edit_file"}
#: The nudge sent when a small model returns a prose plan before editing
#: (ADR-058, the fifth finding): the 7B reads "summarize when done" and
#: jumps to the summary on turn 1. Bounded so a model that simply cannot
#: act still terminates.
NUDGE = (
    "You have not changed any files yet — you only described what to do. "
    "A description is not a fix. Make the change now by calling the "
    "write_file or edit_file tool (and run the guarding tests with the "
    "exec tool). Do not reply with a summary until the files are edited."
)
#: The same nudge for a read-only role: its deliverable is a reflect
#: handoff, and a prose reply that never reaches the orchestrator is the
#: same failure as a prose plan that never edits.
NUDGE_READ_ONLY = (
    "You have not sent your result yet — you only described it. A reply "
    "the orchestrator never receives is not a result. Call the reflect "
    "tool now with kind \"handoff\" and your complete answer as the text. "
    "Do not reply with a summary until reflect has been called."
)
#: Returned in place of re-running a tool the model already called with
#: the exact same arguments (ADR-058, sixth finding — a 7B unit called
#: one read-only tool 55 times). The pipeline refuses the repeat rather
#: than pay for it; the model must do something new.
REPEAT_REFUSAL = (
    "You already called this tool with these exact arguments and the "
    "result has not changed. Stop repeating it. Read something new, edit "
    "a file with write_file/edit_file, or finish — do not call it again."
)


class ContextOverflow(RuntimeError):
    """The endpoint refused the request for length; carries the window
    and input sizes it reported."""

    def __init__(self, message: str, window: int, inputs: int):
        super().__init__(message)
        self.window, self.inputs = window, inputs


class Endpoint:
    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float, max_tokens: int):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key, self.timeout, self.max_tokens = model, api_key, timeout, max_tokens
        #: How often the window had to be fitted or trimmed — the
        #: envelope reports both, so a run can see the window bind.
        self.fitted, self.elided = 0, 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """One completion, fitted to the model's window: a length
        refusal retries with ``max_tokens`` shrunk to what is left, and
        when that would leave fewer than :data:`MIN_COMPLETION` tokens
        the oldest tool results are elided (in place, stated) until the
        request fits or nothing is left to elide."""
        max_tokens = self.max_tokens
        while True:
            try:
                return self._post(messages, tools, max_tokens)
            except ContextOverflow as exc:
                room = exc.window - exc.inputs - 16
                if room >= MIN_COMPLETION and room < max_tokens:
                    max_tokens = room
                    self.fitted += 1
                    continue
                if not elide_oldest_tool_result(messages):
                    raise
                self.elided += 1
                max_tokens = self.max_tokens

    def _post(self, messages: list[dict], tools: list[dict], max_tokens: int) -> dict:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = None
        for attempt in range(4):
            req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:500]
                last = RuntimeError(f"HTTP {exc.code} from {self.url}: {detail}")
                if exc.code == 400 and (m := CONTEXT_LENGTH_RE.search(detail)):
                    raise ContextOverflow(str(last), int(m.group(1)), int(m.group(2)))
                if exc.code < 500 and exc.code != 429:
                    raise last
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = RuntimeError(f"{type(exc).__name__}: {exc}")
            time.sleep(2 ** attempt)
        raise last  # type: ignore[misc]


def elide_oldest_tool_result(messages: list[dict]) -> bool:
    """Replace the content of the oldest not-yet-elided tool result with
    a stated placeholder. Returns False when there is none left — the
    brief itself is then what does not fit, and that is an error."""
    for message in messages:
        if message.get("role") == "tool" and message.get("content") != ELIDED:
            message["content"] = ELIDED
            return True
    return False


def clip(text: str, limit: int) -> str:
    """A tool result cut to *limit* characters, head kept (a file's top
    carries its imports and signatures), the cut stated."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated: {len(text) - limit:,} more characters; read a narrower range]"


# --------------------------------------------------------------------------
# The loop

def run(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    workdir = os.path.abspath(args.workdir)
    prompt = args.prompt if args.prompt is not None else open(args.prompt_file, encoding="utf-8").read()
    read_only = args.role in READ_ONLY_ROLES
    mcp = MCPClient(args.mcp_config) if args.mcp_config else None
    tools = list(FILE_TOOLS)
    if not read_only:
        tools += WRITE_TOOLS
    if mcp:
        tools += mcp.tools()
    else:
        tools.append(BASH_TOOL)
    mcp_names = {t["function"]["name"] for t in (mcp.tools() if mcp else [])}
    endpoint = Endpoint(args.base_url, args.model, os.environ.get(args.api_key_env) or None,
                        args.timeout, args.max_tokens)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(workdir=workdir)},
                {"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    turns, tool_calls_made, text_calls, final, error = 0, 0, 0, "", ""
    edited, nudges_left, nudges = False, args.max_nudges, 0
    reflected = False
    nudge_text = NUDGE_READ_ONLY if read_only else NUDGE
    seen_calls: set[tuple[str, str]] = set()
    repeats, dry_turns, refused_run = 0, 0, 0
    try:
        while turns < args.max_turns:
            turns += 1
            reply = endpoint.chat(messages, tools)
            u = reply.get("usage") or {}
            usage["input_tokens"] += int(u.get("prompt_tokens") or 0)
            usage["output_tokens"] += int(u.get("completion_tokens") or 0)
            message = (reply.get("choices") or [{}])[0].get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                calls = text_tool_calls(message.get("content") or "")
                text_calls += len(calls)
            messages.append({"role": "assistant", "content": message.get("content") or "",
                             **({"tool_calls": calls} if calls else {})})
            productive = False
            refused_turn = False
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                raw = fn.get("arguments") or "{}"
                try:
                    targs = json.loads(raw)
                except json.JSONDecodeError as exc:
                    text, is_err = f"arguments were not valid JSON: {exc}", True
                else:
                    sig = (name, json.dumps(targs, sort_keys=True))
                    mutating = name in MUTATING_TOOLS or name.endswith("__exec") or name == "bash"
                    if sig in seen_calls and not mutating:
                        # A repeated read-only call: refuse, do not re-run it.
                        text, is_err = REPEAT_REFUSAL, True
                        repeats += 1
                        refused_turn = True
                    else:
                        seen_calls.add(sig)
                        if mcp and name in mcp_names:
                            text, is_err = mcp.call(name, targs)
                        else:
                            text, is_err = native_call(name, targs, workdir, allow_bash=mcp is None,
                                                       allow_write=not read_only)
                        if not is_err and mutating:
                            edited = True
                            productive = True
                        if not is_err and name.endswith("reflect") and targs.get("kind") == "handoff":
                            # A read-only role's deliverable (planner, verifier):
                            # the handoff is its edit.
                            reflected = True
                            productive = True
                tool_calls_made += 1
                print(f"[turn {turns}] {name}({json.dumps(targs)[:160]}) → {'error' if is_err else 'ok'}",
                      file=sys.stderr, flush=True)
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name,
                                 "content": clip(("ERROR: " if is_err else "") + text, args.max_result_chars)})
            # Pipeline discipline (ADR-058): a turn that changed nothing is
            # "dry". Nudge toward acting; once nudges are spent, a run of
            # dry turns is a stall, not progress — stop with a reason
            # rather than burn the turn budget (the 55-identical-calls loop).
            # For a read-only role the deliverable is a handoff reflection,
            # so "acted" means reflected, not edited.
            acted = reflected if read_only else edited
            # A run of turns that only re-issue refused calls is a stall
            # whether or not the session edited earlier: the first
            # full-stage probe's U6 had committed, then spent 57 of 60
            # turns on refused repeats (1.5M tokens) because "acted" held.
            refused_run = refused_run + 1 if (refused_turn and not productive) else 0
            if refused_run >= args.stall_after:
                error = f"no progress: {refused_run} turns of refused repeated calls ({repeats} refused in all)"
                break
            if productive:
                dry_turns = 0
            else:
                dry_turns += 1
                if not acted and nudges_left > 0 and (not calls or dry_turns >= args.nudge_after):
                    nudges_left -= 1
                    nudges += 1
                    dry_turns = 0
                    messages.append({"role": "user", "content": nudge_text})
                    continue
                if not calls:
                    final = message.get("content") or ""
                    break
                if not acted and dry_turns >= args.stall_after:
                    what = "a handoff" if read_only else "an edit"
                    error = f"no progress: {dry_turns} turns without {what} after {nudges} nudge(s)"
                    break
        else:
            error = f"turn budget ({args.max_turns}) exhausted"
    except Exception as exc:  # noqa: BLE001 — the envelope carries it
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if mcp:
            mcp.close()
    duration = int((time.monotonic() - started) * 1000)
    return {
        "type": "result", "subtype": "success" if not error else "error",
        "is_error": bool(error), "duration_ms": duration, "num_turns": turns,
        "tool_calls": tool_calls_made, "text_tool_calls": text_calls,
        "context_fitted": endpoint.fitted, "context_elided": endpoint.elided,
        "nudges": nudges, "edited": edited, "reflected": reflected, "repeats_refused": repeats,
        "role": args.role,
        "result": final or error, "model": args.model,
        "runtime": "hobbes-agent-loop", "usage": usage,
    }


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="OpenAI-compatible API root, e.g. https://host/v1")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key-env", default="HOBBES_LLM_API_KEY")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    p.add_argument("--mcp-config", help="the session's mcp.json; tools come from its server, bash is withheld")
    p.add_argument("--role", default="implementer",
                   help="the session role; a read-only role (planner, reviewer, verifier) gets no write "
                        "tools and is disciplined toward a reflect handoff instead of an edit")
    p.add_argument("--workdir", default=".")
    p.add_argument("--max-turns", type=int, default=60)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--max-result-chars", type=int, default=12_000,
                   help="a tool result is clipped to this many characters, the cut stated (default 12000)")
    p.add_argument("--max-nudges", type=int, default=2,
                   help="how many times to nudge a model that stops at a prose plan before editing (default 2)")
    p.add_argument("--nudge-after", type=int, default=3,
                   help="dry (no-edit) turns before a mid-stream nudge (default 3)")
    p.add_argument("--stall-after", type=int, default=6,
                   help="dry (no-edit) turns before stopping a stalled session with a reason (default 6)")
    p.add_argument("--timeout", type=float, default=600.0)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    envelope = run(parse(sys.argv[1:] if argv is None else argv))
    print(json.dumps(envelope), flush=True)
    return 1 if envelope["is_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
