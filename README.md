# Hearthstone Simple Bot

A simple computer-vision bot for Hearthstone on Windows. It can:

- find, restore, and bring the Hearthstone window to the foreground;
- launch the game through Battle.net when `Hearthstone.exe` is not found;
- recognize the blue glow around the **Play** button and click it only on the appropriate screen;
- recognize the starting-hand screen and click only its blue `OK` button;
- recognize match-result and rank screens separately by their desaturated backgrounds;
- find the green glow around playable cards and play only detected cards;
- find highlighted minions, use an available Hero Power, and finish the active turn;
- end turns, start the next match, and handle disconnect dialogs;
- close the match-start error dialog by clicking its `OK` button;
- stop through the **Stop** button or the global `Ctrl+C` hotkey.

This is a screen bot, not a game-playing AI. It makes decisions from colors and templates in screenshots of the game client. It does not read game memory and does not guarantee optimal plays. Game automation may violate the game's rules and could result in account penalties. Use it at your own risk.

## Installation and launch

The easiest option is to double-click `run_bot.cmd`. On its first launch, the script creates a local `.venv` environment and installs the required packages.

Python 3.11–3.13 x64 with Tkinter is required. To set it up manually, open PowerShell in this directory and run:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python SimpleBot.py
```

Python 3.14 may be too new for some OpenCV binary builds. If `opencv-python` cannot be installed, use Python 3.13.

## Coordinate configuration

All coordinates in `bot_config.json` are relative. `[0, 0]` is the top-left corner of Hearthstone's client area and `[1, 1]` is the bottom-right corner. This allows the same configuration to work in windowed and full-screen modes when the standard interface layout is used.

Important points:

- `play` — starts a match;
- `mulligan_confirm` — confirms the starting hand;
- `result_continue` — a safe continuation point on result and rank screens;
- `board_play` — the destination for cards dragged from the hand;
- `enemy_hero`, `hero_power`, and `end_turn` — the corresponding game elements.

Click duration is controlled by `click_hold_seconds` and `navigation_click_hold_seconds`. Menu buttons use the longer hold duration. Drag speed and the delays before and after dragging are controlled by `drag_duration`, `drag_hold_before_seconds`, and `drag_hold_after_seconds`.

If the client uses a nonstandard scale, adjust these values. The initial configuration was calibrated against a client area close to 1600×900.

## Computer vision

The `vision` section in `bot_config.json` controls recognition:

- `green_hsv` — the green glow around playable cards and available minions;
- `blue_hsv` — the blue glow around the **Play** button;
- `gold_hsv` — the active golden **End Turn** button;
- `hand_roi`, `own_board_roi`, `play_roi`, `mulligan_roi`, `error_dialog_roi`, and `end_turn_roi` — search regions;
- `play_color_ratio`, `error_dialog_gray_ratio`, `board_button_color_ratio`, and `end_turn_green_ratio` — minimum ratios of matching pixels;
- `max_cards_per_turn` and `max_attacks_per_turn` — safeguards against endless repeated actions.

The bot first checks for the End Turn button to distinguish the game board from menus. It then acts only when it sees a green card, a green minion, or the green End Turn button. A golden button alone does not start the turn logic because it may remain visible during an opponent's animation.

After detecting a card, the bot performs one drag to the board. It does not press `Esc`, select random targets, or iterate over a fixed hand grid. The bot checks for a green active Hero Power after playing cards and checks again after attacking, so remaining mana is used more consistently.

Cards are played from left to right. Match-result and rank screens are detected separately, receive one click each, and never trigger a blind sequence of menu clicks. A gray match-start error dialog is handled before the blue Play button behind it. Unknown screens cause no clicks, and recoverable iteration errors make the bot wait and retry instead of stopping its worker thread.

While the bot runs, it overwrites `debug_last.png`. Green `CARD` boxes mark detected cards and yellow `ATTACK` boxes mark detected attackers. The top line shows the scene classification. If recognition fails, stop the bot and inspect this image to tune the HSV thresholds accurately.

## Button templates (recommended)

For reliable unattended operation, capture tightly cropped images of the buttons and place them in the `templates` directory:

- `disconnect_ok.png` — the OK button after a disconnect;
- `reconnect.png` — reconnect;
- `continue.png` — continue after a match;
- `play.png` — start a match;
- `mulligan_confirm.png` — confirm the starting hand;
- `end_turn.png` — the active End Turn button.

Capture these images at the same Windows and Hearthstone scale that the bot will use. If `end_turn.png` exists, the bot runs its turn cycle only while that active button is visible, which greatly reduces accidental actions during the opponent's turn.

Without `play.png`, the bot recognizes the Play button by its blue glow. Templates are still recommended for disconnect dialogs, the starting-hand confirmation, and post-match screens because the bot clicks them only when the corresponding image is actually found.

## Automatic game launch

The default launch URI is `battlenet://WTCG`. If it does not work, set the full executable path in the `game.executable` field of `bot_config.json`.

Diagnostics are written to `hs_bot.log`.
