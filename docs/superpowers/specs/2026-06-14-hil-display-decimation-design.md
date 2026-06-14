# HIL Telemetry Display — Faithful Multi-Resolution Rendering

Date: 2026-06-14
Status: Approved design (pre-implementation)

## Problem

The live telemetry charts render fast signals (currents, flux, torque) as
jagged/triangular waveforms and stair-stepped torque, while slow signals
(speed) look clean. Investigation of raw captures proved this is a **display
artifact**, not a solver or initialization bug.

Evidence (decoded `runs/capture_20260614_220142.139.hilbin`, full-rate):

- Raw alpha-beta channels are clean: `Φα/Φβ` second-difference / amplitude
  ratio ~= 0.0002 (smooth sinusoid), ~1704 samples per electrical cycle at
  ~100 kHz, strictly monotonic timestamps, no NaN/Inf, correct scaling
  (`DMA_SCALE = 1/2^28` consistent with the GPIO `MON_SCALE = 1/2^18`).
- So at the timestamps where the GUI shows triangles, the recorded data is a
  clean ~58 Hz sinusoid.

Root causes in the path solver -> front end:

1. **Fixed-size min/max bucket.** The gateway `DisplayReducer` uses
   `displayBucketSize = 1000` samples. At the current 100 kHz DMA source that
   is a 10 ms bucket ~= 0.6 electrical cycle, so min/max collapses each
   half-cycle to a min and a max -> the triangle. The bucket was sized for an
   older ~10 kHz source.
2. **Derived channels reconstructed after decimation.** `Te`, `Ia/Ib/Ic`,
   `Φa/Φb/Φc` are computed in the front end from the min/max-selected alpha/beta
   extrema. Because `Te = 1.5·npp·(Lm/Lr)·(Φα·Iβ − Φβ·Iα)` is nonlinear, and
   at an `Iα` extreme `Iβ ~= 0`, the displayed torque envelope is biased/wrong
   -> the stair-stepped torque.
3. **Buffer-size mismatch.** Gateway full-rate `rawbuf` holds 300_000 samples
   (~3 s), but the GUI requests `MAX_SAMPLES = 600_000` (~6 s). The 3-6 s
   window is always served by the reduced stream even when the user expects
   full detail.

Secondary (real, in the data, out of scope for this spec): the underlying
signal genuinely has large `Te` swing (-275..+200 N·m), ~1 kHz current ripple
(carrier), and ~77 A peak currents. These are simulation/tuning concerns, not
display bugs.

## Goal

Render telemetry the way a commercial HIL logger (dSPACE ControlDesk,
OPAL-RT) does:

- Faithful waveform shape and amplitude at **any zoom level**.
- **Full-rate zoom at any point in the live session history (minutes back).**
- Derived channels (`Te`, `Ia/Ib/Ic`, `Φa/Φb/Φc`) faithful at every zoom.
- Honest rendering: a decimated view shows a min/max envelope band; zooming in
  resolves to the real trace.

## Non-goals

- No change to the RTL solver or FPGA bitstream.
- No change to the on-the-wire PS telemetry protocol or the `.hilbin` file
  format.
- Not addressing the underlying torque/speed/current ripple magnitude (that is
  a model-tuning topic, tracked separately).

## Key decisions

- **Disk is the source of truth.** The whole live session is streamed full-rate
  to disk continuously (Run -> Stop), reusing the existing `record` writer.
  The live chart is a window onto that on-disk stream. Cost ~= 2.4 MB/s.
- **Retention: whole session** kept on disk until Stop, with a safety guardrail
  (default 30 min / ~4 GB, configurable) that warns and rotates the oldest
  segment only for runaway-length sessions.
- **`Record/Save` is promotion, not start.** The session always records; the
  button keeps/names the session file so it is not recycled on the next Run.
- **Derived channels computed in the gateway** from alpha-beta at full rate
  (numerically identical to a firmware-computed `Te`), so no protocol/bitstream
  change. Disk stores only solver-native channels (`t, Iα, Iβ, Φα, Φβ, speed`);
  `Te`/abc are recomputed on read.
- **Viewport-driven decimation.** Decimation is a function of the visible
  window and pixel width, recomputed on every pan/zoom — one (min, max) pair
  per pixel column — never a fixed sample bucket.

## Architecture

```
FPGA (100 kHz alpha-beta) -> UDP -> Gateway
  receiver (full-rate)
    +- derive channels (Te, Ia/Ib/Ic, Φa/Φb/Φc) per sample
    +- session store on disk (.hilbin, whole session) + sparse time->offset index
    +- RAM overview tier (min/max, ~50 ms buckets, whole session, all channels)
    +- recent RAM ring (live tail, zero-I/O recent zoom)
  HTTP
    GET /api/series?from&to&width&channels&session  (viewport query)
    GET /api/tail?cursor                            (live moving edge)
Frontend (uPlot)
  pan/zoom -> debounced /api/series at viewport pixel width
  live tail -> /api/tail, auto-scroll when pinned to "now"
  render: min/max envelope band when decimated; real line when full-rate
```

