"""The M6 exit property: graph verdicts agree with the emitted tool's.

``check: emit`` compiles a record to a CI tool, and the unified checker
still answers in-process wherever the graph can see the rule. Two
checkers, one rule — so wherever both exist they must agree, in both
directions, or one of them is lying. This suite runs **the real
lint-imports** over a generated config for the first time in the
project's history (deferred at M8 because no target toolchain was
installed; import-linter is a dev dependency since V2.M6).

The first real execution immediately found an emitter bug the
shape-only tests could not: the ``except`` cross-product emits ignore
pairs that never occur as imports, and import-linter treats an
unmatched ignore as an error by default — a clean repo exited 1. The
regression lives here (`test_unmatched_ignore_pairs_do_not_fail`).
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from hobbes.extract import extract_repo
from hobbes.invariants.compile import _emit_import_linter
from hobbes.invariants.schema import Invariant
from hobbes.invariants.verdict import FAIL, PASS, judge

pytestmark = pytest.mark.skipif(
    shutil.which("lint-imports") is None,
    reason="import-linter not installed (dev dependency)",
)


def record(**overrides) -> Invariant:
    fields = {
        "id": "I-1",
        "statement": "Only the parser touches json.",
        "scope": ".",
        "status": "confirmed",
        "check": "emit",
        "target": "import-linter",
        "rule": {
            "kind": "forbidden-import",
            "importers": ["*"],
            "except": ["agreementapp.parser"],
            # A stdlib target, so the fixture needs nothing installed —
            # and since ADR-038 the graph sees stdlib imports too.
            "imported": ["ext:json"],
        },
        "guarded_by": [],
        "source": "synthetic",
    }
    fields.update(overrides)
    return Invariant(**fields)


def write_fixture(root: Path, core_body: str) -> None:
    pkg = root / "agreementapp"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "parser.py").write_text(
        "import json\n\n\ndef parse(text):\n    return json.loads(text)\n"
    )
    (pkg / "core.py").write_text(textwrap.dedent(core_body))


def lint(root: Path, ini: str) -> int:
    config = root / "generated.ini"
    config.write_text(ini)
    # cwd puts agreementapp on the tool's path, the way a CI job would
    # run it from the repo root.
    proc = subprocess.run(
        ["lint-imports", "--config", str(config)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode


class TestAgreement:
    def test_a_violation_fails_both_judges(self, tmp_path):
        write_fixture(
            tmp_path,
            "import json\n\n\ndef run():\n    return json.dumps({})\n",
        )
        extraction = extract_repo(tmp_path)
        inv = record()

        verdict = judge(inv, extraction.graph)
        assert verdict.result == FAIL
        assert verdict.violations[0].importer == "agreementapp.core"

        assert lint(tmp_path, _emit_import_linter([inv], extraction.graph)) == 1

    def test_a_clean_tree_passes_both_judges(self, tmp_path):
        write_fixture(tmp_path, "def run():\n    return {}\n")
        extraction = extract_repo(tmp_path)
        inv = record()

        assert judge(inv, extraction.graph).result == PASS
        assert lint(tmp_path, _emit_import_linter([inv], extraction.graph)) == 0

    def test_unmatched_ignore_pairs_do_not_fail(self, tmp_path):
        # The bug the first real execution found: `except` entries that
        # never import the forbidden module emit ignore pairs with no
        # matching import, and import-linter's default treats that as an
        # error — a clean repo exited 1 while the graph said pass.
        write_fixture(tmp_path, "def run():\n    return {}\n")
        extraction = extract_repo(tmp_path)
        inv = record(
            rule={
                "kind": "forbidden-import",
                "importers": ["*"],
                # core never imports json in this variant, so its ignore
                # pair is unmatched by construction.
                "except": ["agreementapp.parser", "agreementapp.core"],
                "imported": ["ext:json"],
            }
        )

        assert judge(inv, extraction.graph).result == PASS
        ini = _emit_import_linter([inv], extraction.graph)
        assert "unmatched_ignore_imports_alerting = warn" in ini
        assert lint(tmp_path, ini) == 0
