# /// script
# requires-python = ">=3.12"
# dependencies = ["modal>=1.1"]
# ///
"""Serve one rung of the model ladder on Modal with vLLM (ADR-057).

    MODEL=Qwen/Qwen2.5-Coder-7B-Instruct uv run pipeline/scripts/modal_vllm.py deploy
    uv run pipeline/scripts/modal_vllm.py url        # print the endpoint root

One app per rung (``hobbes-llm-<slug>``), an OpenAI-compatible server
at ``/v1`` behind a bearer token read from the Modal secret
``hobbes-llm-key`` (``HOBBES_LLM_API_KEY``) — the same variable the
agent loop and ``hobbes bench`` read on the host, so one value serves
both ends. Weights are cached in a Modal volume across cold starts.
The GPU per rung is pinned in ``RUNGS``; a model outside the table is
refused rather than guessed at. Scales to zero when idle.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import modal

#: The ladder, rung → (GPU, vLLM flags). Pinned; a rung is added by
#: editing this table, never by a flag.
RUNGS: dict[str, dict] = {
    "Qwen/Qwen2.5-Coder-7B-Instruct": {
        "gpu": "A10G", "max_model_len": 32768, "tool_parser": "hermes",
    },
    "Qwen/Qwen2.5-Coder-32B-Instruct": {
        "gpu": "A100-80GB", "max_model_len": 32768, "tool_parser": "hermes",
    },
    # The next rung above 32B is not pinned yet: Qwen3-Coder-30B-A3B
    # (MoE, 3B active) is the family's candidate and needs a vLLM with
    # its parser; record the choice in ADR-057 when it is taken.
}

MODEL = os.environ.get("MODEL", "Qwen/Qwen2.5-Coder-7B-Instruct")
if MODEL not in RUNGS:
    sys.exit(f"modal_vllm: {MODEL!r} is not a pinned rung; known: {', '.join(RUNGS)}")
RUNG = RUNGS[MODEL]
SLUG = re.sub(r"[^a-z0-9]+", "-", MODEL.lower()).strip("-")
APP = f"hobbes-llm-{SLUG}"
PORT = 8000
VLLM = "0.10.1.1"

image = (
    modal.Image.debian_slim(python_version="3.12")
    # transformers 5 removed tokenizer attributes this vLLM still reads;
    # pin the major (found on the first cold start, ADR-057).
    .pip_install(f"vllm=={VLLM}", "transformers>=4.55,<5", "huggingface_hub[hf_transfer]>=0.34")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_USE_V1": "1"})
)
weights = modal.Volume.from_name("hobbes-hf-cache", create_if_missing=True)
app = modal.App(APP)


@app.function(
    image=image,
    gpu=RUNG["gpu"],
    volumes={"/root/.cache/huggingface": weights},
    secrets=[modal.Secret.from_name("hobbes-llm-key")],
    scaledown_window=600,
    timeout=60 * 60,
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=PORT, startup_timeout=20 * 60)
def serve():
    """vLLM's OpenAI-compatible server for this rung."""
    cmd = [
        "vllm", "serve", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--served-model-name", MODEL,
        "--max-model-len", str(RUNG["max_model_len"]),
        "--enable-auto-tool-choice", "--tool-call-parser", RUNG["tool_parser"],
        "--api-key", os.environ["HOBBES_LLM_API_KEY"],
        "--gpu-memory-utilization", "0.92",
    ]
    subprocess.Popen(cmd)


def main(argv: list[str]) -> int:
    if argv[1:] == ["url"]:
        fn = modal.Function.from_name(APP, "serve")
        print(fn.get_web_url().rstrip("/") + "/v1")
        return 0
    if argv[1:] == ["deploy"]:
        os.execvp("modal", ["modal", "deploy", "--name", APP, __file__])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
