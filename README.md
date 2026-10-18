# Idleon Gaming

Local Windows application for Idleon’s **Gaming** garden.

## Start and stop

1. Open Idleon and display the full Gaming garden.
2. Double-click **run.cmd**. The interface opens at `http://127.0.0.1:8765`.
3. Click **Start**. If Windows does not bring the game forward automatically, select it during the three-second countdown.
4. Press **F8** or use **Stop** to stop the bot. Hiding the game or switching to another window also stops it.

**Quit application** closes the local server. Closing only the browser tab does not stop the server or bot. The bot never starts automatically when the application opens.

## Current game rules

- With **at least 20 plants before harvesting**, use Harvest All, wait two seconds, and then immediately use the sprinkler to refill the freed slots if water remains. The reduced plant count after harvesting does not cancel this refill.
- With **fewer than 20 plants and sprinkler Max**, use the sprinkler before considering the log. Do not wait for natural growth.
- With **fewer than 20 plants and sprinkler not Max**, play the log if Ready, even when some water charges remain.
- If no usable log is ready, look for a lab plant, advance time, and start the checks again.
- A sprinkler or log use may conserve its charge. Re-read the counters and Ready state instead of treating an unchanged value as failure or exhaustion.
- Only click face-down log cards. Wait at least one second between clicks. Wait through a green star until the next round; a gray skull latches a no-more-card-clicks state until the garden returns.

The sprinkler and green log are detected across the entire garden, including moved positions. The mouse settles over the detected target before pressing. A detection score confirms visual matching, not that a charge was consumed.

## Recognition and diagnostics

References live in `Sources/images_status`. Harvest All identifies the garden position and scale. Temporary harvest or return-from-log animations are retried without guessing coordinates. Missing targets, an unreadable screen, loss of foreground, or execution limits stop the bot. The latest error screenshot is saved to `diagnostics/last_error.png`.

Lab plants are matched by silhouette at multiple orientations, independent of colour. Occluded plants may be missed. The tests cover garden scales of 75%, 100%, 125%, and 150%, moved upgrades, card results, conserved charges, and the Max/non-Max distinction.

## Install on another Windows setup

The dependencies are already installed in `.venv` on this computer. With Python 3 installed:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run checks:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`vision.py` contains recognition, `bot.py` game control, `main.py` the local server, and `ui.html` the English interface. The previous implementation is preserved in `main_legacy.py`. The server binds only to `127.0.0.1`; screenshots are not uploaded.
