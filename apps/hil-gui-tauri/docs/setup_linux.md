# Linux setup for HIL GUI (Tauri)

This project needs Rust, Node.js and Linux GUI runtime dependencies for Tauri.

## 1) Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup target add x86_64-unknown-linux-gnu
```

## 2) Install Node.js (LTS)

```bash
sudo apt update
sudo apt install -y nodejs npm
```

If your distro package is too old, use `nvm` and install the latest LTS.

## 3) Install Tauri Linux dependencies

```bash
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  libudev-dev \
  librsvg2-dev \
  patchelf
```

## 4) Install frontend deps

From project root (recommended):

```bash
make gui-setup
```

Or from `apps/hil-gui-tauri`:

```bash
npm install
```

## 5) Run the app

From project root:

```bash
make gui-dev
```

For validation from root:

```bash
make gui-check
```

For Linux packages (.deb/.rpm) from root:

```bash
make gui-build-linux
```

Directly from app folder:

```bash
npm run dev
```

## Notes for high-rate HIL streams

- Increase UART baud if telemetry is dense.
- Keep `flushMs` around 30-80 ms.
- Use `chunkSamples` between 16 and 128.
- Tune `sampleHz` to fit link bandwidth.
