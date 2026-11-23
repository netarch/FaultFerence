# Inspector Switch

A minimal 2D character detective + Wordle-style network fault-localization game.
Runs **100% client-side in pure static HTML/CSS/JS** (`dashboard/static/`) with zero external libraries and zero backend required.

## Deploy to GitHub Pages (`github.io`)

Copy the contents of `dashboard/static/` (`index.html`, `style.css`, `sprites.js`, `topologies.js`, `engine.js`, `app.js`, `favicon.svg`) directly into your `*.github.io` repository (for example, `projects/fives/inspecter-switch/`). No Python backend, bundler, or WASM runtime is needed.

If you ever change the underlying topologies in `faultference/topologies/` or `testbed/topologies/`, regenerate `dashboard/static/topologies.js` via:

```bash
.venv/bin/python dashboard/export_topologies.py
```

## Run Locally

Serve `dashboard/static/` with any static file server:

```bash
python3 -m http.server 8050 -d dashboard/static
```

(Or `.venv/bin/python dashboard/server.py --port 8050`.)

## Gameplay

1. **Start Screen**: Pick a network (`Clos-k4`, `PROD`, `B4`, `Expander-k10`, `USCarrier`, `Clos-k10`) and fault mode (`Silent Drop`, `Blackhole`, `Intermittent`, `High Latency`), then click **Start Game** to beat the SLO countdown timer.
2. **2D Network Room**: Walk the detective with `WASD` / `Arrow` keys, click any switch or link to inspect and run a micro-action (`1`–`4`), or open **`Actions`** (`Space`) to pick an action card or switch inference mode (**`Flock`** vs **`Set ∩`**).
3. **SLO Timer & FIVES**: Each move deducts operational time alongside the live SLO countdown; if the timer hits `0:00`, the SLO is violated (`SLO violated. You are fired!`). Use **`FIVES Hint`** (`F`) or **`Solve with FIVES`** inside the Suspect Grid card at any point.
