# Module integration

How the Chess module plugs into [Eli Felse Base](https://github.com/ella0333/Eli_Felse_Base).
If you have not set the base up yet, start with its
[getting started guide](https://github.com/ella0333/Eli_Felse_Base/blob/master/docs/getting-started.md).

## Installation

```bash
cd Eli_Felse_Base
.venv\Scripts\activate
git clone https://github.com/ella0333/Eli_Felse_Chess.git data/modules/chess
cd data/modules/chess
pip install -r requirements.txt
python scripts/setup.py
```

The base scans `data/modules/` at startup and reads the `ACTIVITIES` list out of the
folder's `__init__.py`. There is nothing to register.

`scripts/setup.py` downloads Stockfish into `stockfish/` inside the module folder. On
Mac and Linux, a Stockfish already installed through `brew` or `apt` is used instead. If
the setup step was skipped, the first game downloads it.

This module needs base **0.5.0 or newer**, which is the release that added shared menu
lines and module dashboard pages.

## Menu structure

Chess does not take a main-menu line of its own. It declares
`menu_group = "Play a Board or Card Game"`, so the base folds it into a shared line
with any other module that declares the same group:

```
D) Play a Board or Card Game (Chess, Poker, Blackjack)
```

Picking that opens the group's sub-menu, and picking the game runs it:

```
Play a Board or Card Game

A) Chess (last: 2 hours ago)
B) Poker
C) Blackjack
```

Install Chess on its own and the line reads `Play a Board or Card Game (Chess)`.
The anti-repeat rule still applies per game, so playing chess holds chess back for a
turn without hiding the others.

### Sub-menus

1. **Resume**, only when a save is waiting: resume, or start fresh and delete the save.
2. **Setup**, asking only for what config left open: difficulty and color.
3. **Move**, every turn: a lettered list of candidate moves from Stockfish.
4. **Quit menu**, when the agent sets `return_to_menu` mid-game: quit and take the
   loss, save and quit, or cancel and keep playing.

## Config

Add an optional section to your `config.yaml`. Every key is optional, and the module
runs with none of them.

```yaml
activities:
  chess:
    difficulty: agent      # agent | beginner | easy | casual | intermediate | advanced | hard | expert | master
    color: agent           # agent | white | black
    daily_limit: 0         # games per day, 0 = no cap
    pace_table: true       # pause two seconds before Stockfish moves so the board is watchable
```

`agent` means the agent is asked during setup. Any other value fixes the answer and
drops that question from the setup menu, so pinning both means the agent is never
asked anything and sits straight down.

There is no API key, so nothing goes in the base's `.env` and `requires` is empty.

## Difficulty

| Level | ELO | Stockfish depth | Candidate moves |
|-------|-----|-----------------|-----------------|
| Beginner | 800 | 1 | 3 good, 1 trap |
| Easy | 1000 | 3 | 3 good, 1 trap |
| Casual | 1200 | 5 | 3 good, 1 trap |
| Intermediate | 1500 | 8 | 3 good, 2 traps |
| Advanced | 1800 | 12 | 3 good, 2 traps |
| Hard | 2000 | 15 | 3 good, 3 traps |
| Expert | 2200 | 18 | 3 good, 3 traps |
| Master | 2500 | 20 | 3 good, 3 traps |

The ELO is passed to Stockfish as `UCI_Elo` up to Hard. Stockfish will not go below
1320, so Beginner, Easy and Casual are set by Stockfish's Skill Level alone. Expert
and Master have no ELO cap and play at Skill Level 18 and 20.

## How a turn works

Stockfish analyses every legal move. The top three become the good candidates, and
the worst-ranked moves become the traps. The list is shuffled so the first letter is
never a safe guess. Each move is described in plain words: captures say what they win
and whether the trade is even, knights and bishops leaving the back rank are
"Develop", and any move that leaves a piece open to a losing capture says so. Once the
agent is down more than five points of material, the traps are dropped, since there
is nothing left to test.

The turn prompt carries the position as FEN, a drawn board, the move list, and a
short log of the game so far, trimmed to the most recent moves when it gets long.

An unusable letter plays the first option rather than guessing.

## How a game ends

Checkmate, stalemate, insufficient material, the fifty-move rule and fivefold
repetition end the game as in normal chess. Threefold repetition is only claimed when
material is within three points, so a side that is clearly winning plays on.

Games also end sooner than a strict rulebook would:

- **A draw for no progress.** With little material left and no captures or pawn moves
  for 5 to 25 moves, depending on how much is on the board.
- **A draw at move 80.**
- **Resignation**, by either side: three moves with a lone king, six moves down seven
  points or more, fifteen moves down four or more, or after move 50, ten moves down
  three or more.

## The dashboard page

`dashboard_view = "dashboard/index.html"` gives the module a tab in the base's
dashboard. Start it with the `/dashboard` command and open
**http://127.0.0.1:8080**, the base's own dashboard port. The page polls
`/api/module-state?key=chess` twice a second and shows the board, the captured
material, the move list, and the agent's latest thinking.

The standalone harness serves the same page on the same port, since it is what you
run instead of the base rather than alongside it.

## Data storage

One file, `data/activities/chess/chess_save.json`, and only while a game is saved. It
holds the position, the move list, the difficulty and color, and the resignation
counters. Everything else goes through the base's own stores.

## Context isolation

`isolate_context = True` and `memory_mode = "game_batch"`. A chess game is dozens of
move decisions, so the framework snapshots context before the game and restores it
after, and memories are batched three messages at a time without the classifier.
What survives is the summary, not the notation.

## Stats

`chess.games_played`, `chess.wins`, `chess.losses`, `chess.draws`, and
`chess.games_saved`, all visible on the dashboard's status page.

## Schemas

The setup menu and each move are schema-constrained JSON: a letter from an enum,
plus `return_to_menu` on moves. The agent can only ever answer with a letter, so it
can only ever play a legal move.
