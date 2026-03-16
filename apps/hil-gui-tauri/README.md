# HIL GUI (Tauri + Rust)

Desktop GUI for the Hardware-in-the-Loop project with:
- Rust backend for serial protocol and stream buffering
- Tauri IPC events for chunked telemetry delivery
- Frontend plot optimized with min-max decimation

## Why this stack

- Rust handles high-rate serial IO and protocol parsing with low overhead.
- Tauri keeps desktop footprint much lower than Electron.
- Chunked IPC avoids JSON overhead from per-sample events.

## Current features

- List serial ports
- Start/stop real-time stream via Read All command
- Write `VDC_BUS` and `TORQUE_LOAD`
- Live values for all registers
- Real-time plot with frontend decimation

## App structure

```text
apps/hil-gui-tauri/
  src/                 # Frontend (TypeScript + uPlot)
  src-tauri/           # Backend (Rust + Tauri commands)
  docs/setup_linux.md  # Environment setup steps
```

## Quick start

1. Follow [docs/setup_linux.md](docs/setup_linux.md)
2. From repository root:
   - `make gui-setup`
   - `make gui-check`
   - `make gui-dev`

Alternative (inside this folder):
- `npm install`
- `npm run frontend:build`
- `cd src-tauri && source "$HOME/.cargo/env" && cargo check`
- `npm run dev`

Linux packages:
- `make gui-build-linux` (deb/rpm)

## Stream strategy

- Backend reads at configured `sampleHz`
- Samples are buffered in Rust
- Data is emitted as `telemetry-chunk` every `flushMs` or `chunkSamples`
- Frontend keeps a ring buffer and decimates before plotting

This architecture keeps UI responsive under high sample rates.
