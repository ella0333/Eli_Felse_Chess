#!/usr/bin/env python3
"""Chess module setup - interactive wizard.

Matches the style of the base's `elifelse init` wizard. There is no API key
to enter, so this asks which decisions you want to make yourself, writes them
to the base's config.yaml, and downloads Stockfish if it is missing.
"""

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
BASE_ROOT = MODULE_ROOT.parent.parent.parent  # data/modules/chess -> base root
BASE_CONFIG = BASE_ROOT / "config.yaml"

sys.path.insert(0, str(MODULE_ROOT))

from src.chess_game.stockfish import find_stockfish, get_stockfish  # noqa: E402

DIFFICULTIES = [
    "beginner", "easy", "casual", "intermediate", "advanced", "hard", "expert", "master",
]
COLORS = ["white", "black"]


# ~~~ IO helpers (mirrors base WizardIO) ~~~

def say(msg: str) -> None:
    print(f"[system] {msg}")


def yesno(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} ({hint}): ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        say("please answer y or n")


def integer(prompt: str, default: int, minimum: int = 0) -> int:
    while True:
        answer = input(f"{prompt} ({default}): ").strip()
        if not answer:
            return default
        if answer.isdigit() and int(answer) >= minimum:
            return int(answer)
        say(f"please enter a whole number >= {minimum}")


def choice(prompt: str, options: list[str], default: str) -> str:
    say(prompt)
    for i, option in enumerate(options, 1):
        say(f"  {i}. {option}")
    default_num = options.index(default) + 1
    while True:
        answer = input(f"choose 1-{len(options)} ({default_num}): ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        say(f"please enter a number from 1 to {len(options)}")


# ~~~ config ~~~

def print_config(section: dict) -> None:
    """The block, indented ready to paste under `activities:`."""
    try:
        import yaml
    except ImportError:
        say("install PyYAML to see the config block")
        return
    dumped = yaml.dump(
        {"activities": {"chess": section}}, default_flow_style=False, sort_keys=False
    )
    for line in dumped.rstrip().splitlines():
        say(f"  {line}")


def write_base_config(section: dict) -> bool:
    """Merge the section into the base's config.yaml."""
    if not BASE_CONFIG.exists():
        say("no config.yaml next to the base, so nothing was written")
        return False
    try:
        import yaml
    except ImportError:
        say("PyYAML is not installed, so config.yaml was left alone")
        return False

    try:
        data = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8")) or {}
        existing = data.setdefault("activities", {}).setdefault("chess", {})
        existing.update(section)
        BASE_CONFIG.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    except (OSError, yaml.YAMLError) as e:
        say(f"could not update config.yaml: {e}")
        return False
    say("")
    say(f"updated activities.chess in {BASE_CONFIG}")
    say("(the YAML round-trip drops the comments the base ships with)")
    return True


# ~~~ main wizard ~~~

def main():
    section: dict[str, object] = {"difficulty": "agent", "color": "agent"}

    if not yesno("Let the agent set up its own games?", default=True):
        section["difficulty"] = choice("Difficulty:", DIFFICULTIES, default="beginner")
        section["color"] = choice("Color:", COLORS, default="white")

    say("")
    section["daily_limit"] = integer("Games per day (0 for no cap)", default=0)

    say("")
    found = find_stockfish()
    if found:
        say(f"Stockfish found: {found}")
    else:
        get_stockfish()

    written = write_base_config(section)

    say("")
    if written:
        say("for reference, this is what went in:")
    else:
        say("add this to your config.yaml:")
    print_config(section)

    say("")
    say("Done. Start the agent with:  elifelse run")
    say("'Chess' will appear under 'Play a Board or Card Game'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(1)
