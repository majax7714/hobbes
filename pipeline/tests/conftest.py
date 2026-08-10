"""Shared fixtures: a fake hobbes-policy binary for hermetic CLI tests.

The real Go binary is exercised by its own test suite (go/cmd/hobbes-policy);
here we only test the Python side of the ADR-003 contract, so a shell script
that emits canned JSON and a chosen exit code stands in for it.
"""

import json
import os
import stat

import pytest

FAKE_RESOLUTION = {
    "command": "git push --force origin main",
    "decision": "deny",
    "default": False,
    "rule": {
        "pattern": "git push --force*",
        "decision": "deny",
        "reason": "force-push forbidden",
        "scope": "box",
        "source": "/home/x/.hobbes/box.policy",
    },
    "matches": [],
}


@pytest.fixture
def fake_policy_bin(tmp_path):
    """Create a fake hobbes-policy script.

    Returns a factory: ``fake_policy_bin(exit_code, payload=None)`` writes a
    script that prints *payload* as JSON (arguments it received under
    ``"argv"`` when payload is None) and exits with *exit_code*.
    """

    def make(exit_code: int, payload: dict | None = None) -> str:
        path = tmp_path / "hobbes-policy"
        if payload is None:
            body = (
                "#!/bin/sh\n"
                'printf \'{"argv": "%s"}\\n\' "$*"\n'
                f"exit {exit_code}\n"
            )
        else:
            body = f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(payload)}\nEOF\nexit {exit_code}\n"
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    return make


@pytest.fixture
def no_real_binary(monkeypatch):
    """Guarantee binary discovery fails: clear the env var and empty PATH."""
    monkeypatch.delenv("HOBBES_POLICY_BIN", raising=False)
    monkeypatch.setenv("PATH", os.devnull)
