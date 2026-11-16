import json
import os

import pytest

PLAIN = (dict, list, str, int, float, bool, type(None))


def assert_plain(obj, path="result"):
    """Worker output must be plain JSON types only (no numpy / pandas / NaN), see AGENT_GUARDRAILS.md."""
    assert type(obj) in PLAIN, f"{path}: {type(obj).__name__}"
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert type(k) is str, f"{path}: key {k!r}"
            assert_plain(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_plain(v, f"{path}[{i}]")
    if path == "result":
        json.dumps(obj, allow_nan=False)
    return obj


@pytest.fixture(autouse=True)
def router_llm_off(monkeypatch):
    """Unit tests never call Bedrock for routing: unclear messages go to the pipeline (method "default").
    Live tests (RUN_LIVE=1) keep the real router."""
    if os.getenv("RUN_LIVE") != "1":
        monkeypatch.setenv("ROUTER_LLM", "0")


@pytest.fixture(autouse=True)
def _no_real_guardrail(monkeypatch):
    """Unit tests never call the real Bedrock Guardrail, even when .env sets GUARDRAIL_ID (pipeline.py loads .env).
    Tests that need it set their own fake ID; live tests (RUN_LIVE=1) keep the real one."""
    if os.getenv("RUN_LIVE") != "1":
        monkeypatch.delenv("GUARDRAIL_ID", raising=False)
