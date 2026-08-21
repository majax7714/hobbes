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

READ_ONLY_ROLES = {"reviewer", "verifier"}

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

class Endpoint:
    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float, max_tokens: int):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key, self.timeout, self.max_tokens = model, api_key, timeout, max_tokens

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": 0}
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
                if exc.code < 500 and exc.code != 429:
                    raise last
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = RuntimeError(f"{type(exc).__name__}: {exc}")
            time.sleep(2 ** attempt)
        raise last  # type: ignore[misc]


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
            if not calls:
                final = message.get("content") or ""
                break
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                try:
                    targs = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    text, is_err = f"arguments were not valid JSON: {exc}", True
                else:
                    if mcp and name in mcp_names:
                        text, is_err = mcp.call(name, targs)
                    else:
                        text, is_err = native_call(name, targs, workdir, allow_bash=mcp is None,
                                                   allow_write=not read_only)
                tool_calls_made += 1
                print(f"[turn {turns}] {name}({json.dumps(targs)[:160]}) → {'error' if is_err else 'ok'}",
                      file=sys.stderr, flush=True)
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name,
                                 "content": (("ERROR: " if is_err else "") + text)[-30000:]})
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
    p.add_argument("--role", default="implementer")
    p.add_argument("--workdir", default=".")
    p.add_argument("--max-turns", type=int, default=60)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--timeout", type=float, default=600.0)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    envelope = run(parse(sys.argv[1:] if argv is None else argv))
    print(json.dumps(envelope), flush=True)
    return 1 if envelope["is_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
