"""Reading an agent's handoff (harness restructure, ADR-059).

A handoff is the one reflection an agent sends with ``kind: handoff``
— its job for the next agent, in short memory. The orchestrator asks
for a fixed, line-keyed shape (``files:``, ``symbols:``, ``tests:``,
``approach:``, ``risks:``, ``verdict:``, ``units:``, ``reason:``) and
reads it tolerantly: bullets, backticks, quotes and a JSON object are
all accepted, because a small model follows a schema loosely. What is
*not* done is inference from prose: a file that is not named is not
guessed, and a verdict that is not keyed is reported as inferred
rather than asserted.
"""

from __future__ import annotations

import json
import re

#: The keys the orchestrator reads, and the aliases a model tends to use.
LIST_FIELDS = ("files", "symbols", "tests", "units")
TEXT_FIELDS = ("approach", "risks", "verdict", "reason")
ALIASES = {
    "file": "files", "paths": "files", "path": "files", "modules": "files",
    "symbol": "symbols", "functions": "symbols", "function": "symbols", "classes": "symbols",
    "test": "tests", "tests_to_run": "tests", "tests to run": "tests", "run": "tests",
    "unit": "units", "rework": "units",
    "plan": "approach", "summary": "approach", "changes": "approach",
    "risk": "risks", "unverified": "risks", "could not verify": "risks",
    "result": "verdict", "status": "verdict", "outcome": "verdict",
    "why": "reason", "failure": "reason", "failures": "reason",
}
#: The verdicts a verifier or reviewer may return, normalised.
VERDICTS = {"pass": "pass", "passed": "pass", "passes": "pass", "ok": "pass", "green": "pass",
            "fail": "fail", "failed": "fail", "fails": "fail", "failing": "fail", "red": "fail",
            "approve": "approve", "approved": "approve", "accept": "approve", "lgtm": "approve",
            "amend": "amend", "revise": "amend", "reject": "amend", "change": "amend"}

_KEYED = re.compile(r"^\s*(?:[-*•]\s*)?(?:#+\s*)?[`*_]*([A-Za-z][A-Za-z _]{1,24}?)[`*_]*\s*[:=]\s*(.*)$")
_SPLIT = re.compile(r"[,\n;]+|\s+(?=(?:[\w./-]+))")


def _clean(item: str) -> str:
    return item.strip().strip("`'\"*-•[]() ").strip()


def _listify(value) -> list[str]:
    if isinstance(value, list):
        raw = [str(v) for v in value]
    else:
        raw = re.split(r"[,\n;]+", str(value))
    out: list[str] = []
    for item in raw:
        item = _clean(item)
        # "path (reason)" / "path — reason": keep the path
        item = re.split(r"\s+[—–-]\s+|\s+\(", item, maxsplit=1)[0].strip()
        if item and item.lower() not in ("none", "n/a", "-") and item not in out:
            out.append(item)
    return out


def _norm_key(key: str) -> str | None:
    k = key.strip().lower().replace("-", " ").replace("_", " ")
    k2 = k.replace(" ", "_")
    for candidate in (k, k2):
        if candidate in LIST_FIELDS or candidate in TEXT_FIELDS:
            return candidate
        if candidate in ALIASES:
            return ALIASES[candidate]
    return None


def parse_handoff(text: str) -> dict:
    """Parse a handoff into ``{field: value}`` with list fields as lists.

    Returns the fields present plus ``verdict_source`` (``keyed`` when a
    ``verdict:`` line was given, ``inferred`` when the word had to be
    found in prose, ``none`` otherwise) and ``raw`` — the text itself,
    which is what the record keeps.
    """
    out: dict = {"raw": text or "", "verdict_source": "none"}
    text = (text or "").strip()
    data = None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict):
        for key, value in data.items():
            field = _norm_key(str(key))
            if field in LIST_FIELDS:
                out[field] = _listify(value)
            elif field in TEXT_FIELDS:
                out[field] = str(value).strip()
    else:
        current: str | None = None
        for line in text.splitlines():
            m = _KEYED.match(line)
            field = _norm_key(m.group(1)) if m else None
            if field:
                current = field
                out[field] = (out.get(field, "") + "\n" + m.group(2)).strip() if field in out else m.group(2).strip()
            elif current and line.strip():
                out[current] = (out[current] + "\n" + line.strip()).strip()
        for field in LIST_FIELDS:
            if field in out:
                out[field] = _listify(out[field])
    if "verdict" in out:
        word = re.findall(r"[A-Za-z]+", str(out["verdict"]).lower())
        verdict = next((VERDICTS[w] for w in word if w in VERDICTS), "")
        if verdict:
            out["verdict"] = verdict
            out["verdict_source"] = "keyed"
        else:
            del out["verdict"]
    if "verdict" not in out:
        words = re.findall(r"[A-Za-z]+", text.lower())
        inferred = next((VERDICTS[w] for w in words if w in VERDICTS and VERDICTS[w] in ("pass", "fail")), "")
        if inferred:
            out["verdict"] = inferred
            out["verdict_source"] = "inferred"
    return out
