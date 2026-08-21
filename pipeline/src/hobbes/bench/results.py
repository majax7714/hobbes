"""Records and the report (ADR-055).

One record per (instance, arm, model) in ``records.jsonl`` under the
run directory — instance facts (repo, created_at, the depth proxy),
the arm's outcome and patch shape, the meter, the verdict once the
evaluator has spoken, and for the harness arm the plan and run
summaries (the error stream). The report lays the records against
the three preregistered hypotheses and **computes, never interprets**:
it prints the rates, slopes, and per-solved costs with their sample
sizes and every unobserved term named, and leaves the reading to the
results section of ``docs/benchmark-hypotheses.md``.

Records with no verdict yet are excluded from every rate and counted
as such — a rate over unjudged patches would be a rate of "produced
something", which is not what any hypothesis asks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hobbes.bench.accounting import Usage
from hobbes.bench.arms import ArmResult
from hobbes.bench.instances import DEPTH_BUCKETS, Instance

RECORDS = "records.jsonl"


@dataclass
class Record:
    instance_id: str
    repo: str
    created_at: str
    depth: int
    depth_bucket: str
    arm: str
    model: str
    outcome: str
    patch_bytes: int
    patch_files: list[str]
    usage: dict
    verdict: str | None = None
    error: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def solved(self) -> bool | None:
        return None if self.verdict in (None, "unjudged") else self.verdict == "resolved"

    def to_dict(self) -> dict:
        return asdict(self)


def make_record(instance: Instance, result: ArmResult) -> Record:
    return Record(
        instance_id=instance.instance_id, repo=instance.repo, created_at=instance.created_at,
        depth=instance.depth, depth_bucket=instance.depth_bucket,
        arm=result.arm, model=result.model, outcome=result.outcome,
        patch_bytes=len(result.patch.encode()), patch_files=result.patch_files,
        usage=result.usage.to_dict(), error=result.error, detail=result.detail,
    )


def append(run_dir: Path, record: Record) -> None:
    path = Path(run_dir) / RECORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")


def load(run_dir: Path) -> list[Record]:
    path = Path(run_dir) / RECORDS
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(Record(**json.loads(line)))
    return out


def rewrite(run_dir: Path, records: list[Record]) -> None:
    path = Path(run_dir) / RECORDS
    path.write_text("".join(json.dumps(r.to_dict(), sort_keys=True) + "\n" for r in records))


def _rate(records: list[Record]) -> dict:
    judged = [r for r in records if r.solved is not None]
    solved = sum(1 for r in judged if r.solved)
    return {
        "n": len(records), "judged": len(judged), "solved": solved,
        "rate": round(solved / len(judged), 4) if judged else None,
    }


def _per_solved(records: list[Record]) -> dict:
    """H3's quantity: mean meter per *solved* instance, over the solved
    records whose term was observed; the unobserved count is stated."""
    solved = [r for r in records if r.solved]
    out: dict = {"solved": len(solved)}
    for term, key in (("tokens", "total_tokens"), ("cost_usd", "cost_usd"), ("wall_seconds", "wall_seconds")):
        values = [r.usage.get(key) for r in solved]
        seen = [v for v in values if v is not None]
        out[term] = {
            "mean": round(sum(seen) / len(seen), 3) if seen else None,
            "observed": len(seen), "unobserved": len(values) - len(seen),
        }
    return out


def report(records: list[Record]) -> dict:
    """The numbers the hypotheses are decided by, by arm and model."""
    groups: dict[tuple[str, str], list[Record]] = {}
    for r in records:
        groups.setdefault((r.arm, r.model), []).append(r)
    models = sorted({m for _, m in groups})

    h1 = {}
    for model in models:
        pure = _rate(groups.get(("pure", model), []))
        harness = _rate(groups.get(("harness", model), []))
        h1[model] = {"pure": pure, "harness": harness,
                     "delta": round(harness["rate"] - pure["rate"], 4)
                     if pure["rate"] is not None and harness["rate"] is not None else None}
    pure_rates = {m: h1[m]["pure"]["rate"] for m in models if h1[m]["pure"]["rate"] is not None}
    best_pure = max(pure_rates, key=pure_rates.get) if pure_rates else None
    for model in models:
        gap = None
        if best_pure and model != best_pure and h1[model]["harness"]["rate"] is not None \
                and h1[model]["pure"]["rate"] is not None:
            span = pure_rates[best_pure] - h1[model]["pure"]["rate"]
            gap = round((h1[model]["harness"]["rate"] - h1[model]["pure"]["rate"]) / span, 4) if span > 0 else None
        h1[model]["gap_closed_vs"] = best_pure
        h1[model]["gap_closed"] = gap

    h2 = {}
    for (arm, model), rs in sorted(groups.items()):
        buckets = {name: _rate([r for r in rs if r.depth_bucket == name]) for name, _, _ in DEPTH_BUCKETS}
        first, last = buckets[DEPTH_BUCKETS[0][0]]["rate"], buckets[DEPTH_BUCKETS[-1][0]]["rate"]
        h2[f"{arm}/{model}"] = {"buckets": buckets,
                                "slope": round(last - first, 4) if first is not None and last is not None else None}

    h3 = {f"{arm}/{model}": _per_solved(rs) for (arm, model), rs in sorted(groups.items())}

    outcomes: dict[str, dict[str, int]] = {}
    for (arm, model), rs in groups.items():
        counts = outcomes.setdefault(f"{arm}/{model}", {})
        for r in rs:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
    unjudged = sum(1 for r in records if r.solved is None)
    return {
        "records": len(records), "unjudged": unjudged, "models": models,
        "H1": h1, "H2": h2, "H3": h3, "outcomes": outcomes,
        "notes": [
            "rates are over judged records only; unjudged records are counted, not rated",
            "depth is the gold-patch file count — a proxy (H2)",
            "H3 means are per solved instance over records whose term was observed; "
            "unobserved counts are stated, never imputed",
            "contamination is bounded by the selection's cutoff, not proven (C-39)",
            "the verdict is the pinned swebench evaluator's — its limits are ours (P9)",
        ],
    }


def _pct(rate: float | None) -> str:
    return "—" if rate is None else f"{100 * rate:.1f}%"


def format_report(doc: dict) -> str:
    lines = [f"benchmark report: {doc['records']} records, {doc['unjudged']} unjudged"]
    lines.append("")
    lines.append("H1 — solve rate, pure vs harnessed, same model")
    lines.append("  model | pure (solved/judged) | harness (solved/judged) | delta | gap closed vs best pure")
    for model, row in doc["H1"].items():
        p, h = row["pure"], row["harness"]
        gap = "—" if row["gap_closed"] is None else f"{100 * row['gap_closed']:.0f}% of {row['gap_closed_vs']}"
        delta = "—" if row["delta"] is None else f"{100 * row['delta']:+.1f} pts"
        lines.append(f"  {model} | {_pct(p['rate'])} ({p['solved']}/{p['judged']}) | "
                     f"{_pct(h['rate'])} ({h['solved']}/{h['judged']}) | {delta} | {gap}")
    lines.append("")
    lines.append("H2 — solve rate by depth (gold-patch files, a proxy); slope = last bucket − first")
    for key, row in doc["H2"].items():
        cells = ", ".join(f"{b} {_pct(v['rate'])} ({v['solved']}/{v['judged']})" for b, v in row["buckets"].items())
        slope = "—" if row["slope"] is None else f"{100 * row['slope']:+.1f} pts"
        lines.append(f"  {key}: {cells}; slope {slope}")
    lines.append("")
    lines.append("H3 — per solved instance (means over observed terms)")
    for key, row in doc["H3"].items():
        parts = []
        for term in ("tokens", "cost_usd", "wall_seconds"):
            t = row[term]
            value = "unobserved" if t["mean"] is None else f"{t['mean']:g}"
            miss = f" ({t['unobserved']} unobserved)" if t["unobserved"] else ""
            parts.append(f"{term} {value}{miss}")
        lines.append(f"  {key}: solved {row['solved']}; " + "; ".join(parts))
    lines.append("")
    lines.append("outcomes (the error stream)")
    for key, counts in doc["outcomes"].items():
        lines.append(f"  {key}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    lines.append("")
    lines += [f"note: {n}" for n in doc["notes"]]
    return "\n".join(lines)
