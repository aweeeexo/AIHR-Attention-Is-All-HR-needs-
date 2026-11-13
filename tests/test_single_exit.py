"""Принцип 4 (D10): единственная точка выхода к LLM — src/aihr/llm/client.py."""

import re

from tests.conftest import REPO_ROOT

SRC = REPO_ROOT / "src" / "aihr"
NETWORK = re.compile(
    r"^\s*(?:import|from)\s+(?:openai|httpx|requests|urllib\.request|aiohttp|http\.client)\b"
    r"|\b(?:httpx|requests)\.(?:get|post|put|request|Client|AsyncClient)\b",
    re.MULTILINE,
)


def test_only_llm_client_talks_to_network() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel == "llm/client.py":
            continue
        if NETWORK.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, offenders
