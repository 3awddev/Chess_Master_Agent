# ChessMaster

A Windows desktop assistant that watches a chessboard on your screen, recognizes the position, asks the Stockfish engine for the best move, and shows it directly over the board:

- **Red rectangle**: the piece to move.
- **Green rectangle**: the square to move it to.

It only looks at the screen. It never clicks, types, or changes the chess game or the browser.

> **Fair play:** Using engine help in rated or live games on chess.com, lichess, or anywhere else breaks their rules and gets accounts closed. Use ChessMaster for analysis boards, games against bots, puzzles, studying openings, and reviewing your own finished games.

## Requirements

- Windows 10 or 11, 64-bit.
- Nothing else for the ready-made version. To run from source you also need Python 3.11 or newer.

## Option A: Use the ready-made app (easiest)

1. On the computer where it was built, copy the **whole** folder `dist\ChessMaster\` (USB stick, zip file, cloud drive...). The folder must stay complete: `ChessMaster.exe` needs the `_internal` folder next to it, which contains Stockfish and the built-in board profiles.
2. On the new computer, put the folder anywhere, for example `C:\Program Files\ChessMaster` or your Desktop.
3. Double-click `ChessMaster.exe`.
   - If Windows SmartScreen says "Windows protected your PC", click **More info**, then **Run anyway**. This appears because the app is not code-signed.
4. Optional: right-click `ChessMaster.exe` and choose **Send to > Desktop (create shortcut)**.

No installation or administrator rights are needed.

## Option B: Set it up from the source code

Use this if you received the project folder (with `src`, `scripts`, `pyproject.toml`) instead of the built app.

1. **Install Python** (3.11 or newer). Either download it from [python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe to PATH"** during setup, or run in PowerShell:

   ```powershell
   winget install -e --id Python.Python.3.12
   ```

2. **Open PowerShell in the project folder.** In File Explorer, open the folder, click the address bar, type `powershell` and press Enter.

3. **Allow local scripts for this window** (needed for the `.ps1` helper scripts):

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

4. **Create a virtual environment and install the app:**

   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\pip install -e ".[dev]"
   ```

5. **Download Stockfish** (official build from GitHub, saved to `engine\stockfish.exe`):

   ```powershell
   .\scripts\get_stockfish.ps1
   ```

6. **Run it:**

   ```powershell
   .venv\Scripts\python -m chessmaster
   ```

7. **Optional: build your own `ChessMaster.exe`** (takes a few minutes):

   ```powershell
   .\scripts\build.ps1
   ```

   The result is `dist\ChessMaster\ChessMaster.exe`. Copy the whole `dist\ChessMaster` folder to use it elsewhere (see Option A).

8. **Optional: run the tests:**

   ```powershell
   .venv\Scripts\python -m pytest -q
   ```

## First use

1. Start ChessMaster. The control panel opens in the top-right corner of the screen.
2. Open a chessboard (for example the lichess or chess.com analysis board). Keep the whole board visible and don't let the ChessMaster panel cover it.
3. The app finds the board automatically. The panel shows **Board: Found at ...**.
4. **Calibrate once per board style:**
   - Lichess' default brown board works out of the box.
   - For any other board theme or piece set (for example chess.com), show the **starting position** and click **Calibrate**. The app learns the square colors and pieces, then saves a profile. Next time that style is recognized automatically.
5. Play or analyse. When it is your turn, the red and green rectangles show the suggested move. The panel also shows the move, the evaluation, and a mini-board of what the app sees.

By default the hints are for the side at the bottom of the board. You can change this in **Settings**.

## Controls

| Button / key | What it does |
| --- | --- |
| Pause / Resume | Stop or restart watching the screen. |
| Calibrate | Learn a new board style. The board must show the starting position. |
| Select board | Drag a rectangle around the board if it is not found automatically. |
| Resync | Re-read the position from the screen if the app got out of step. |
| Flip board | Use if White and Black at the bottom were detected the wrong way round. |
| Settings | Engine, think time, threads, memory, screen checks per second, which side gets hints, rectangle thickness. |
| **Ctrl+Alt+H** | Show or hide the hints (works from any window). |
| **Ctrl+Alt+R** | Resync (works from any window). |

## Where things are stored

Everything is in `%APPDATA%\ChessMaster` (paste that into the File Explorer address bar):

- `profiles\`: your calibrated board styles. Copy this folder to another computer to skip calibrating again.
- `settings.json`: your settings.
- `logs\chessmaster.log`: what the app detected and did. Useful when something goes wrong.

To reset the app completely, close it and delete that folder.

## Troubleshooting

**"Searching the screen..." and the board is never found**
- Make sure the whole board is visible and nothing covers it, including the ChessMaster panel itself. Move the panel to the side.
- Zoom the browser so the board is reasonably large (at least about 200 px wide).
- Use **Select board** and drag a rectangle tightly around the 8x8 squares.

**"Not calibrated - show the start position and click Calibrate"**
This board style is new. Show the starting position and click **Calibrate**.

**Calibration fails**
- "The middle of the board is not empty": the board is not in the starting position. Start a new analysis board or game and try again.
- "Self-test failed": something covers part of the board (the panel, a popup, an arrow or a drawn circle). Clear it and try again.

**Many "unclear squares", or wrong moves shown**
- Something covers the board, or arrows/circles are drawn on it. Remove them.
- The board theme or pieces were changed since calibrating. Calibrate again.
- Click **Resync** (Ctrl+Alt+R). If White/Black is upside down, click **Flip board**.

**The rectangles are slightly off the squares**
Click **Select board** and drag tightly around the board. This also happens briefly while the page is scrolling or resizing.

**"Stockfish was not found"**
- Ready-made app: the `_internal` folder is missing. Copy the whole `dist\ChessMaster` folder again.
- From source: run `.\scripts\get_stockfish.ps1`, or choose any UCI engine `.exe` in **Settings**.

**"Hotkey ... is already in use by another program"**
Another program (or a second copy of ChessMaster) uses Ctrl+Alt+H or Ctrl+Alt+R. Close the other copy. The buttons work either way.

**The app starts mid-game and says "(assumed)" next to the side to move**
When there is no last-move highlight, the app guesses whose turn it is. It corrects itself after the next move, or you can press **Resync**.

## Known limitations

- Made for flat 2D boards (lichess, chess.com, most desktop chess programs). 3D boards are not supported, and very unusual piece sets may need a careful calibration.
- When joining a game in progress, castling and en passant rights are guessed from the board. Following a game from the first move is exact.
- Arrows or circles drawn on the board block recognition of those squares until removed.

## Credits and licenses

- [Stockfish](https://stockfishchess.org/) is free software under the GNU GPL v3. Its license is included as `engine\COPYING.txt`.
- Built with Python, [PySide6 (Qt)](https://doc.qt.io/qtforpython-6/), [OpenCV](https://opencv.org/), [python-chess](https://python-chess.readthedocs.io/), and [mss](https://github.com/BoboTiG/python-mss).
