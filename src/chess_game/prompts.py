"""What the agent reads: the game guidance, and the setup menu."""

from __future__ import annotations

from .engine import DIFFICULTIES


def table_guidance(difficulty_name: str, llm_color: str) -> str:
    """The block appended to the agent's own identity prompt while it plays."""
    return f"""You are playing Chess against a Stockfish engine at {difficulty_name} difficulty. You are playing as {llm_color}.

Each turn you will be presented with a selection of candidate moves to choose from. The moves include descriptions of what they do (captures, checks, development).

Strategy priorities:
- Look for checks and captures first, these are forcing moves
- Develop your pieces early (knights and bishops)
- Control the center with pawns and pieces
- Castle to protect your king
- In the endgame, activate your king and push passed pawns
- Be cautious of trap moves, some options may look appealing but lose material

Important: Some presented moves may be traps (intentionally bad). Use your judgment to distinguish good moves from bad ones based on the descriptions provided.

If you quit mid-game, it counts as a loss (resignation)."""


def difficulty_lines() -> list[str]:
    return [
        f"  {chr(65 + i)}. {d['name']} (~{d['elo']} ELO - {d['desc']})"
        for i, d in enumerate(DIFFICULTIES)
    ]


def setup_prompt(fields: list[str]) -> str:
    """The setup menu, minus anything config already fixed."""
    lines = ["Set up your chess game against Stockfish."]
    if "difficulty" in fields:
        lines += ["", "Difficulty:", *difficulty_lines()]
    if "color" in fields:
        lines += ["", "Color:", "  A. White (move first)", "  B. Black"]
    return "\n".join(lines)
