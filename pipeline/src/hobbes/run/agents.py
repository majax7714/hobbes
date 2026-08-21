"""Materializing agents from a change-spec (ADR-054).

An agent is *(context slice, policy profile, verification
obligations)* (agent-mapping §1). This module writes each one down as
a directory the sandbox mounts read-only at ``/agent``:

- ``policy.yaml`` — the derived **agent** policy layer (``scope:
  agent``): the P10 guarantees first, as denies; the unit's guarding
  tests allowed to run; a human-first unit denied every write. It is
  loaded last in the chain and can only narrow (ADR-002).
- ``context.json`` — the manifest the proxy reads to tag **context
  faults**: interior, boundary, and neighborhood ids plus the
  interior's paths. A knowledge query outside them is served and
  tagged — the allocator's error signal.
- ``context.md`` — the **standing** context, rendered: interior,
  guarding tests, docs, in-scope invariants, contracts with their
  pins, one-hop signatures, and the stated complement (mandatory,
  ADR-047 — refused upstream without it, restated here so the agent
  reads it first, not last).
- ``brief.md`` — what the session is started with: the role, the
  proposal, the standing context, the **short-term** inbox, and the
  obligations (commit on the session branch; run the guards; reflect
  when a contract proves wrong rather than working around it).

What the base does **not** enforce is stated in the brief and
registered as C-38: write mounts are advisory at path grain (the
sandbox mounts the worktree whole; the orchestrator measures rework
against the manifest afterwards instead).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from hobbes.run import mail

AGENTS_DIR = "agents"
ORCHESTRATOR = "orchestrator"

#: The specific guarantees (P10) every agent policy states first, as
#: denies — the same three the policy manifest names (ADR-051).
GUARANTEE_RULES = [
    {"pattern": "*.tfstate*", "decision": "deny",
     "reason": "tfstate carries secrets (I-1)"},
    {"pattern": "git push*", "decision": "deny",
     "reason": "sessions commit; the human publishes"},
    {"pattern": "git add *.hobbes/derived*", "decision": "deny",
     "reason": "derived is regenerable, never authored (P1)"},
]

#: How a guarding test file is run, by its suffix — the allow rules
#: an agent policy carries so its own guards never need an escalation.
_TEST_COMMANDS = {
    ".py": "uv run pytest {path}*",
    ".go": "go test ./{dir}*",
    ".ts": "npm test*",
    ".tsx": "npm test*",
    ".js": "npm test*",
    ".mjs": "npm test*",
    ".rs": "cargo test*",
}


def agents_root(plan_dir: Path) -> Path:
    return Path(plan_dir) / AGENTS_DIR


def agent_dir(plan_dir: Path, unit: str) -> Path:
    return agents_root(plan_dir) / unit


def _by_unit(spec: dict, key: str) -> dict[str, dict]:
    return {entry["unit"]: entry for entry in spec.get(key, [])}


def _module_of(target: str, kind: str) -> str:
    return target if kind == "module" else target.rsplit(".", 1)[0]


def build_policy(spec: dict, unit: str, test_files: dict[str, str]) -> dict:
    """The agent policy layer for *unit* as a policy-file dict."""
    context = _by_unit(spec, "contexts")[unit]
    rules = [dict(r) for r in GUARANTEE_RULES]
    if context.get("human_first"):
        rules.append({
            "pattern": "git commit*", "decision": "deny",
            "reason": "human-first unit: " + context.get("human_first_reason", ""),
        })
        rules.append({
            "pattern": "git add *", "decision": "deny",
            "reason": "human-first unit: the sandbox stays read-only",
        })
    seen: set[str] = set()
    for test_id in context.get("guarding_tests", []):
        path = test_files.get(test_id, "")
        template = _TEST_COMMANDS.get(Path(path).suffix)
        if not path or not template:
            continue
        pattern = template.format(path=path, dir=str(Path(path).parent))
        if pattern in seen:
            continue
        seen.add(pattern)
        rules.append({"pattern": pattern, "decision": "allow",
                      "reason": f"guards this unit ({test_id})"})
    return {"version": 1, "scope": "agent", "default": "escalate", "rules": rules}


def build_context_json(spec: dict, unit: str) -> dict:
    """The manifest the proxy tags context faults against."""
    context = _by_unit(spec, "contexts")[unit]
    interior = [m["id"] for m in context.get("modules", [])]
    boundary: list[str] = []
    for contract in spec.get("contracts", []):
        if unit not in (contract["from_unit"], contract["to_unit"]):
            continue
        far = contract["target"] if contract["owner"] != unit else contract["caller"]
        kind = contract.get("target_kind", "module") if contract["owner"] != unit else "module"
        module = _module_of(far, kind)
        if module not in interior and module not in boundary:
            boundary.append(module)
    return {
        "unit": unit,
        "interior": interior,
        "boundary": boundary,
        "neighborhood": [n["id"] for n in context.get("neighborhood", [])],
        "paths": [m["path"] for m in context.get("modules", []) if m.get("path")],
    }


def render_context(spec: dict, unit: str) -> str:
    """The standing context as markdown — the unit's manifest, complement
    first-class."""
    context = _by_unit(spec, "contexts")[unit]
    policy = _by_unit(spec, "policies")[unit]
    lines = [f"# Standing context — unit {unit}", ""]
    lines.append(f"Derived from graph {spec.get('graph_sha', '')[:12]}"
                 + (" (dirty)" if spec.get("graph_dirty") else "")
                 + f"; plan {spec['task']}. This context moves only when a "
                 "commit changes the graph and it is re-ingested.")
    lines.append("")
    lines.append("## Interior (full resolution — yours to change)")
    for m in context.get("modules", []):
        lines.append(f"- `{m['id']}` — {m.get('path') or 'no path'}")
    lines.append("")
    lines.append("## Guarding tests (run these; they are the behaviors you can break)")
    lines += [f"- {t}" for t in context.get("guarding_tests", [])] or ["- none recorded — this code is unguarded"]
    lines.append("")
    if context.get("docs"):
        lines.append("## Module docs (pinned claims; `get_module_doc`)")
        lines += [f"- {d}" for d in context["docs"]]
        lines.append("")
    lines.append("## Invariants in scope (breaking one is a review failure)")
    lines += [f"- {i}" for i in context.get("invariants", [])] or ["- none confirmed for these paths"]
    lines.append("")
    lines.append("## Contracts at your boundary (the only interface to other units)")
    mine = [c for c in spec.get("contracts", []) if unit in (c["from_unit"], c["to_unit"])]
    for c in mine:
        side = "you own the declaration" if c["owner"] == unit else f"owned by {c['owner']}"
        lines.append(
            f"- {c['id']}: `{c['caller']}` → `{c['target']}` ({c['edge_type']}, "
            f"{c['tier']}) pinned at {c['declared_at']} — {side}; {c.get('pin', '')}"
        )
    if not mine:
        lines.append("- none: this unit is self-contained")
    lines.append("")
    lines.append("## Neighborhood (one hop out — signatures only, internals deliberately absent)")
    for n in context.get("neighborhood", []):
        syms = ", ".join(n.get("symbols", [])[:12])
        more = "" if len(n.get("symbols", [])) <= 12 else f" … +{len(n['symbols']) - 12}"
        lines.append(f"- `{n['id']}`: {syms}{more}")
    if not context.get("neighborhood"):
        lines.append("- none")
    lines.append("")
    comp = context.get("complement") or {}
    lines.append("## What Hobbes cannot see here (read this before trusting the rest)")
    lines.append(f"- {comp.get('denominator', '')}")
    sites, unresolved = comp.get("sites", 0), comp.get("unresolved", 0)
    lines.append(f"- {unresolved} of {sites} detected call sites in this unit are unresolved")
    for cls, n in (comp.get("tail") or {}).items():
        lines.append(f"  - {cls} {n}: {comp.get('meanings', {}).get(cls, '')}")
    for gap in comp.get("environment_gaps", []):
        lines.append(f"- environment gap: {gap}")
    for deg in comp.get("degradations", []):
        lines.append(f"- degraded: {deg}")
    for w in comp.get("warnings", []):
        lines.append(f"- warning: {w}")
    if context.get("human_first"):
        lines.append(f"- **human-first**: {context.get('human_first_reason', '')}")
    lines.append("- `list_blind_spots` gives the same for any path.")
    lines.append("")
    lines.append("## Derived policy (advisory at path grain — C-38; measured as rework afterwards)")
    lines.append(f"- floor: {policy.get('floor', '')}")
    for g in policy.get("guarantees", []):
        lines.append(f"- guarantee: {g}")
    lines.append("- write scope: " + (", ".join(policy.get("write_mounts", [])) or "none"))
    for f in policy.get("flags", []):
        lines.append(f"- flag: {f}")
    lines.append("")
    return "\n".join(lines)


#: Standing-context sections a brief limit never cuts: the complement
#: (ADR-047's contract — derived context must carry what it cannot see),
#: the policy, the contracts and the invariants. Everything else is
#: detail the model can re-fetch through the knowledge tools.
PROTECTED_SECTIONS = ("## What Hobbes cannot see", "## Derived policy", "## Contracts at your boundary",
                      "## Invariants in scope")


def limit_context(context: str, limit: int) -> tuple[str, int]:
    """Cut *context* (a ``render_context`` document) to at most *limit*
    characters by trimming its unprotected sections to an equal share
    of what the protected ones leave, each with a stated cut line
    (C-45). Returns the text and the number of characters dropped."""
    if len(context) <= limit:
        return context, 0
    parts = context.split("\n## ")
    head, sections = parts[0], ["## " + p for p in parts[1:]]
    protected = [s for s in sections if s.startswith(PROTECTED_SECTIONS)]
    cuttable = [s for s in sections if not s.startswith(PROTECTED_SECTIONS)]
    def notice(lost: int) -> str:
        return (f"\n… cut: {lost} more line(s) not shown — the brief is held to {limit:,} characters "
                "for the model's context window (C-45); the knowledge tools still answer for them")

    # Protected sections are never cut, so a limit below their size is
    # not met — the returned text is then as small as honesty allows.
    fixed = len(head) + sum(len(s) + 1 for s in protected)
    reserve = len(notice(99999)) + 1
    share = max(0, (limit - fixed) // max(1, len(cuttable)) - reserve)
    dropped = 0
    out = []
    for section in sections:
        if section in protected or len(section) <= share + reserve:
            out.append(section)
            continue
        title, _, body = section.partition("\n")
        kept_lines, used = [], len(title) + 1
        for line in body.splitlines():
            if used + len(line) + 1 > share:
                break
            kept_lines.append(line)
            used += len(line) + 1
        lost = len(body.splitlines()) - len(kept_lines)
        dropped += len(section) - used
        out.append(title + "\n" + "\n".join(kept_lines) + notice(lost))
    return "\n".join([head, *out]), dropped


def render_brief(spec: dict, unit: str, role: str, inbox: list[dict], session: str,
                 limit: int | None = None) -> str:
    """The session's opening prompt: role, proposal, both horizons,
    obligations. With *limit*, the standing context is cut to fit
    (:func:`limit_context`) and the brief says so."""
    lines = [
        f"You are a single-use {role} for unit {unit} of plan {spec['task']}.",
        "",
        f"## Proposal\n{spec.get('proposal', '')}",
        "",
        "## Obligations",
        f"- Work only inside your interior; commit on the session branch "
        f"(`hobbes/{session}`) with conventional commits. Do not create "
        "branches, merge, rebase, or push.",
        "- Run the guarding tests before committing; a guard you cannot run "
        "is a reflection, not a skipped step.",
        "- Contracts are the only interface to other units. If a pinned "
        "contract proves wrong, call `reflect` with the amendment you need "
        "and stop at that boundary — a silent workaround is a policy "
        "violation, not initiative.",
        "- The knowledge tools answer for any node; outside your manifest "
        "the answer is still served, and logged as a context fault. Use "
        "them — the faults are how the allocator learns.",
        "- When done, `reflect` a two-line summary: what changed, and what "
        "you could not verify.",
        "",
        "## Short-term context (your inbox, newest last)",
    ]
    if inbox:
        for message in inbox:
            lines.append(f"- [{message.get('seq')}] from {message.get('from')} "
                         f"({message.get('kind')}): {message.get('text')}")
    else:
        lines.append("- empty: nothing has been pushed to you yet")
    context = render_context(spec, unit)
    if limit is not None:
        room = limit - len("\n".join(lines)) - 120  # the cut notice on line 2
        context, dropped = limit_context(context, max(room, 0))
        if dropped:
            lines.insert(1, f"(standing context cut by {dropped:,} characters to fit the brief limit — C-45)")
    lines += ["", context]
    return "\n".join(lines)


def materialize(
    plan_dir: Path, spec: dict, tests: dict, role: str = "implementer"
) -> dict[str, Path]:
    """Write every unit's agent dir (and the orchestrator's inbox dir);
    returns ``unit -> dir``. Briefs are written separately at spawn
    time, because they carry the inbox as it stands then."""
    test_files = {t["id"]: t.get("file", "") for t in tests.get("tests", [])}
    out: dict[str, Path] = {}
    for unit in spec.get("units", []):
        name = unit["name"]
        directory = agent_dir(plan_dir, name)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "policy.yaml").write_text(
            yaml.safe_dump(build_policy(spec, name, test_files), sort_keys=False)
        )
        (directory / "context.json").write_text(
            json.dumps(build_context_json(spec, name), indent=2) + "\n"
        )
        (directory / "context.md").write_text(render_context(spec, name))
        (directory / mail.INBOX).touch()
        out[name] = directory
    orchestrator = agent_dir(plan_dir, ORCHESTRATOR)
    orchestrator.mkdir(parents=True, exist_ok=True)
    (orchestrator / mail.INBOX).touch()
    return out
