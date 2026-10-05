"""Printing the game to the terminal.

A game is dozens of decisions the framework makes no noise about, so the
module prints its own. The shape follows the rest of the family: a ruled
header, indented lines for the board talking, and the agent's own voice
left unindented so it stands out.
"""

from __future__ import annotations

import sys

RULE_WIDTH = 60


def _write(line: str) -> None:
    """Print ASCII-safe, the way the base's print_system does."""
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding))


def print_header(text: str) -> None:
    _write("\n" + "=" * RULE_WIDTH + f"\n  {text}\n" + "=" * RULE_WIDTH)


def print_table(text: str) -> None:
    """The board talking: one indented line per event."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            _write(f"  {stripped}")


def print_thinking(text: str) -> None:
    """The agent's reasoning, matching how the base prints it at a menu."""
    if text:
        _write(f"\nThinking: {text}")


def print_action(text: str) -> None:
    if text:
        _write(f"  {text}")


def print_menu(text: str) -> None:
    """What the model is shown, unindented, the way the base prints a menu."""
    _write(f"\n{text}")


def print_choice(text: str) -> None:
    """The model's pick, matching the base's `Choice:` line."""
    if text:
        _write(f"Choice: {text}")
