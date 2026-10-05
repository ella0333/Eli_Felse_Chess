# Eli Felse | Chess

[![MIT License](https://img.shields.io/badge/MIT_License-869b9f?style=flat)](LICENSE)

!["Eli" Chibi Character with grey hair and green eyes, and grey x hair clip holding a chess piece](https://i.imgur.com/n79Rfm2.png)

**A module for [Eli Felse Base](https://github.com/ella0333/Eli_Felse_Base) that lets
an AI agent play chess against Stockfish at eight difficulty levels, from beginner
to master.**

The agent configures the game by default: which difficulty and which color. You can
manually pin either option in `config.yaml`.

## Quick start

```bash
cd Eli_Felse_Base
.venv\Scripts\activate        # Windows   (Mac/Linux: source .venv/bin/activate)
git clone https://github.com/ella0333/Eli_Felse_Chess.git data/modules/chess
cd data/modules/chess
pip install -r requirements.txt
python scripts/setup.py       # game configuration, and downloads Stockfish
cd ../../..                   # Back to Eli_Felse_Base
elifelse run
```

"Chess" will appear under "Play a Board or Card Game" in the activity menu,
alongside any other board or card game you have installed.

New to all of this? Follow the **[base project's guide](https://github.com/ella0333/Eli_Felse_Base/blob/master/docs/getting-started.md)** and come back here when you are finished

Need help choosing a compatible model? See the 
**[Model Options Guide](https://github.com/ella0333/Eli_Felse_Base/blob/master/docs/model-options.md)**

Requires base **0.5.0 or newer**.

## How the LLM plays chess

The agent never writes its own moves from scratch. Each turn, Stockfish analyses the position and
gives the agent a short multiple-choice list of moves to choose from. The list is its top
three moves, mixed with one to three of the worst moves on the board as traps, in a
random order. Each option is described in plain words, such as "Knight captures Bishop
on f6 (equal trade, 3 pts)" or a warning that it leaves the queen exposed. The agent
only has to pick a letter, so even a small local model plays legal, sensible chess and
can actually win, while the traps still test its judgment. The model is paired against a Stockfish bot of the chosen difficulty as well. 

## Viewing the board

Type `/dashboard` while the agent is running and open
**http://127.0.0.1:8080**

## Settings

Every setting takes `agent`, the default, which means the agent is asked during setup.
Add the value yourself instead, and the agent is no longer prompted to decide.

```yaml
activities:
  chess:
    difficulty: agent      # agent | beginner | easy | casual | intermediate | advanced | hard | expert | master
    color: agent           # agent | white | black
```

A daily cap and the pause before Stockfish moves are in
**[module integration](docs/module-integration.md)**.

## Standalone chess harness

You can also run this module without the Eli Felse framework. Connect any
**[compatible model](https://github.com/ella0333/Eli_Felse_Base/blob/master/docs/model-options.md)** and let it play directly.

```bash
git clone https://github.com/ella0333/Eli_Felse_Chess.git
cd Eli_Felse_Chess
python -m venv .venv
.venv\Scripts\activate        # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python standalone_setup.py    # configures the model connection and downloads Stockfish
python standalone.py          # play
```

The model sets up a game and plays it out, one game after another, until it spends
the session's game limit (3 by default, set during setup). The same board is served at
**http://127.0.0.1:8080** while it plays. Press `Ctrl+C` at any time to quit.

## Docs

- **[Module integration](docs/module-integration.md):** how it plugs into the base, menus, config, memory
- **[Standalone mode](docs/standalone-mode.md):** standalone harness setup and how sessions work

## Learn More about the Project

Meet Eli Felse, a framework built to explore safer ways to create autonomous AI assistants.
Eli Felse is part of a public demo, weekly blogs, open-source releases, and a growing community.

**[24/7 live public demo](https://elifelse.org/eli/)**

**[Introduction Blog](https://elifelse.org/dev-blog/meet-eli)**

**[Join the Discord community](https://discord.com/invite/2C4znNnyM7)**

## Third-party licenses

This project is licensed under the [MIT License](LICENSE). It uses the following
third-party components, which are not included in this repository. Each is installed
separately and stays under its own license, the GNU General Public License.

| Component | License | Details |
|-----------|---------|---------|
| **[Stockfish](https://stockfishchess.org/)** | GPL v3 | Downloaded by the setup scripts from the official releases · Source: [github.com/official-stockfish/Stockfish](https://github.com/official-stockfish/Stockfish) |
| **[python-chess](https://github.com/niklasf/python-chess)** | GPL v3 or later | Installed by `pip` from `requirements.txt` · Source: [github.com/niklasf/python-chess](https://github.com/niklasf/python-chess) |

---

[![elif else](https://img.shields.io/badge/elif_else-869b9f?style=flat)](https://elifelse.org/)
[![MIT License](https://img.shields.io/badge/MIT_License-869b9f?style=flat)](LICENSE)
