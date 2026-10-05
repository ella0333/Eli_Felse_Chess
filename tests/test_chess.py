"""The move descriptions and game-over rules are pure, so they are tested
directly. Games run against the real Stockfish (the setup scripts download
it), and the activity is driven end to end on the MockProvider, with menu
answers scripted as letters exactly as a real model would send them."""

import json
import random

import chess
import pytest

from src.chess_game.engine import (
    DIFFICULTIES,
    ChessGame,
    calc_material,
    check_game_over,
    describe_move,
)
from src.chess_game.stockfish import find_stockfish

needs_stockfish = pytest.mark.skipif(
    find_stockfish() is None, reason="Stockfish not installed, run standalone_setup.py"
)


def play_out(game, letter="A", max_turns=400):
    """Take the same letter every turn until the game ends."""
    turns = 0
    while not game.is_game_over() and turns < max_turns:
        if game.get_turn_state() is None:
            break
        game.apply_choice(letter)
        turns += 1
    return turns


# ~~~ the rules ~~~
def test_a_capture_says_what_it_wins():
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    desc = describe_move(board, chess.Move.from_uci("e4d5"))
    assert desc.startswith("Pawn captures Pawn on d5")


def test_a_move_that_hangs_a_piece_is_flagged():
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    # Queen to g4 walks into the bishop on c8
    desc = describe_move(board, chess.Move.from_uci("d1g4"))
    assert "risks losing queen on g4" in desc


def test_development_and_castling_are_named():
    board = chess.Board()
    assert describe_move(board, chess.Move.from_uci("g1f3")) == "Develop knight to f3"
    castle = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert describe_move(castle, chess.Move.from_uci("e1g1")) == "Castle kingside"


def test_material_counts_the_captured_pieces():
    board = chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    mat = calc_material(board)
    assert mat["advantage"] == 5
    assert len(mat["white_captured"]) == 15  # every black piece but the king


def test_a_no_progress_minor_piece_endgame_is_a_draw():
    board = chess.Board("4k1n1/8/8/8/8/8/8/2B1K3 w - - 10 60")
    assert check_game_over(board) == (True, "Draw", "no progress (minor piece endgame)")


def test_a_game_past_the_length_cap_is_a_draw():
    over, result, reason = check_game_over(chess.Board(), move_number=81)
    assert over and result == "Draw" and "80 moves" in reason


def test_the_menu_elos_match_the_engine():
    assert [d["elo"] for d in DIFFICULTIES] == [800, 1000, 1200, 1500, 1800, 2000, 2200, 2500]


# ~~~ the game ~~~
@needs_stockfish
def test_a_turn_offers_shuffled_lettered_candidates():
    random.seed(1)
    game = ChessGame(3, "white", pace=False)
    game.start()
    try:
        turn = game.get_turn_state()
        # Intermediate: three good moves and two traps
        assert turn["options"] == 5
        assert "Your move options:" in turn["prompt"]
        assert "A. " in turn["prompt"] and "E. " in turn["prompt"]
        assert sum(1 for c in game._candidates if c[3]) == 2
    finally:
        game.shutdown()


@needs_stockfish
def test_playing_black_lets_stockfish_open():
    game = ChessGame(0, "black", pace=False)
    game.start()
    try:
        assert len(game.moves_list) == 1
        assert game.board.turn == chess.BLACK
        assert game.get_last_opponent_move_text().startswith("White (Stockfish):")
    finally:
        game.shutdown()


@needs_stockfish
def test_an_unusable_letter_plays_the_first_option():
    random.seed(2)
    game = ChessGame(0, "white", pace=False)
    game.start()
    try:
        game.get_turn_state()
        first = game._candidates[0][1]
        played = game.apply_choice("Z")
        assert played["choice_letter"] == "A"
        assert played["san"] == first
    finally:
        game.shutdown()


@needs_stockfish
def test_a_game_plays_to_a_result():
    random.seed(3)
    game = ChessGame(7, "white", pace=False)
    game.start()
    try:
        play_out(game)
        assert game.is_game_over()
        assert game.get_result()["result"] in {"W", "L", "D"}
    finally:
        game.shutdown()


