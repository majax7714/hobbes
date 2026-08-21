"""Short-term context: per-agent inboxes and reflections (ADR-054).

Two horizons of context, per the owner's structure. The standing
context is derived and moves only with commits; the **short-term**
context is messaging — role-pushed mail. The orchestrator posts to a
unit's ``inbox.jsonl`` (a needed specific, a renegotiated contract, a
verifier finding); the agent's brief carries the inbox in full; the
agent answers through the proxy's ``reflect`` tool, which lands in
``<session>/mail.jsonl`` and is folded back into the orchestrator's
own inbox after the session. Nothing here is a transcript: each line
is one message with a sender, a sequence number, and a body.

Files are JSON lines, append-only, in the agent dir under
``.hobbes/plans/<task>/agents/<unit>/`` — beside the plan, because a
message is part of the task's record, not of the regenerable
``derived/`` layer.
"""

from __future__ import annotations

import json
from pathlib import Path

INBOX = "inbox.jsonl"


def post(agent_dir: Path, sender: str, text: str, kind: str = "request") -> dict:
    """Append one message to *agent_dir*'s inbox; returns the message."""
    agent_dir = Path(agent_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / INBOX
    seq = len(read(agent_dir)) + 1
    message = {"seq": seq, "from": sender, "kind": kind, "text": text}
    with path.open("a") as handle:
        handle.write(json.dumps(message) + "\n")
    return message


def read(agent_dir: Path) -> list[dict]:
    """Every message in *agent_dir*'s inbox, in order."""
    path = Path(agent_dir) / INBOX
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def reflections(session_dir: Path) -> list[dict]:
    """The messages a session sent back through ``reflect``
    (``<session>/mail.jsonl``), in order; empty when it sent none."""
    path = Path(session_dir) / "mail.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def fold_back(orchestrator_dir: Path, unit: str, reflected: list[dict]) -> int:
    """Deliver a unit's reflections into the orchestrator's inbox, one
    message each, sender ``<unit>``; returns how many were delivered."""
    for message in reflected:
        post(orchestrator_dir, unit, message.get("text", ""), kind="reflection")
    return len(reflected)
