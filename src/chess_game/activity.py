"""Chess Activity - the Eli Felse module interface.

Registers as a drop-in activity. Provides:
- A menu entry under the shared "Play a Board or Card Game" line
- A setup menu for difficulty and color
- A move-by-move loop where Stockfish proposes the candidate moves
- A save you can resume later, and a live board in the base's dashboard

Every setting in the setup menu can be fixed in config.yaml instead, which
removes that question. Left alone, the agent decides all of it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .display import print_choice, print_header, print_menu, print_table, print_thinking
from .engine import COLORS, DIFFICULTIES, DIFFICULTY_KEYS, ChessGame
from .prompts import setup_prompt, table_guidance

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext
    from elifelse.persona import Persona

try:
    from elifelse.activities.base import Activity
except ImportError:
    # Standalone mode - provide a stub
    class Activity:
        key = ""
        menu_label = ""
        menu_group = ""
        requires = []
        requires_base = ""
        schemas = {}
        isolate_context = False
        memory_mode = "standard"
        memory_rules = ""
        survey = None
        dashboard_view = ""
        module_dir = None

        def get_menu_label(self, ctx): return self.menu_label
        def get_status(self, ctx): return ""
        def get_prompt(self, persona): return ""
        def dashboard_state(self, ctx): return None
        def available(self, ctx): return True
        async def startup(self, ctx): pass
        async def run(self, ctx): pass

try:
    from elifelse.textutils import print_system
except ImportError:
    def print_system(text: str) -> None:
        print(f"[system] {text}")


# Config defaults (activities.chess in config.yaml). "agent" means the agent is
# asked during setup; anything else fixes the answer and drops the question.
AGENT = "agent"
DEFAULT_DAILY_LIMIT = 0          # games per day, 0 = no cap


# ~~~ schemas ~~~
def build_setup_schema(fields: list[str]) -> dict[str, Any]:
    """One call for the whole setup, minus anything config already fixed."""
    properties: dict[str, Any] = {"thinking": {"type": "string"}}
    if "difficulty" in fields:
        properties["difficulty"] = {
            "type": "string",
            "enum": [chr(65 + i) for i in range(len(DIFFICULTIES))],
        }
    if "color" in fields:
        properties["color"] = {"type": "string", "enum": ["A", "B"]}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def build_move_schema(num_options: int) -> dict[str, Any]:
    """The per-turn move menu, lettered like every other menu."""
    return {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "choice": {
                "type": "string",
                "enum": [chr(65 + i) for i in range(num_options)],
            },
            "return_to_menu": {"type": "boolean"},
        },
        "required": ["thinking", "choice", "return_to_menu"],
        "additionalProperties": False,
    }


class ChessActivity(Activity):
    key = "chess"
    menu_label = "Chess"
    menu_group = "Play a Board or Card Game"
    requires = []
    requires_base = ">=0.5,<1"
    isolate_context = True
    memory_mode = "game_batch"
    survey = "simple"
    dashboard_view = "dashboard/index.html"
    memory_rules = (
        "Extract how the game went as chess, not as a list of moves: the difficulty "
        "and color, the moments that turned the game, traps the agent fell for or "
        "avoided, and how it felt about winning or losing. Skip routine developing "
        "moves and the move-by-move notation."
    )

    def __init__(self) -> None:
        self._game: ChessGame | None = None

    # ~~~ menu presence ~~~
    def get_status(self, ctx: ActivityContext) -> str:
        if self._save_path(ctx).exists():
            return "saved game waiting"
        return super().get_status(ctx)

    def available(self, ctx: ActivityContext) -> bool:
        limit = int(ctx.config.get("daily_limit", DEFAULT_DAILY_LIMIT))
        if limit <= 0:
            return True
        return ctx.limits.remaining(self.key, limit) > 0

    def get_prompt(self, persona: Persona) -> str:
        """Empty: run() sets the full prompt once the game is known."""
        return ""

    def dashboard_state(self, ctx: ActivityContext) -> dict[str, Any] | None:
        return self._game.state.to_dict() if self._game else None

    # ~~~ config ~~~
    def _setting(self, ctx: ActivityContext, name: str, allowed: list[str]) -> str | None:
        """A fixed value from config.yaml, or None when the agent decides."""
        value = str(ctx.config.get(name, AGENT)).strip().lower()
        return value if value in allowed else None

    def _save_path(self, ctx: ActivityContext) -> Path:
        return ctx.data_dir / "chess_save.json"

    def _pace(self, ctx: ActivityContext) -> bool:
        """Pausing before Stockfish moves is for watching, so tests turn it off."""
        return bool(ctx.config.get("pace_table", True))

    # ~~~ the activity ~~~
    async def run(self, ctx: ActivityContext) -> str:
        save_path = self._save_path(ctx)
        resumed = False

        if save_path.exists():
            saved = self._read_save(save_path)
            if saved:
                choice = await ctx.choose(
                    f"You have a saved Chess game.\n"
                    f"Saved: {saved.get('saved_at', '?')}, {saved.get('summary', '')}",
                    options=["resume", "new"],
                    labels=["Resume saved game", "Start a new game (deletes the save)"],
                )
                if choice == "resume":
                    print_system("Restoring saved chess game...")
                    self._game = await asyncio.to_thread(
                        ChessGame.restore, saved, pace=self._pace(ctx)
                    )
                    resumed = True
                save_path.unlink()

        if self._game is None:
            self._game = await self._new_game(ctx)

        game = self._game
        try:
            return await self._play(ctx, game, resumed)
        finally:
            await asyncio.to_thread(game.shutdown)
            self._game = None

    async def _new_game(self, ctx: ActivityContext) -> ChessGame:
        """Ask for whatever config left open, then start Stockfish."""
        difficulty = self._setting(ctx, "difficulty", DIFFICULTY_KEYS)
        color = self._setting(ctx, "color", COLORS)

        fields = []
        if difficulty is None:
            fields.append("difficulty")
        if color is None:
            fields.append("color")

        if fields:
            print_header("CHESS SETUP")
            prompt = setup_prompt(fields)
            print_menu(prompt)
            answer = await ctx.generate(prompt, build_setup_schema(fields))
            print_thinking(answer.get("thinking", ""))
            if "difficulty" in fields:
                difficulty = self._pick(answer.get("difficulty"), DIFFICULTY_KEYS)
            if "color" in fields:
                color = self._pick(answer.get("color"), COLORS)
            diff_idx = DIFFICULTY_KEYS.index(difficulty)
            print_choice(f"{DIFFICULTIES[diff_idx]['name']}, {color.title()}")

        diff_idx = DIFFICULTY_KEYS.index(difficulty)

        game = ChessGame(diff_idx, color, agent_name=ctx.persona.name, pace=self._pace(ctx))
        await asyncio.to_thread(game.start)
        return game

    async def _play(self, ctx: ActivityContext, game: ChessGame, resumed: bool) -> str:
        save_path = self._save_path(ctx)
        diff_name = game.difficulty["name"]
        ctx.app.provider.set_system_prompt("\n\n".join([
            ctx.app.base_prompt(),
            table_guidance(diff_name, game.llm_color_name.lower()),
        ]))
        ctx.set_status("Playing chess", {"game": "Chess", "difficulty": diff_name})
        print_header(
            f"PLAYING CHESS ({diff_name.upper()}) AS {game.llm_color_name.upper()}"
            f"{' - RESUMED' if resumed else ''}"
        )
        opening = game.get_last_opponent_move_text()
        if opening:
            print_table(f"Opponent: {opening}")

        game_start_time = datetime.now()
        turns = 0
        while not game.is_game_over():
            turn = await asyncio.to_thread(game.get_turn_state)
            if turn is None:
                break
            turns += 1

            print_header(f"MOVE {turn['move_number']} - {ctx.persona.name} ({turn['turn']})")
            print_menu(turn["menu_text"])
            answer = await ctx.generate(turn["prompt"], build_move_schema(turn["options"]))
            thinking = answer.get("thinking", "")
            print_thinking(thinking)

            if answer.get("return_to_menu"):
                print_choice("return to menu")
                left = await self._quit_menu(ctx, game, save_path, turns, game_start_time)
                if left:
                    return left
                continue

            before = game.get_last_opponent_move_text()
            played = await asyncio.to_thread(game.apply_choice, answer.get("choice", ""), thinking)
            print_choice(f"{played['choice_letter']} ({played['san']})")

            ctx.remember_game("user", game.get_last_opponent_move_text() or "Your move.")
            ctx.remember_game("assistant", f"{thinking}\nMove: {played['san']}")

            opponent = game.get_last_opponent_move_text()
            if opponent and opponent != before:
                print_table(f"Opponent: {opponent}")

        result = game.get_result()
        display = f"{result['result_text']} ({result['reason']})"
        if save_path.exists():
            save_path.unlink()
        self._record(ctx, result)
        print_header(f"CHESS RESULT: {display}")
        ctx.remember_game("user", f"[Game result] {result['summary']}")
        return f"Finished playing Chess against Stockfish (AI engine). {display}"

    async def _quit_menu(self, ctx: ActivityContext, game: ChessGame, save_path: Path,
                         turns: int, started: datetime) -> str:
        """A mid-game exit. Returns the closing note, or '' to keep playing."""
        choice = await ctx.choose(
            "You want to leave Chess. What would you like to do?",
            options=["quit", "save", "cancel"],
            labels=[
                "Quit game (counts as a loss)",
                "Save game and quit (you can resume later)",
                "Cancel, keep playing",
            ],
        )
        if choice == "cancel":
            print_system("Continuing the game.")
            return ""
        if choice == "save":
            data = game.save_data()
            elapsed_min = int((datetime.now() - started).total_seconds() // 60)
            data["saved_at"] = datetime.now().strftime("%m/%d/%Y %I:%M %p")
            data["summary"] = f"Turn {turns}, {elapsed_min}m played"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            ctx.app.stats.increment("chess.games_saved")
            print_system("Game saved. You can resume next time.")
            return "Saved the chess game to finish later."

        game.record_loss()
        result = game.get_result()
        if save_path.exists():
            save_path.unlink()
        self._record(ctx, result)
        print_system(f"{ctx.persona.name} quit the game, automatic loss recorded.")
        return f"Quit the chess game against Stockfish. {result['result_text']} (counts as a loss)"

    # ~~~ bookkeeping ~~~
    def _record(self, ctx: ActivityContext, result: dict[str, Any]) -> None:
        stats = ctx.app.stats
        stats.increment("chess.games_played")
        stats.increment({"W": "chess.wins", "L": "chess.losses"}.get(result["result"], "chess.draws"))
        limit = int(ctx.config.get("daily_limit", DEFAULT_DAILY_LIMIT))
        if limit > 0:
            ctx.limits.use(self.key)

    # ~~~ small helpers ~~~
    @staticmethod
    def _pick(letter: Any, keys: list[str]) -> str:
        index = ord(str(letter).upper()[0]) - 65 if letter else -1
        return keys[index] if 0 <= index < len(keys) else keys[0]

    @staticmethod
    def _read_save(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print_system(f"could not read the chess save: {e}")
            path.unlink(missing_ok=True)
            return None
