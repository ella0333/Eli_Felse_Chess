"""The chess game: Stockfish as the opponent, and Stockfish as the move proposer.

The agent never writes a move. Each turn Stockfish analyses the position and
offers a short lettered list: its best few moves, plus (at most difficulties)
some of the worst-ranked moves mixed in as traps. Every option is described in
plain words, so picking well is a matter of reading, not calculating.

Everything here is synchronous. The engine calls block, so the activity runs
them in a worker thread.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

import chess
import chess.engine
import chess.svg

from .stockfish import get_stockfish

# ~~~ difficulty ~~~
# Stockfish move proposer: (good_count, bad_count) per difficulty.
# Good = top Stockfish moves, Bad = worst-ranked moves (traps).
CANDIDATE_CONFIG = {
    "Beginner":     (3, 1),  # 4 total, 25% bad
    "Easy":         (3, 1),  # 4 total, 25% bad
    "Casual":       (3, 1),  # 4 total, 25% bad
    "Intermediate": (3, 2),  # 5 total, 40% bad
    "Advanced":     (3, 2),  # 5 total, 40% bad
    "Hard":         (3, 3),  # 6 total, 50% bad
    "Expert":       (3, 3),  # 6 total, 50% bad
    "Master":       (3, 3),  # 6 total, 50% bad (capped)
}

# `desc` is the menu wording. Stockfish's UCI_Elo floor is 1320, so the three
# levels below it play on Skill Level alone.
DIFFICULTIES = [
    {"name": "Beginner",     "elo": 800,  "skill": 1,  "depth": 1,  "time": 0.01, "desc": "new to chess"},
    {"name": "Easy",         "elo": 1000, "skill": 3,  "depth": 3,  "time": 0.05, "desc": "casual player"},
    {"name": "Casual",       "elo": 1200, "skill": 5,  "depth": 5,  "time": 0.1,  "desc": "knows the basics well"},
    {"name": "Intermediate", "elo": 1500, "skill": 8,  "depth": 8,  "time": 0.2,  "desc": "club player"},
    {"name": "Advanced",     "elo": 1800, "skill": 12, "depth": 12, "time": 0.5,  "desc": "experienced"},
    {"name": "Hard",         "elo": 2000, "skill": 15, "depth": 15, "time": 1.0,  "desc": "strong player"},
    {"name": "Expert",       "elo": 2200, "skill": 18, "depth": 18, "time": 1.5,  "desc": "tournament strength"},
    {"name": "Master",       "elo": 2500, "skill": 20, "depth": 20, "time": 2.0,  "desc": "professional strength"},
]
DIFFICULTY_KEYS = [d["name"].lower() for d in DIFFICULTIES]
COLORS = ["white", "black"]

CHARS_PER_TOKEN = 4  # standard approximation
NARRATIVE_TOKENS = 5000

# Seconds Stockfish waits before replying, so a watched board is followable.
STOCKFISH_PAUSE = 2

PIECE_NAMES = {
    chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop",
    chess.ROOK: "Rook", chess.QUEEN: "Queen", chess.KING: "King",
}

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9,
}

PIECE_SYMBOLS = {
    chess.PAWN: ("♙", "♟"),
    chess.KNIGHT: ("♘", "♞"),
    chess.BISHOP: ("♗", "♝"),
    chess.ROOK: ("♖", "♜"),
    chess.QUEEN: ("♕", "♛"),
}

# ~~~ resigning and drawing ~~~
LONE_KING_MOVES = 3        # resign after this many moves with just a king
HOPELESS_MOVES = 6         # resign after this many hopeless moves
HOPELESS_THRESHOLD = -7    # material deficit to consider hopeless (down a rook+minor)

# Moderate disadvantage: down a full piece worth for a sustained stretch
LOSING_THRESHOLD = -4      # down a minor piece + pawn
LOSING_MOVES = 15          # resign after this many losing moves

# Late-game resignation: tighter thresholds past move 50
LATE_GAME_MOVE = 50        # after this move number, apply stricter rules
LATE_GAME_THRESHOLD = -3   # any clear disadvantage in late game
LATE_GAME_MOVES = 10       # resign after this many late-game losing moves

# Absolute game length cap, a forced draw if the game drags on
MAX_GAME_MOVES = 80        # draw after this many full moves (160 half-moves)

RESIGN_COUNTERS = ("lone_king", "hopeless", "losing", "late_game")


# ~~~ material ~~~
def calc_material(board: chess.Board) -> dict[str, Any]:
    """Material scores and captured pieces for both sides."""
    starting = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}

    white_score = 0
    black_score = 0
    white_captured = []  # pieces white has captured (black pieces missing)
    black_captured = []  # pieces black has captured (white pieces missing)

    for piece_type, value in PIECE_VALUES.items():
        w_count = len(board.pieces(piece_type, chess.WHITE))
        b_count = len(board.pieces(piece_type, chess.BLACK))
        white_score += w_count * value
        black_score += b_count * value

        b_missing = starting[piece_type] - b_count
        for _ in range(max(0, b_missing)):
            white_captured.append(PIECE_SYMBOLS[piece_type][1])

        w_missing = starting[piece_type] - w_count
        for _ in range(max(0, w_missing)):
            black_captured.append(PIECE_SYMBOLS[piece_type][0])

    advantage = white_score - black_score

    return {
        "white_score": white_score,
        "black_score": black_score,
        "advantage": advantage,  # positive = white leads
        "advantage_text": f"+{advantage}" if advantage > 0 else str(advantage),
        "white_captured": white_captured,
        "black_captured": black_captured,
    }


# ~~~ describing moves ~~~
def find_pieces_en_prise_after(board: chess.Board, move: chess.Move) -> list[tuple]:
    """Our pieces the opponent can profitably capture next turn after this move.

    Only flags pieces that become newly capturable (weren't already en prise).
    Returns (piece_name, square_name, piece_value, attacker_name, attacker_value).
    """
    color = board.turn
    opp = not color
    board_after = board.copy()
    board_after.push(move)

    en_prise = []
    for opp_move in board_after.legal_moves:
        if not board_after.is_capture(opp_move):
            continue
        victim = board_after.piece_at(opp_move.to_square)
        if not victim or victim.color != color or victim.piece_type == chess.KING:
            continue
        attacker = board_after.piece_at(opp_move.from_square)
        if not attacker:
            continue

        victim_val = PIECE_VALUES.get(victim.piece_type, 0)
        attacker_val = PIECE_VALUES.get(attacker.piece_type, 0)

        # Only losing trades: the opponent captures something worth more than
        # the attacker, or it's undefended (a free capture).
        is_defended = board_after.is_attacked_by(color, opp_move.to_square)
        if not is_defended or victim_val > attacker_val:
            was_capturable = (
                board.piece_at(opp_move.to_square) is not None
                and board.is_attacked_by(opp, opp_move.to_square)
                and (not board.is_attacked_by(color, opp_move.to_square) or victim_val > attacker_val)
            )
            if not was_capturable:
                v_name = PIECE_NAMES.get(victim.piece_type, "piece")
                v_sq = chess.square_name(opp_move.to_square)
                a_name = PIECE_NAMES.get(attacker.piece_type, "piece")
                en_prise.append((v_name, v_sq, victim_val, a_name, attacker_val))

    # One entry per victim square, keeping the highest-value threat
    seen: dict[str, tuple] = {}
    for item in en_prise:
        sq = item[1]
        if sq not in seen or item[2] > seen[sq][2]:
            seen[sq] = item
    result = list(seen.values())
    result.sort(key=lambda x: -x[2])
    return result


def describe_move(board: chess.Board, move: chess.Move) -> str:
    """Natural-language description of a chess move for the candidate menu."""
    san = board.san(move)
    piece = board.piece_at(move.from_square)
    to_name = chess.square_name(move.to_square)

    piece_name = PIECE_NAMES.get(piece.piece_type, "Piece") if piece else "Piece"

    if san == "O-O":
        desc = "Castle kingside"
    elif san == "O-O-O":
        desc = "Castle queenside"

    elif move.promotion:
        promo_name = PIECE_NAMES.get(move.promotion, "piece")
        if board.is_capture(move):
            desc = f"Capture on {to_name} and promote to {promo_name}"
        else:
            desc = f"Push pawn to {to_name} and promote to {promo_name}"

    elif board.is_en_passant(move):
        desc = f"En passant capture on {to_name}"

    elif board.is_capture(move):
        captured = board.piece_at(move.to_square)
        captured_name = PIECE_NAMES.get(captured.piece_type, "piece") if captured else "piece"
        captured_value = PIECE_VALUES.get(captured.piece_type, 0) if captured else 0
        moving_value = PIECE_VALUES.get(piece.piece_type, 0)
        net = captured_value - moving_value
        if captured_value >= 9:  # queen capture
            desc = f"{piece_name} captures {captured_name} on {to_name} (wins {captured_value} points!)"
        elif net > 0:
            desc = f"{piece_name} captures {captured_name} on {to_name} (wins {captured_value} pts, net +{net})"
        elif net == 0:
            desc = f"{piece_name} captures {captured_name} on {to_name} (equal trade, {captured_value} pts)"
        else:
            desc = f"{piece_name} captures {captured_name} on {to_name} ({captured_value} pts)"

    # Development: a knight or bishop leaving the back rank
    elif piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == (0 if piece.color == chess.WHITE else 7):
        desc = f"Develop {piece_name.lower()} to {to_name}"

    elif piece.piece_type == chess.PAWN:
        distance = abs(chess.square_rank(move.to_square) - chess.square_rank(move.from_square))
        if distance == 2:
            desc = f"Push pawn two squares to {to_name}"
        else:
            desc = f"Push pawn to {to_name}"

    else:
        desc = f"{piece_name} to {to_name}"

    en_prise = find_pieces_en_prise_after(board, move)
    if en_prise:
        warnings = [
            f"{v_name.lower()} on {v_sq} (-{v_val}pts) exposed to {a_name.lower()}"
            for v_name, v_sq, v_val, a_name, _a_val in en_prise
        ]
        desc += f" (risks losing {'; '.join(warnings)})"

    return desc


def get_candidate_moves(engine, board, difficulty_idx, num_good, num_bad=0):
    """Top-N good moves plus bottom-M bad ones (traps) from Stockfish.

    Returns a shuffled list of (move, san, desc, is_trap) tuples.
    """
    diff = DIFFICULTIES[difficulty_idx]
    limit = chess.engine.Limit(depth=diff["depth"], time=diff["time"])

    legal_count = sum(1 for _ in board.legal_moves)

    if num_bad > 0 and legal_count > num_good:
        # Full analysis of every legal move to get both the best and the worst
        full_n = min(legal_count, 200)
        infos = engine.analyse(board, limit, multipv=full_n)

        good_moves = set()
        candidates = []
        for info in infos[:min(num_good, len(infos))]:
            move = info["pv"][0]
            good_moves.add(move)
            candidates.append((move, board.san(move), describe_move(board, move), False))

        bad_candidates = []
        for info in reversed(infos):
            if len(bad_candidates) >= num_bad:
                break
            move = info["pv"][0]
            if move not in good_moves:
                bad_candidates.append((move, board.san(move), describe_move(board, move), True))

        candidates.extend(bad_candidates)
    else:
        n = min(num_good, legal_count)
        infos = engine.analyse(board, limit, multipv=n)
        candidates = []
        for info in infos:
            move = info["pv"][0]
            candidates.append((move, board.san(move), describe_move(board, move), False))

    # Shuffle so the model can't assume A is always the best move
    random.shuffle(candidates)
    return candidates


def build_candidate_menu(candidates) -> str:
    """The candidates as a lettered menu, a blank line between options."""
    lines = []
    for i, (_move, san, desc, *_rest) in enumerate(candidates):
        lines.append(f"{chr(65 + i)}. {san} -- {desc}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_move_history(moves: list[dict[str, Any]]) -> str:
    """The move list as a PGN-style string."""
    parts = []
    for m in moves:
        s = f"{m['number']}. {m.get('white', '')}"
        if m.get("black"):
            s += f" {m['black']}"
        parts.append(s)
    return " ".join(parts)


def board_svg(board: chess.Board, last_move: chess.Move | None, flipped: bool) -> str:
    """The board picture, the agent's pieces at the bottom."""
    fill = {}
    if last_move:
        fill[last_move.from_square] = "#b58863aa"
        fill[last_move.to_square] = "#b58863aa"
    if board.is_check():
        fill[board.king(board.turn)] = "#ff000066"
    return chess.svg.board(
        board,
        flipped=flipped,
        lastmove=last_move,
        fill=fill,
        size=480,
        colors={
            "square light": "#f0d9b5",
            "square dark": "#b58863",
            "margin": "#161b22",
            "coord": "#8b949e",
        },
    )


# ~~~ game over ~~~
def check_game_over(board: chess.Board, move_number: int | None = None) -> tuple[bool, str, str]:
    """(is_over, result, reason). move_number enables the max-length draw."""
    if board.is_checkmate():
        winner = "Black" if board.turn == chess.WHITE else "White"
        return True, f"{winner} wins", "checkmate"
    if board.is_stalemate():
        return True, "Draw", "stalemate"
    if board.is_insufficient_material():
        return True, "Draw", "insufficient material"
    if board.can_claim_fifty_moves():
        return True, "Draw", "50-move rule"
    if board.is_fivefold_repetition():
        return True, "Draw", "fivefold repetition"
    if board.can_claim_threefold_repetition():
        # In real chess this is a voluntary claim, so it is only taken when
        # material is roughly even. A side with a winning edge plays on.
        mat = calc_material(board)
        if abs(mat["advantage"]) <= 3:
            return True, "Draw", "threefold repetition"

    if move_number is not None and move_number > MAX_GAME_MOVES:
        return True, "Draw", f"game exceeded {MAX_GAME_MOVES} moves"

    # Low material and no progress. halfmove_clock counts half-moves since the
    # last capture or pawn push. The 50-move rule needs 100; these fire much
    # sooner for positions that are practically drawn.
    mat = calc_material(board)
    w = mat["white_score"]
    b = mat["black_score"]
    hmc = board.halfmove_clock

    if w <= 3 and b <= 3 and hmc >= 10:
        return True, "Draw", "no progress (minor piece endgame)"
    if w <= 5 and b <= 5 and hmc >= 20:
        return True, "Draw", "no progress (low material)"
    if w <= 10 and b <= 10 and hmc >= 30:
        return True, "Draw", "no progress (stalled endgame)"
    if hmc >= 50:
        return True, "Draw", "no progress (extended shuffling)"

    return False, "", ""


# ~~~ the live board ~~~
class GameState:
    """What the dashboard reads. Written by the game thread, read by the page."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.board = chess.Board()
        self.moves: list[dict[str, Any]] = []
        self.thinking_log: list[dict[str, Any]] = []
        self.status = "waiting"   # waiting | playing | finished
        self.result = ""
        self.result_reason = ""
        self.llm_color = chess.WHITE
        self.difficulty_name = ""
        self.agent_name = ""
        self.last_move: chess.Move | None = None
        self.move_count = 0

    def to_dict(self) -> dict[str, Any]:
        with self.lock:
            return {
                "game": "chess",
                "agent_name": self.agent_name,
                "fen": self.board.fen(),
                "svg": board_svg(self.board, self.last_move, self.llm_color == chess.BLACK),
                "moves": list(self.moves),
                "thinking_log": list(self.thinking_log),
                "status": self.status,
                "result": self.result,
                "result_reason": self.result_reason,
                "llm_color": "White" if self.llm_color == chess.WHITE else "Black",
                "stockfish_color": "Black" if self.llm_color == chess.WHITE else "White",
                "difficulty": self.difficulty_name,
                "move_count": self.move_count,
                "turn": "White" if self.board.turn == chess.WHITE else "Black",
                "material": calc_material(self.board),
            }


# ~~~ the narrative ~~~
class GameNarrative:
    """Condensed per-move event log injected into each prompt."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.entries: list[str] = []

    def add_move(self, move_number, is_white, player_label, san, board_before, board_after, thinking=None):
        color = "White" if is_white else "Black"
        parts = [f"Move {move_number} ({color}/{player_label}): {san}"]

        captured_piece = self._detect_capture(board_before, board_after, san)
        if captured_piece:
            piece_name, value = captured_piece
            parts.append(f"captured {piece_name} (+{value})")

        if board_after.is_checkmate():
            parts.append("CHECKMATE")
        elif board_after.is_check():
            parts.append("check")

        if san in ("O-O", "O-O-O"):
            side = "kingside" if san == "O-O" else "queenside"
            parts.append(f"castled {side}")

        adv = calc_material(board_after)["advantage"]
        if adv > 0:
            parts.append(f"Material: White +{adv}")
        elif adv < 0:
            parts.append(f"Material: Black +{abs(adv)}")
        else:
            parts.append("Material: Even")

        if thinking and player_label == self.agent_name:
            truncated = thinking[:100].replace("\n", " ")
            if len(thinking) > 100:
                truncated += "..."
            parts.append(f'You thought: "{truncated}"')

        self.entries.append(" - ".join(parts))

    def build_context(self, budget_tokens: int) -> str:
        """The newest entries that fit the budget, in chronological order."""
        budget_chars = budget_tokens * CHARS_PER_TOKEN
        selected = []
        total_chars = 0
        for entry in reversed(self.entries):
            entry_chars = len(entry) + 1
            if total_chars + entry_chars > budget_chars:
                break
            selected.append(entry)
            total_chars += entry_chars
        selected.reverse()
        return "\n".join(selected)

    @staticmethod
    def _detect_capture(board_before, board_after, san):
        """(piece_name, value) if this move captured something, else None."""
        if "x" not in san:
            return None
        # The side that lost a piece is the one whose turn it now is
        captured_color = board_after.turn
        for piece_type, value in PIECE_VALUES.items():
            before_count = len(board_before.pieces(piece_type, captured_color))
            after_count = len(board_after.pieces(piece_type, captured_color))
            if after_count < before_count:
                return (PIECE_NAMES[piece_type], value)
        return None


# ~~~ the game ~~~
class ChessGame:
    """One game against Stockfish."""

    def __init__(self, difficulty_idx: int, llm_color_str: str, use_traps: bool = True,
                 agent_name: str = "You", pace: bool = True) -> None:
        self.difficulty_idx = difficulty_idx
        self.difficulty = DIFFICULTIES[difficulty_idx]
        self.llm_color = chess.WHITE if llm_color_str.lower() == "white" else chess.BLACK
        self.sf_color = not self.llm_color
        self.llm_color_name = "White" if self.llm_color == chess.WHITE else "Black"
        self.sf_color_name = "Black" if self.llm_color == chess.WHITE else "White"
        self.use_traps = use_traps
        self.agent_name = agent_name
        self.pace = pace

        self.state = GameState()
        self._engine = None
        self.board = chess.Board()
        self.narrative = GameNarrative(agent_name)
        self.moves_list: list[dict[str, Any]] = []
        self.move_number = 1
        self._game_over = False
        self._result: dict[str, Any] = {}
        self._last_opponent_move_text = ""
        self._candidates: list[tuple] = []
        self._counters = {f"{side}{name}": 0 for side in ("", "sf_") for name in RESIGN_COUNTERS}

    # ~~~ lifecycle ~~~
    def start(self) -> None:
        """Start Stockfish and, if it plays White, make its first move."""
        self._open_engine()
        self._sync_state(status="playing")
        if self.board.turn != self.llm_color:
            self._make_stockfish_move()

    def _open_engine(self) -> None:
        self._engine = chess.engine.SimpleEngine.popen_uci(get_stockfish())
        self._engine.configure({"Skill Level": self.difficulty["skill"]})
        if self.difficulty["elo"] <= 2000:
            try:
                self._engine.configure({"UCI_LimitStrength": True, "UCI_Elo": self.difficulty["elo"]})
            except chess.engine.EngineError:
                pass  # below Stockfish's UCI_Elo floor, Skill Level alone sets the strength

    def shutdown(self) -> None:
        if self._engine:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def _sync_state(self, status: str | None = None, last_move: chess.Move | None = None) -> None:
        with self.state.lock:
            self.state.board = self.board.copy()
            self.state.moves = [dict(m) for m in self.moves_list]
            self.state.llm_color = self.llm_color
            self.state.difficulty_name = self.difficulty["name"]
            self.state.agent_name = self.agent_name
            if last_move is not None:
                self.state.last_move = last_move
                self.state.move_count += 1
            if status:
                self.state.status = status

    # ~~~ a turn ~~~
    def get_turn_state(self) -> dict[str, Any] | None:
        """The agent's turn: prompt text, the menu, and what to print.

        None when the game is over or it isn't the agent's move.
        """
        if self._game_over:
            return None

        if self.board.is_game_over(claim_draw=True):
            is_over, result_text, reason = check_game_over(self.board, self.move_number)
            if is_over:
                self._finish_game(result_text, reason)
                return None

        if self.board.turn != self.llm_color:
            return None

        should_resign, resign_reason = self._check_resign(self.llm_color, "")
        if should_resign:
            self._finish_game(f"{self.sf_color_name} wins", resign_reason)
            return None

        good_count, bad_count = CANDIDATE_CONFIG.get(self.difficulty["name"], (3, 0))
        num_bad = bad_count if self.use_traps else 0

        # No traps once the position is already lost (down more than 5)
        if num_bad > 0 and self._advantage(self.llm_color) < -5:
            num_bad = 0

        self._candidates = get_candidate_moves(
            self._engine, self.board, self.difficulty_idx, good_count, num_bad
        )

        candidate_menu = build_candidate_menu(self._candidates)
        move_history_str = format_move_history(self.moves_list)
        board_str = str(self.board.unicode(borders=True))

        context_section = ""
        context_str = self.narrative.build_context(NARRATIVE_TOKENS)
        if context_str:
            context_section = f"\nGame context (your memory of the game so far):\n{context_str}\n"

        turn = "White" if self.board.turn == chess.WHITE else "Black"

        prompt_text = f"""Current position (FEN): {self.board.fen()}

Board:
{board_str}

Move history: {move_history_str if move_history_str else "(game just started)"}
{context_section}
It is {turn}'s turn.

Your move options:
{candidate_menu}"""

        # The tail of the prompt, word for word, for the terminal. The board
        # and history above it are on the dashboard.
        menu_text = f"It is {turn}'s turn.\n\nYour move options:\n" + "\n".join(
            line for line in candidate_menu.splitlines() if line
        )

        return {
            "prompt": prompt_text,
            "options": len(self._candidates),
            "move_number": self.move_number,
            "turn": turn,
            "menu_text": menu_text,
        }

    def apply_choice(self, choice_letter: str, thinking: str = "") -> dict[str, Any]:
        """Play the agent's pick, then Stockfish's reply. Returns what was played."""
        letter = str(choice_letter or "").strip().upper()
        idx = ord(letter) - 65 if len(letter) == 1 else -1
        if not 0 <= idx < len(self._candidates):
            idx, letter = 0, "A"  # an unusable letter plays the first option
        move, san, desc, is_trap = self._candidates[idx]

        is_white_turn = self.board.turn == chess.WHITE
        board_before = self.board.copy()

        if is_white_turn:
            self.moves_list.append({"number": self.move_number, "white": san, "black": ""})
        else:
            self.moves_list[-1]["black"] = san

        self.board.push(move)
        self.narrative.add_move(
            self.move_number, is_white_turn, self.agent_name, san,
            board_before, self.board, thinking=thinking,
        )

        if not is_white_turn:
            self.move_number += 1

        self._sync_state(last_move=move)
        with self.state.lock:
            self.state.thinking_log.append({
                "move_num": self.move_number if is_white_turn else self.move_number - 1,
                "color": "White" if is_white_turn else "Black",
                "thinking": thinking,
            })

        played = {"san": san, "desc": desc, "choice_letter": letter, "is_trap": is_trap}

        is_over, result_text, reason = check_game_over(self.board, self.move_number)
        if is_over:
            self._finish_game(result_text, reason)
            return played

        self._make_stockfish_move()
        return played

    def _make_stockfish_move(self) -> None:
        should_resign, resign_reason = self._check_resign(self.sf_color, "sf_")
        if should_resign:
            self._finish_game(f"{self.llm_color_name} wins", resign_reason)
            return

        is_white_turn = self.board.turn == chess.WHITE
        color_label = "White" if is_white_turn else "Black"

        if self.pace:
            time.sleep(STOCKFISH_PAUSE)
        result = self._engine.play(
            self.board,
            chess.engine.Limit(depth=self.difficulty["depth"], time=self.difficulty["time"]),
        )
        move = result.move
        san = self.board.san(move)

        if is_white_turn:
            self.moves_list.append({"number": self.move_number, "white": san, "black": ""})
        else:
            self.moves_list[-1]["black"] = san

        board_before = self.board.copy()
        self.board.push(move)
        self.narrative.add_move(
            self.move_number, is_white_turn, "Stockfish", san, board_before, self.board
        )

        desc = describe_move(board_before, move)
        self._last_opponent_move_text = f"{color_label} (Stockfish): {san} ({desc})"

        if not is_white_turn:
            self.move_number += 1

        self._sync_state(last_move=move)

        is_over, result_text, reason = check_game_over(self.board, self.move_number)
        if is_over:
            self._finish_game(result_text, reason)

    # ~~~ resigning ~~~
    def _advantage(self, color: chess.Color) -> int:
        mat = calc_material(self.board)
        return mat["advantage"] if color == chess.WHITE else -mat["advantage"]

    def get_standing(self) -> str:
        """'winning', 'losing', or 'even' for the agent, by material."""
        adv = self._advantage(self.llm_color)
        return "winning" if adv > 0 else "losing" if adv < 0 else "even"

    def _check_resign(self, color: chess.Color, prefix: str) -> tuple[bool, str]:
        """Whether `color` should resign. The same rules for both sides."""
        mat = calc_material(self.board)
        score = mat["white_score"] if color == chess.WHITE else mat["black_score"]
        advantage = self._advantage(color)
        c = self._counters

        # Lone king, no realistic winning chances
        if score == 0:
            c[f"{prefix}lone_king"] += 1
            if c[f"{prefix}lone_king"] >= LONE_KING_MOVES:
                return True, "resignation (lone king)"
        else:
            c[f"{prefix}lone_king"] = 0

        # Down a rook or more
        if advantage <= HOPELESS_THRESHOLD:
            c[f"{prefix}hopeless"] += 1
            if c[f"{prefix}hopeless"] >= HOPELESS_MOVES:
                return True, f"resignation (down {abs(advantage)} material for {c[f'{prefix}hopeless']} moves)"
        else:
            c[f"{prefix}hopeless"] = 0

        # Down a full piece for a sustained stretch
        if advantage <= LOSING_THRESHOLD:
            c[f"{prefix}losing"] += 1
            if c[f"{prefix}losing"] >= LOSING_MOVES:
                return True, f"resignation (down {abs(advantage)} material for {c[f'{prefix}losing']} moves)"
        else:
            c[f"{prefix}losing"] = 0

        # After move 50, even small deficits are decisive
        if self.move_number >= LATE_GAME_MOVE and advantage <= LATE_GAME_THRESHOLD:
            c[f"{prefix}late_game"] += 1
            if c[f"{prefix}late_game"] >= LATE_GAME_MOVES:
                return True, f"resignation (down {abs(advantage)} material in late game)"
        else:
            c[f"{prefix}late_game"] = 0

        return False, ""

    # ~~~ results ~~~
    def _finish_game(self, result_text: str, reason: str) -> None:
        self._game_over = True
        name = self.agent_name

        if "wins" in result_text:
            winner_color = result_text.split(" ")[0]
            if winner_color == self.llm_color_name:
                result_code = "W"
                outcome = f"{name} won (playing {self.llm_color_name})"
            else:
                result_code = "L"
                outcome = f"{name} lost (playing {self.llm_color_name})"
        else:
            result_code = "D"
            outcome = f"Draw ({name} was {self.llm_color_name})"

        self._result = {
            "result": result_code,
            "result_text": outcome,
            "reason": reason,
            "summary": f"Chess ({self.difficulty['name']}): {outcome} ({reason})",
        }
        with self.state.lock:
            self.state.status = "finished"
            self.state.result = outcome
            self.state.result_reason = reason

    def record_loss(self) -> None:
        """The agent quit mid-game, which counts as a loss."""
        self._game_over = True
        self._result = {
            "result": "L",
            "result_text": f"{self.agent_name} quit",
            "reason": "returned to menu",
            "summary": f"Chess ({self.difficulty['name']}): Quit (automatic loss)",
        }
        with self.state.lock:
            self.state.status = "finished"
            self.state.result = f"{self.agent_name} quit"
            self.state.result_reason = "returned to menu"

    def is_game_over(self) -> bool:
        return self._game_over

    def get_result(self) -> dict[str, Any]:
        """{"result": "W"/"L"/"D", "result_text", "reason", "summary"}."""
        return self._result

    def get_last_opponent_move_text(self) -> str:
        """Like 'Black (Stockfish): e5 (Push pawn two squares to e5)'."""
        return self._last_opponent_move_text

    # ~~~ save / restore ~~~
    def save_data(self) -> dict[str, Any]:
        return {
            "game": "chess",
            "fen": self.board.fen(),
            "moves_list": self.moves_list,
            "move_number": self.move_number,
            "difficulty_idx": self.difficulty_idx,
            "llm_color": "white" if self.llm_color == chess.WHITE else "black",
            "use_traps": self.use_traps,
            "agent_name": self.agent_name,
            "counters": dict(self._counters),
        }

    @classmethod
    def restore(cls, data: dict[str, Any], pace: bool = True) -> ChessGame:
        """A saved game, ready to play: board, moves and resign counters restored."""
        game = cls(
            data["difficulty_idx"], data["llm_color"],
            use_traps=data.get("use_traps", True),
            agent_name=data.get("agent_name", "You"),
            pace=pace,
        )
        game.board = chess.Board(data["fen"])
        game.moves_list = data.get("moves_list", [])
        game.move_number = data.get("move_number", 1)
        game._counters.update(data.get("counters", {}))
        game._open_engine()
        with game.state.lock:
            game.state.move_count = len(game.moves_list)
        game._sync_state(status="playing")
        return game
