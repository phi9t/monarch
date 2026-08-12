# Monarch Dashboard

A web dashboard for monitoring Monarch training jobs. Shows real-time actor status, message traffic, and health metrics across the Monarch hierarchy (Meshes > Host Units > Proc Meshes > Procs > Actor Meshes > Actors).

The dashboard is included in the `torchmonarch` package. After
`pip install torchmonarch`, the `monarch-dashboard` console command is available
on PATH. In a source checkout on Linux, run it through `scripts/run`, the sole
gateway into the hermetic bwrap rootfs, which builds the frontend as package data
during `uv pip install -e .`.

## Quick Start

```bash
# From an installed wheel
monarch-dashboard

# From a source checkout (Linux), through the rootfs gateway
scripts/run python -m monarch.monarch_dashboard
```

Then open http://localhost:5000 in your browser (or use an SSH tunnel, see below).

## Running Modes

### Static Data (default)

Serves the dashboard with a pre-generated SQLite database (`fake_data/fake_data.db`).

```bash
monarch-dashboard
# or, in a source checkout
scripts/run python -m monarch.monarch_dashboard
```

### Live Simulator

Launches a background simulator that writes data with real wall-clock timestamps, so the dashboard shows live-updating state. At 4.5 minutes (configurable), a CUDA OOM failure triggers on one host unit with death propagation.

```bash
monarch-dashboard --simulate
# or, in a source checkout
scripts/run python -m monarch.monarch_dashboard --simulate
```

### Live Simulator with Custom Failure Time

```bash
# Trigger failure after 30 seconds instead of 4.5 minutes
monarch-dashboard --simulate --failure-at 30
```

### Custom Tick Interval

```bash
# Simulator ticks every 0.5 seconds instead of 1.0
monarch-dashboard --simulate --interval 0.5
```

### Standalone Simulator

Run the simulator by itself (without the Flask server), useful for pre-populating a database.

```bash
scripts/run python python/monarch/monarch_dashboard/fake_data/simulate.py --db fake_data/fake_data.db --failure-at 270
```

Options:
- `--db PATH` — SQLite database path (default: `fake_data/fake_data.db`)
- `--interval SECONDS` — tick interval (default: 1.0)
- `--failure-at SECONDS` — seconds until failure event (default: 270)

## Rebuilding the frontend

The frontend is built as package data during the editable install, not by a CLI
flag. To rebuild it from a source checkout, reinstall the project through the
rootfs gateway, which runs the deterministic frontend build:

```bash
scripts/run uv pip install -e .
```

## SSH Tunnel

The dashboard binds to `0.0.0.0:5000`. To access it from your laptop:

```bash
ssh -L 5000:localhost:5000 YOUR_HOST
```

Then open http://localhost:5000 in your local browser.

## CLI Flags

### `monarch-dashboard` (also `python -m monarch.monarch_dashboard`)

| Flag | Description |
|------|-------------|
| `--db PATH` | SQLite database path |
| `--host HOST` | Bind address (default: 0.0.0.0) |
| `--port PORT` | Bind port (default: 5000) |
| `--simulate` | Launch live data simulator |
| `--failure-at N` | Seconds until simulator failure (default: 270) |
| `--interval N` | Simulator tick interval (default: 1.0) |

### `fake_data/simulate.py`

| Flag | Description |
|------|-------------|
| `--db PATH` | SQLite database path (default: fake_data/fake_data.db) |
| `--interval N` | Tick interval in seconds (default: 1.0) |
| `--failure-at N` | Seconds until failure event (default: 270) |