## Components

### 1. Ingestion + derived channels
- Location: gateway, in/after `receiver.SetSampleHandler` (already full-rate).
- For each sample compute, before any decimation:
  - `Te = 1.5·npp·(Lm/Lr_total)·(Φα·Iβ − Φβ·Iα)` using the motor params the
    gateway already tracks (`lastMotor`); fall back to firmware defaults if
    unset.
  - Inverse Clarke (amplitude-invariant): `Ia=Iα`, `Ib=−Iα/2+(√3/2)·Iβ`,
    `Ic=−Iα/2−(√3/2)·Iβ`; same for flux.
- Derived values feed the overview tier and are recomputed on disk reads. They
  are NOT written to disk.

### 2. Session store on disk + sparse index
- Reuse the `record` package writer; make it always-on from Run to Stop,
  writing the session file in `runs/`.
- File format unchanged (`HILDATA` header + full-rate alpha-beta records).
- Sparse `time -> file offset` index in RAM, one entry per block (e.g. every
  4096 samples), enabling O(log n) seek by time.
- Guardrail: when the session exceeds the configured cap, warn and rotate the
  oldest segment.
- `Save/Record` promotes (renames/marks) the session so it is retained.

### 3. RAM overview tier + recent ring
- One min/max overview tier, ~50 ms buckets, every channel including derived,
  covering the whole session. Bounded (a few MB/hour).
- Short recent full-rate ring for the live tail and zero-I/O recent deep zoom.

### 4. Query API
- `GET /api/series?from&to&width&channels&session`:
  - If window is coarser than the overview bucket -> serve from overview tier.
  - Else -> seek + read the full-rate range from disk (or recent ring),
    compute derived channels, and decimate to `width` columns as (min, max)
    pairs; return raw samples if the window holds <= ~2·width full-rate points.
  - Binary response encoding (follow `rawbuf.Encode` style).
- `GET /api/tail?cursor`: returns full-rate samples since the cursor for the
  moving right edge (reuse the rawbuf cursor concept).
- Intermediate disk-resident tiers are a **deferred optimization**, added only
  if profiling shows mid-range zoom (seconds-wide windows) reads too many
  samples per query.

### 5. Frontend viewport rendering
- uPlot zoom/pan hook: debounce ~60 ms, compute visible `[t0,t1]` and plot
  pixel width, query `/api/series`, update series.
- Live tail via `/api/tail`, auto-scroll when pinned to "now".
- Representation by zoom: decimated -> min/max envelope band; full-rate ->
  real line. A channel switches representation as zoom changes.
- Remove the buggy paths: gateway `DisplayReducer` SSE stream, and the
  front-end overview/min-max-on-alpha-beta-then-reconstruct logic in `main.ts`.

## Data flow on a zoom-in to old data
1. User zooms to a window 12 minutes back.
2. Front end fires `/api/series?from=t0&to=t1&width=1500`.
3. Gateway binary-searches the sparse index -> file offset; reads only that
   viewport's byte range.
4. Gateway computes `Te`/abc on those samples; returns full-rate if small,
   else 1500 (min, max) pairs.
5. uPlot renders the real sine (full-rate) or the envelope band (decimated).

## Error handling
- Query for a time range outside the retained session -> empty result + clear
  status, no crash.
- Disk read/seek error -> error surfaced to the front end; chart keeps last
  good view.
- Missing motor params -> derived channels use firmware defaults; surface a
  hint that `Te` may be approximate until a motor model is applied.
- Guardrail rotation while a query targets a rotated range -> return the
  retained subset + a "history truncated" marker.

## Testing
- Go unit tests:
  - Sparse index seek correctness across a real fixture file.
  - Overview tier min/max correctness vs brute-force.
  - Query resolution selection (window/width -> overview vs disk vs raw).
  - Derived-channel formulas vs golden values.
  - Guardrail rotation behavior.
  - Fixtures: existing captures (`cenario1_*.hilbin`, etc.).
- Key regression test: a synthetic 100 kHz sinusoid ->
  - wide-window `/api/series` returns an envelope whose amplitude matches the
    sinusoid (no triangle collapse);
  - narrow-window `/api/series` returns the real sine within tolerance.
- Front-end tests: viewport -> query-param mapping; representation-by-zoom
  selection.

## Compatibility / migration
- `.hilbin` format unchanged; old captures load and derive `Te`/abc on read.
- CSV export uses the same derived-channel computation.
- Removed: gateway `DisplayReducer` SSE path; front-end fixed-bucket overview
  and alpha-beta-extrema reconstruction.

## Open implementation risks (to validate during the plan)
- Mid-range zoom query cost (seconds-wide windows reading millions of samples).
  Mitigation order: sequential bounded reads + debounce first; add intermediate
  tiers only if profiling requires.
- Disk throughput on the target host for sustained 2.4 MB/s plus query reads.
