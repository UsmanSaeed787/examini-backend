"""Instruction assets loader. Instructions are versioned data files, kept
out of agent code so they can evolve without code review of logic."""
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache
def load_instructions(agent_key: str) -> str:
    path = _DIR / f"{agent_key}.md"
    return path.read_text(encoding="utf-8").strip()