@needs_stockfish
def test_a_save_restores_the_position():
    random.seed(4)
    game = ChessGame(1, "white", agent_name="Testa", pace=False)
    game.start()
    game.get_turn_state()
    game.apply_choice("A")
    data = game.save_data()
    game.shutdown()

    resumed = ChessGame.restore(data, pace=False)
    try:
        assert resumed.board.fen() == data["fen"]
        assert resumed.moves_list == data["moves_list"]
        assert resumed.agent_name == "Testa"
        assert resumed.get_turn_state() is not None
    finally:
        resumed.shutdown()


# ~~~ the activity ~~~
async def test_the_activity_sits_under_the_shared_games_line(chess_activity):
    activity, _ = chess_activity
    assert activity.menu_group == "Play a Board or Card Game"
    assert activity.key == "chess"
    assert activity.requires == []


@needs_stockfish
async def test_a_full_game_runs_from_scripted_menu_answers(chess_activity, mock_provider, app):
    activity, ctx = chess_activity
    random.seed(5)
    mock_provider.feed({"thinking": "start gently", "difficulty": "H", "color": "A"})
    for _ in range(400):
        mock_provider.feed({"thinking": "this one", "choice": "A", "return_to_menu": False})

    note = await activity.run(ctx)

    assert note.startswith("Finished playing Chess against Stockfish")
    assert app.stats.get("chess.games_played") == 1


@needs_stockfish
async def test_config_can_fix_a_setting_and_drop_its_question(chess_activity, mock_provider, app):
    """With both settings pinned, the setup menu never gets asked at all."""
    activity, ctx = chess_activity
    app.config.activities["chess"] = {"pace_table": False, "difficulty": "master", "color": "black"}
    random.seed(6)
    for _ in range(400):
        mock_provider.feed({"thinking": "this one", "choice": "A", "return_to_menu": False})

    await activity.run(ctx)

    assert all("difficulty" not in call["schema"]["properties"] for call in mock_provider.calls)
    assert all("color" not in call["schema"]["properties"] for call in mock_provider.calls)


@needs_stockfish
async def test_leaving_mid_game_can_save_and_resume(chess_activity, mock_provider, app):
    activity, ctx = chess_activity
    app.config.activities["chess"] = {"pace_table": False, "difficulty": "easy", "color": "white"}
    mock_provider.feed({"thinking": "move", "choice": "A", "return_to_menu": False})
    mock_provider.feed({"thinking": "I want to stop", "choice": "A", "return_to_menu": True})
    mock_provider.feed({"thinking": "keep it for later", "choice": "B"})  # save and quit

    note = await activity.run(ctx)

    save = ctx.data_dir / "chess_save.json"
    assert save.exists()
    assert "Saved the chess game" in note
    saved = json.loads(save.read_text(encoding="utf-8"))
    assert saved["game"] == "chess"
    assert saved["summary"].startswith("Turn 2")
    assert activity.get_status(ctx) == "saved game waiting"

    # Resuming picks up the same position and clears the save
    mock_provider.feed({"thinking": "back to it", "choice": "A"})  # resume
    mock_provider.feed({"thinking": "stop again", "choice": "A", "return_to_menu": True})
    mock_provider.feed({"thinking": "just go", "choice": "A"})  # quit
    await activity.run(ctx)
    assert not save.exists()
    assert app.stats.get("chess.losses") == 1


@needs_stockfish
async def test_quitting_mid_game_counts_as_a_loss(chess_activity, mock_provider, app):
    activity, ctx = chess_activity
    app.config.activities["chess"] = {"pace_table": False, "difficulty": "easy", "color": "white"}
    mock_provider.feed({"thinking": "done with this", "choice": "A", "return_to_menu": True})
    mock_provider.feed({"thinking": "just go", "choice": "A"})  # quit

    note = await activity.run(ctx)

    assert "counts as a loss" in note
    assert app.stats.get("chess.losses") == 1
    assert not (ctx.data_dir / "chess_save.json").exists()


@needs_stockfish
async def test_the_dashboard_state_is_the_live_board(chess_activity):
    activity, ctx = chess_activity
    assert activity.dashboard_state(ctx) is None  # nothing running

    activity._game = ChessGame(0, "black", agent_name=ctx.persona.name, pace=False)
    activity._game.start()
    try:
        state = activity.dashboard_state(ctx)
        assert state["game"] == "chess"
        assert state["agent_name"] == "Testa"
        assert state["svg"].startswith("<svg")
        assert state["move_count"] == 1
    finally:
        activity._game.shutdown()
        activity._game = None
