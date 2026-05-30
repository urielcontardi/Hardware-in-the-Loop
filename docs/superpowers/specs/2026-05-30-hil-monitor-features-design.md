# HIL Monitor — Pending Features Design

**Date:** 2026-05-30
**Scope:** Four pending items for the HIL Monitor frontend (`apps/hil-go/frontend/src/main.ts`)

---

## 1. Commit current changes

Commit the uncommitted diff (main.ts, styles.css, gateway static bundles) before starting feature work.

No design decisions — just a clean checkpoint commit.

---

## 2. Scroll zoom sensitivity fix

### Problem

The wheel zoom handler applies a fixed multiplicative factor (`1.25` zoom-in, `0.8` zoom-out) to `windowSec` per wheel event. `deltaY` varies widely between input devices: trackpads report fractional values (e.g. 4.5 per finger movement tick), mouse wheels report discrete steps (100 or 120 per notch). The same factor applied to both makes trackpad zoom feel runaway-fast.

### Solution

Normalize `deltaY` into a "notch count" (capped at ±3) and apply a gentler per-notch factor (1.10 ≈ 10% per notch):

```typescript
const notches = Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY) / 100, 3);
const factor = Math.pow(1.10, notches);
```

This replaces the two-branch `e.deltaY > 0 ? 1.25 : 0.8` in `attachPlotNavigation`.

**Effect per device:**
| Device | deltaY typical | notches | factor applied |
|--------|---------------|---------|----------------|
| Mouse wheel (1 notch) | 100 | 1.0 | 1.10 |
| Mouse wheel (fast) | 300 | 3.0 | 1.33 |
| Trackpad (light swipe) | 10 | 0.1 | 1.01 |
| Trackpad (strong swipe) | 80 | 0.8 | 1.08 |

**Change location:** `attachPlotNavigation` → `wheel` event handler (~line 1438).

---

## 3. TL / solver sync architecture review

### Finding

The `TL` (commanded load torque) trace is generated client-side:

```typescript
const tlNow = Number(elTorque.value) || 0;
for (const s of samples) { s.TL = tlNow; }
```

`tlNow` is read from the form at the moment a telemetry batch arrives in the browser. The timestamp in the plot (`tBuf`) is the FPGA hardware counter value embedded in the sample. This creates a small lead artifact: the TL step appears at the hardware timestamp of the first post-change batch rather than at the exact hardware cycle the UDP command was applied.

**Magnitude:** ≤ 1 broadcast cycle = 16 ms. This is below the telemetry sample period (~100 µs × batch size) and visually indistinguishable. The TL trace correctly leads the motor's physical response (currents/speed react after the solver integrates the new torque through the inertia J).

### Decision

No code change. Architecture is correct for display purposes. Documented here for future reference.

---

## 4. Sequential batch runner + run save/load

### 4.1 Batch runner

#### UI

New collapsible panel **"BATCH"** in the Scenarios tab, below the existing SCENARIO RECIPE panel.

```
┌─ BATCH ──────────────────────────────────────────────────────┐
│  Recipe name        End delay   Status                        │
│  [speed_steps  ▾]  [2.0  s]    ○  [×]                       │
│  [torque_test  ▾]  [1.0  s]    ○  [×]                       │
│  [speed_ramp   ▾]  [3.0  s]    ○  [×]                       │
│  [+ Add]              [▶ Run Batch]    [■ Stop Batch]        │
│  Batch: 0/3 · t = 0.0 s                                      │
└──────────────────────────────────────────────────────────────┘
```

- **Recipe name**: `<select>` populated from `localStorage[RECIPE_KEY]` keys. Refreshed when panel is shown.
- **End delay**: seconds to wait after the last recipe event fires before stopping and advancing. Replaces the hardcoded `+ 0.5 s` in the single-scenario runner.
- **Status icons**: ○ pending → ▶ running → ✓ done → ✗ error.
- **Progress line**: current recipe index / total + elapsed wall-clock time.
- **Auto-save**: at the end of each recipe, auto-saves a `.hilbin` file named `<recipe_name>_<YYYYMMDD_HHMMSS>.hilbin`.

#### Execution flow

```
for each item i in batch:
  1. StopController(ip) + ResetSolver(ip)          // clean slate
  2. clearPlotBuffers(); captureTelemetry = capturePwm = false
  3. SetParams + Run(ip)
  4. clearPlotBuffers(); captureTelemetry = capturePwm = true
  5. Schedule recipe events via setTimeout (same as startScenario)
  6. After last_event.t + item.endDelaySec:
       a. StopController(ip) + ResetSolver(ip)
       b. auto-save current buffers → <name>_<ts>.hilbin
       c. mark item status = done
  7. await 500 ms
  8. advance to item i+1
After all items: batchRunning = false; restore UI; status = "Batch complete"
```

Aborting mid-batch (Stop Batch button): stops the timer chain, calls StopController, marks remaining items as cancelled, does NOT auto-save partial run.

#### State

```typescript
type BatchItem = { recipeName: string; endDelaySec: number };
let batchRunning = false;
let batchItems: BatchItem[] = [];
let batchIndex = 0;
let batchTimeouts: number[] = [];
let batchT0 = 0;
let batchProgressTimer: number | null = null;
```

Batch items are stored only in memory (not persisted to localStorage) — the individual recipes are already persisted.

---

### 4.2 Save / Load system

#### New buttons

In the **TELEMETRY** panel, below the existing `[Clear]` button:

```
[💾 Save run]  [📂 Load run]
```

**Save run** — serializes current in-memory buffers (`tBuf`, `samplesBuf`, `pwmEvents`) to `.hilbin` and:
- **Gateway mode**: triggers a browser file download via `URL.createObjectURL(blob)`.
- **Wails mode**: calls new Go method `SaveRun(data []byte, suggestedName string) error` which opens a native save-file dialog.

**Load run** — reads a `.hilbin` file and:
1. Clears current plot buffers and resets epoch tracking.
2. Populates `tBuf`, `samplesBuf`, `pwmEvents` from file data.
3. Sets `paused = true`, `viewEndSec` = last sample timestamp.
4. Shows a metadata badge (run name, date, duration, sample count).
5. Calls `scheduleRender()`.

- **Gateway mode**: hidden `<input type="file" accept=".hilbin">` triggered by button click.
- **Wails mode**: calls new Go method `LoadRun() ([]byte, error)`.

#### Wails Go methods (app.go)

```go
func (a *App) SaveRun(data []byte, suggestedName string) error
func (a *App) LoadRun() ([]byte, error)
```

Both use `runtime.SaveFileDialog` / `runtime.OpenFileDialog`. Wails JS bindings auto-generated.

---

### 4.3 `.hilbin` binary format

See `docs/hilbin-format.md` for the full format specification.

**Summary:**
- Little-endian throughout.
- Fixed magic header for quick identification.
- JSON metadata section (motor params, date, scenario name, counts).
- Two flat binary arrays: telemetry records and PWM records.
- Designed for direct `np.frombuffer` consumption in Python and `DataView` parsing in TypeScript.

---

## Implementation order

1. Commit current changes (prerequisite — clean working tree).
2. Scroll fix (isolated, two-line change).
3. Save/Load system (new UI + serialization logic + Wails methods).
4. Batch runner (builds on Save/Load for auto-save).
