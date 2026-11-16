# Dead Cells ultrawide for native Linux

An experimental, reversible runtime patch for native Linux Dead Cells. It
expands the horizontal view without stretching the image or changing the
game's vertical scale. It does not modify game files and resets when the game
exits.

## Compatibility and risks

- Tested with the Steam **native Linux** build 23762174 and its `hlboot.dat`
  SHA-256 `59350cad475a2375b9e39d7cd13fdb6e4ed9a027fd827ae5140f913c1c07ce7e`.
  The patcher refuses other versions; game updates can break it.
- Tested on x86-64 Linux, X11, and a 3440x1440 fullscreen game window. Other
  resolutions are calculated but have not been tested in-game. Wayland and
  Proton are not supported by this prototype.
- Requires Python 3.11 or newer, `wmctrl`, and `xprop` (usually provided by
  `x11-utils`). No Python packages are needed.
- The tool reads and writes the running process's memory. Linux permissions,
  ptrace restrictions or Steam's runtime may prevent access. Run it as the
  same user as the game; **do not use sudo** or weaken system security settings
  to make it work.
- The game briefly leaves fullscreen and returns to it to recalculate the view.
  Camera limits, small rooms, cutscenes, menus, or HUD elements may look wrong.
  This is experimental and may crash the game or disrupt an unsaved run.

## Use

1. Start the native Linux version of Dead Cells through Steam and enter
   fullscreen on the intended monitor.
2. From this directory, run:

   ```sh
   python3 ultrawide.py
   ```

3. Check the current value without modifying the game:

   ```sh
   python3 ultrawide.py --status
   ```

4. Restore the original view during the same session:

   ```sh
   python3 ultrawide.py --restore
   ```

Restarting the game also restores the original behavior. The patch is not
applied automatically; run it after each game start. Game installation paths
are discovered from the running executable, and no game assets are included.

The fullscreen window's dimensions are detected automatically. To specify
the resolution explicitly, it must match those dimensions:

```sh
python3 ultrawide.py --resolution 3440x1440
```

By default the viewport width is calculated to fill the screen using the
game's pixel scale. To choose a different **logical** horizontal width
instead, for example 900 (allowed range: 1 to 8192):

```sh
python3 ultrawide.py --width 900
```

A smaller width can leave black bars; a larger width is capped by the window
size, so it does not necessarily reveal more world. This is **not a camera
zoom control** and does not change character size. A reliable adjustable
camera zoom has not yet been implemented.

## How it works

In the tested build, the game computes the stage size from the window size,
pixel scale, and `Viewport.NATIVE_WIDTH` / `NATIVE_HEIGHT`. The patcher
checks the bytecode hash, locates a unique matching `$Viewport` object in
writable process memory, and changes its width (683 to 860 at 3440x1440). It verifies
the written value and requests a resize so the game recalculates its layout.
This changes the active process, not the bytecode on disk.

This approach is inspired by the documented runtime technique in
[prismicious/deadcells-ultrawide](https://github.com/prismicious/deadcells-ultrawide),
which targets the Windows version.

## Tests

```sh
python3 -m unittest -v
```

The unit tests use synthetic memory; they do not start or patch the game.
