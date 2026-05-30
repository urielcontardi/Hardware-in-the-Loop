# HIL Monitor Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix scroll sensitivity, add save/load of run data (.hilbin), and add sequential batch scenario runner.

**Architecture:** All logic lives in `apps/hil-go/frontend/src/main.ts` (TypeScript/uPlot frontend). Wails file I/O goes through two new Go methods in `app.go`. Gateway mode uses browser-native Blob download + file input.

**Tech Stack:** TypeScript, uPlot, Wails v2 (Go backend), Vite build

---

## Files

- Modify: `apps/hil-go/frontend/src/main.ts` — all feature logic + UI HTML
- Modify: `apps/hil-go/app.go` — two new Go methods (SaveRun, LoadRun)
- Modify: `apps/hil-go/frontend/wailsjs/go/main/App.js` — add JS bindings
- Modify: `apps/hil-go/frontend/wailsjs/go/main/App.d.ts` — add TS declarations

---

## Task 1: Scroll sensitivity fix

**Files:** Modify `apps/hil-go/frontend/src/main.ts`

- [ ] In `attachPlotNavigation` (~line 1438), replace:
  ```typescript
  const factor = e.deltaY > 0 ? 1.25 : 0.8;
  ```
  with:
  ```typescript
  const notches = Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY) / 100, 3);
  const factor = Math.pow(1.10, notches);
  ```

- [ ] Commit:
  ```bash
  git add apps/hil-go/frontend/src/main.ts
  git commit -m "fix(frontend): reduce scroll zoom sensitivity — 10% per notch, normalized for trackpad"
  ```

---

## Task 2: Add Wails Go methods for file I/O

**Files:** Modify `apps/hil-go/app.go`

- [ ] Add imports `"encoding/base64"` and `"os"` to app.go imports block.

- [ ] Add at the end of app.go:
  ```go
  // SaveRun opens a native save dialog and writes the provided base64-encoded
  // .hilbin data to the chosen path.
  func (a *App) SaveRun(dataB64 string, suggestedName string) error {
  	data, err := base64.StdEncoding.DecodeString(dataB64)
  	if err != nil {
  		return err
  	}
  	path, err := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{
  		DefaultFilename: suggestedName,
  		Filters: []runtime.FileFilter{
  			{DisplayName: "HIL Run (*.hilbin)", Pattern: "*.hilbin"},
  		},
  	})
  	if err != nil || path == "" {
  		return err
  	}
  	return os.WriteFile(path, data, 0644)
  }

  // LoadRun opens a native open dialog and returns the chosen file's contents
  // as a base64-encoded string.
  func (a *App) LoadRun() (string, error) {
  	path, err := runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
  		Filters: []runtime.FileFilter{
  			{DisplayName: "HIL Run (*.hilbin)", Pattern: "*.hilbin"},
  		},
  	})
  	if err != nil || path == "" {
  		return "", err
  	}
  	data, err := os.ReadFile(path)
  	if err != nil {
  		return "", err
  	}
  	return base64.StdEncoding.EncodeToString(data), nil
  }
  ```

- [ ] Update Wails JS bindings — append to `wailsjs/go/main/App.js`:
  ```javascript
  export function SaveRun(arg1, arg2) {
    return window['go']['main']['App']['SaveRun'](arg1, arg2);
  }

  export function LoadRun() {
    return window['go']['main']['App']['LoadRun']();
  }
  ```

- [ ] Update Wails TS declarations — append to `wailsjs/go/main/App.d.ts`:
  ```typescript
  export function SaveRun(arg1:string, arg2:string):Promise<void>;

  export function LoadRun():Promise<string>;
  ```

- [ ] Commit:
  ```bash
  git add apps/hil-go/app.go apps/hil-go/frontend/wailsjs/go/main/App.js apps/hil-go/frontend/wailsjs/go/main/App.d.ts
  git commit -m "feat(wails): add SaveRun/LoadRun Go methods for native file dialogs"
  ```

---

## Task 3: Save/Load system in frontend

**Files:** Modify `apps/hil-go/frontend/src/main.ts`

### 3a — Extend HilApi type

- [ ] In the `HilApi` type definition (around line 37), add:
  ```typescript
  SaveRun?(dataB64: string, name: string): Promise<void>;
  LoadRun?(): Promise<string>;
  ```

### 3b — Add SaveRun/LoadRun to Wails api object

- [ ] In the `isWails` api block, add:
  ```typescript
  SaveRun: WailsApp.SaveRun as HilApi["SaveRun"],
  LoadRun: WailsApp.LoadRun as HilApi["LoadRun"],
  ```

### 3c — Add buttons to TELEMETRY panel HTML

- [ ] In the DOM HTML template, in the TELEMETRY panel section (after the `[Clear]` button row):
  ```html
  <div class="btn-row" style="margin-top:6px">
    <button id="btn-save-run" class="btn btn-sm">Save run</button>
    <button id="btn-load-run" class="btn btn-sm">Load run</button>
  </div>
  <input id="load-file-input" type="file" accept=".hilbin" style="display:none" />
  <div id="run-meta-badge" class="run-meta-badge hidden"></div>
  ```

### 3d — Add DOM refs

- [ ] After existing DOM refs section, add:
  ```typescript
  const elBtnSaveRun    = document.querySelector<HTMLButtonElement>("#btn-save-run")!;
  const elBtnLoadRun    = document.querySelector<HTMLButtonElement>("#btn-load-run")!;
  const elLoadFileInput = document.querySelector<HTMLInputElement>("#load-file-input")!;
  const elRunMetaBadge  = document.querySelector<HTMLDivElement>("#run-meta-badge")!;
  ```

### 3e — Add serializeHilbin function

- [ ] Add this function before the button handlers section:
  ```typescript
  function serializeHilbin(name: string): ArrayBuffer {
    const meta = JSON.stringify({
      version: 1,
      date: new Date().toISOString(),
      name,
      sample_count: tBuf.length,
      pwm_count: pwmEvents.length,
      npp: motorNpp,
      motor: {
        rs: Number(elMotorRs.value), rr: Number(elMotorRr.value),
        ls: Number(elMotorLs.value), lr: Number(elMotorLr.value),
        lm: Number(elMotorLm.value), j:  Number(elMotorJ.value),
      },
    });
    const metaBytes = new TextEncoder().encode(meta);
    const jsonSize  = metaBytes.length;
    const rawBase   = 12 + jsonSize;
    const alignBase = (rawBase + 7) & ~7;

    const telemBytes = tBuf.length * 28;
    const pwmBytes   = pwmEvents.length * 8;
    const total = alignBase + 4 + telemBytes + 4 + pwmBytes;

    const buf  = new ArrayBuffer(total);
    const view = new DataView(buf);
    const u8   = new Uint8Array(buf);

    // Magic "HILDATA\x01"
    "HILDATA".split('').forEach((c, i) => { u8[i] = c.charCodeAt(0); });
    u8[7] = 1;

    view.setUint32(8, jsonSize, true);
    u8.set(metaBytes, 12);

    let off = alignBase;
    view.setUint32(off, tBuf.length, true); off += 4;
    for (let i = 0; i < tBuf.length; i++) {
      const s = samplesBuf[i];
      view.setFloat32(off,      tBuf[i],     true);
      view.setFloat32(off +  4, s.Ia,        true);
      view.setFloat32(off +  8, s.Ib,        true);
      view.setFloat32(off + 12, s.FluxA,     true);
      view.setFloat32(off + 16, s.FluxB,     true);
      view.setFloat32(off + 20, s.Speed,     true);
      view.setFloat32(off + 24, s.TL ?? 0,   true);
      off += 28;
    }

    view.setUint32(off, pwmEvents.length, true); off += 4;
    for (const ev of pwmEvents) {
      view.setFloat32(off, ev.t_sec, true);
      view.setInt8(off + 4, ev.a);
      view.setInt8(off + 5, ev.b);
      view.setInt8(off + 6, ev.c);
      view.setUint8(off + 7, 0);
      off += 8;
    }

    return buf;
  }
  ```

### 3f — Add deserializeHilbin function

- [ ] Add after `serializeHilbin`:
  ```typescript
  function deserializeHilbin(buf: ArrayBuffer): { name: string; date: string; sampleCount: number; pwmCount: number } {
    const u8   = new Uint8Array(buf);
    const view = new DataView(buf);

    const magic = String.fromCharCode(...u8.slice(0, 7));
    if (magic !== "HILDATA") throw new Error("Not a valid .hilbin file");

    const jsonSize  = view.getUint32(8, true);
    const metaStr   = new TextDecoder().decode(u8.slice(12, 12 + jsonSize));
    const meta      = JSON.parse(metaStr);

    const rawBase   = 12 + jsonSize;
    const alignBase = (rawBase + 7) & ~7;
    let off = alignBase;

    const telemCount = view.getUint32(off, true); off += 4;

    resetPlotBuffer();
    paused = true;

    for (let i = 0; i < telemCount; i++) {
      const t     = view.getFloat32(off,      true);
      const Ia    = view.getFloat32(off +  4, true);
      const Ib    = view.getFloat32(off +  8, true);
      const FluxA = view.getFloat32(off + 12, true);
      const FluxB = view.getFloat32(off + 16, true);
      const Speed = view.getFloat32(off + 20, true);
      const TL    = view.getFloat32(off + 24, true);
      off += 28;

      tBuf.push(t);
      samplesBuf.push({ Ia, Ib, FluxA, FluxB, Speed, TL });
      sampleCount++;
    }

    const pwmCount = view.getUint32(off, true); off += 4;
    for (let i = 0; i < pwmCount; i++) {
      const t_sec = view.getFloat32(off,     true);
      const a     = view.getInt8(off + 4);
      const b     = view.getInt8(off + 5);
      const c     = view.getInt8(off + 6);
      off += 8;
      pwmEvents.push({ t_cycles: 0, a, b, c, mask: 0, epoch: 0, t_sec });
    }

    if (tBuf.length > 0) viewEndSec = tBuf[tBuf.length - 1];

    scheduleRender();
    return { name: meta.name ?? "", date: meta.date ?? "", sampleCount: telemCount, pwmCount };
  }
  ```

### 3g — Add save/load helpers and button handlers

- [ ] Add helper functions:
  ```typescript
  function arrayBufferToBase64(buf: ArrayBuffer): string {
    const bytes = new Uint8Array(buf);
    let binary = "";
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    }
    return btoa(binary);
  }

  function base64ToArrayBuffer(b64: string): ArrayBuffer {
    const binary = atob(b64);
    const bytes  = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  async function triggerSave(name: string) {
    const buf      = serializeHilbin(name);
    const filename = name.endsWith(".hilbin") ? name : name + ".hilbin";
    if (isWails && api.SaveRun) {
      await api.SaveRun(arrayBufferToBase64(buf), filename);
    } else {
      const blob = new Blob([buf], { type: "application/octet-stream" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    }
  }

  function showRunMetaBadge(meta: { name: string; date: string; sampleCount: number; pwmCount: number }) {
    const d = meta.date ? new Date(meta.date).toLocaleString() : "unknown date";
    elRunMetaBadge.textContent = `Loaded: "${meta.name}" · ${d} · ${meta.sampleCount.toLocaleString()} samples · ${meta.pwmCount.toLocaleString()} PWM events`;
    elRunMetaBadge.classList.remove("hidden");
  }
  ```

- [ ] Add button event handlers (near the other button handlers at the bottom):
  ```typescript
  elBtnSaveRun.addEventListener("click", () => withButton(elBtnSaveRun, async () => {
    const name = `hil_run_${new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}`;
    await triggerSave(name);
    setStatus("Run saved", "ok");
  }));

  elBtnLoadRun.addEventListener("click", () => {
    if (isWails && api.LoadRun) {
      withButton(elBtnLoadRun, async () => {
        const b64 = await api.LoadRun!();
        if (!b64) return;
        const meta = deserializeHilbin(base64ToArrayBuffer(b64));
        showRunMetaBadge(meta);
        setStatus(`Loaded: ${meta.name} (${meta.sampleCount.toLocaleString()} samples)`, "ok");
      });
    } else {
      elLoadFileInput.click();
    }
  });

  elLoadFileInput.addEventListener("change", () => {
    const file = elLoadFileInput.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const meta = deserializeHilbin(reader.result as ArrayBuffer);
        showRunMetaBadge(meta);
        setStatus(`Loaded: ${meta.name} (${meta.sampleCount.toLocaleString()} samples)`, "ok");
      } catch (e) {
        setStatus(`Load failed: ${e}`, "error");
      }
      elLoadFileInput.value = "";
    };
    reader.readAsArrayBuffer(file);
  });
  ```

### 3h — Add CSS for run-meta-badge

- [ ] In `styles.css`, add:
  ```css
  .run-meta-badge {
    margin-top: 6px;
    padding: 4px 8px;
    background: #0e1d30;
    border: 1px solid #1e3a5f;
    border-radius: 4px;
    font-size: 10px;
    color: #7bafd4;
    line-height: 1.4;
  }
  .run-meta-badge.hidden { display: none; }
  ```

- [ ] Commit:
  ```bash
  git add apps/hil-go/frontend/src/main.ts apps/hil-go/frontend/src/styles.css
  git commit -m "feat(frontend): add save/load run system (.hilbin format) with Wails and gateway support"
  ```

---

## Task 4: Batch Runner

**Files:** Modify `apps/hil-go/frontend/src/main.ts`

### 4a — New types and state

- [ ] After existing scenario state variables (~line 795), add:
  ```typescript
  type BatchItem = { recipeName: string; endDelaySec: number };
  let batchRunning = false;
  let batchItems: BatchItem[] = [];
  let batchIndex  = 0;
  let batchTimeouts: number[] = [];
  let batchT0 = 0;
  let batchProgressTimer: number | null = null;
  ```

### 4b — Add BATCH panel HTML

- [ ] In the DOM HTML, in the `data-tab-panel="scenario"` div, **after** the closing `</section>` of the SCENARIO RECIPE panel, add:
  ```html
  <section class="panel">
    <div class="panel-title">BATCH</div>
    <div id="batch-table" class="scenario-table" aria-label="Batch recipe list">
      <div class="scenario-head">
        <span>Recipe</span>
        <span>End delay (s)</span>
        <span>Status</span>
        <span></span>
      </div>
    </div>
    <div class="btn-row" style="margin-top:6px">
      <button id="btn-add-batch-item" class="btn btn-sm" type="button">+ Add</button>
      <button id="btn-batch-run"  class="btn btn-sm" type="button">Run Batch</button>
      <button id="btn-batch-stop" class="btn btn-sm btn-danger" type="button" disabled>Stop Batch</button>
    </div>
    <span id="batch-progress" class="scenario-progress"></span>
  </section>
  ```

### 4c — Add DOM refs

- [ ] Add after existing DOM refs:
  ```typescript
  const elBatchTable      = document.querySelector<HTMLDivElement>("#batch-table")!;
  const elBtnAddBatchItem = document.querySelector<HTMLButtonElement>("#btn-add-batch-item")!;
  const elBtnBatchRun     = document.querySelector<HTMLButtonElement>("#btn-batch-run")!;
  const elBtnBatchStop    = document.querySelector<HTMLButtonElement>("#btn-batch-stop")!;
  const elBatchProgress   = document.querySelector<HTMLSpanElement>("#batch-progress")!;
  ```

### 4d — Batch helper functions

- [ ] Add before the button handlers section:

  ```typescript
  // ── Batch runner ──────────────────────────────────────────────────────────────
  function getSavedRecipeNames(): string[] {
    try {
      return Object.keys(JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}"));
    } catch { return []; }
  }

  function getRecipeByName(name: string): { t: number; target: string; param: string; value: number }[] | null {
    try {
      const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
      return all[name] ?? null;
    } catch { return null; }
  }

  function addBatchRow(preset?: BatchItem): HTMLElement {
    const names  = getSavedRecipeNames();
    const opts   = names.map(n => `<option${n === preset?.recipeName ? " selected" : ""}>${n}</option>`).join("") ||
                   `<option>${preset?.recipeName ?? "no recipes saved"}</option>`;
    const row    = document.createElement("div");
    row.className = "scenario-row";
    row.innerHTML = `
      <select class="write-input">${opts}</select>
      <input type="number" value="${preset?.endDelaySec ?? 2}" min="0" step="0.5" class="write-input" style="width:72px" />
      <span class="batch-status">○</span>
      <button class="scenario-remove" type="button" title="Remove">×</button>`;
    row.querySelector<HTMLButtonElement>(".scenario-remove")
      ?.addEventListener("click", () => { if (!batchRunning) row.remove(); });
    elBatchTable.appendChild(row);
    return row;
  }

  function readBatchItems(): BatchItem[] {
    return Array.from(elBatchTable.querySelectorAll<HTMLElement>(".scenario-row")).map(row => ({
      recipeName:  row.querySelector<HTMLSelectElement>("select")!.value,
      endDelaySec: Number(row.querySelector<HTMLInputElement>("input")!.value) || 2,
    }));
  }

  function setBatchItemStatus(rowIndex: number, status: "pending" | "running" | "done" | "error") {
    const rows = elBatchTable.querySelectorAll<HTMLElement>(".scenario-row");
    const span = rows[rowIndex]?.querySelector<HTMLSpanElement>(".batch-status");
    if (!span) return;
    const icons: Record<string, string> = { pending: "○", running: "▶", done: "✓", error: "✗" };
    span.textContent = icons[status] ?? "○";
  }

  function stopBatch() {
    batchRunning = false;
    batchTimeouts.forEach(clearTimeout);
    batchTimeouts = [];
    if (batchProgressTimer !== null) { clearInterval(batchProgressTimer); batchProgressTimer = null; }
    elBatchProgress.textContent = "";
    elBtnBatchRun.disabled  = false;
    elBtnBatchStop.disabled = true;
    elBtnAddBatchItem.disabled = false;
    elBatchTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
      .forEach(b => { b.disabled = false; });
  }

  function batchSleep(ms: number): Promise<void> {
    return new Promise(resolve => {
      const tid = window.setTimeout(resolve, ms);
      batchTimeouts.push(tid);
    });
  }

  async function runBatchSequence() {
    const ip = elIp.value.trim();
    if (!ip) { setStatus("Missing board IP", "error"); stopBatch(); return; }

    try {
      const found = await api.DiscoverBoard(ip) as DiscoveryResponse;
      applyBoardIP(found.ip || ip);
      rememberBoardIP(found.ip || ip);
    } catch { /* proceed with stored IP */ }

    const items = readBatchItems();

    for (let i = 0; i < items.length; i++) {
      if (!batchRunning) break;
      batchIndex = i;
      elBatchProgress.textContent = `Batch: ${i + 1}/${items.length}`;
      setBatchItemStatus(i, "running");

      const item = items[i];
      const events = getRecipeByName(item.recipeName);
      if (!events) {
        setBatchItemStatus(i, "error");
        setStatus(`Recipe "${item.recipeName}" not found`, "error");
        break;
      }

      try {
        // Clean state
        await api.StopController(ip);
        await api.ResetSolver(ip);
        captureTelemetry = false;
        capturePwm = false;
        resetPlotBuffer();

        // Start
        const p = readParams();
        await api.SetParams(ip, p.freq, p.vdc, p.torque, p.baseFreq, p.maxVPu, p.accelTime, false, false, true);
        await api.Run(ip);
        resetPlotBuffer();
        captureTelemetry = true;
        capturePwm = true;

        // Execute events
        const sorted = [...events].sort((a, b) => a.t - b.t);
        const lastT  = sorted.length ? sorted[sorted.length - 1].t : 0;
        sorted.forEach(ev => {
          const tid = window.setTimeout(() => dispatchScenarioEvent(ev), ev.t * 1000);
          batchTimeouts.push(tid);
        });
        await batchSleep((lastT + item.endDelaySec) * 1000);

        if (!batchRunning) break;

        // Stop and save
        await api.StopController(ip);
        await api.ResetSolver(ip);
        captureTelemetry = false;
        capturePwm = false;

        const ts  = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
        const runName = `${item.recipeName}_${ts}`;
        await triggerSave(runName);

        setBatchItemStatus(i, "done");
        setStatus(`Saved: ${runName}.hilbin`, "ok");
      } catch (e) {
        setBatchItemStatus(i, "error");
        setStatus(`Batch item ${i + 1} failed: ${e}`, "error");
        break;
      }

      await batchSleep(500);
    }

    stopBatch();
    if (batchRunning === false && batchIndex >= items.length - 1) {
      setStatus("Batch complete", "ok");
    }
  }

  async function startBatch() {
    if (batchRunning) return;
    const items = readBatchItems();
    if (items.length === 0) { elBatchProgress.textContent = "Add items first"; return; }

    batchRunning = true;
    batchT0      = performance.now();
    batchIndex   = 0;
    batchTimeouts = [];

    elBtnBatchRun.disabled     = true;
    elBtnBatchStop.disabled    = false;
    elBtnAddBatchItem.disabled = true;
    elBatchTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
      .forEach(b => { b.disabled = true; });

    // reset all status icons
    elBatchTable.querySelectorAll<HTMLElement>(".scenario-row").forEach((_, i) => setBatchItemStatus(i, "pending"));

    batchProgressTimer = window.setInterval(() => {
      const elapsed = ((performance.now() - batchT0) / 1000).toFixed(1);
      const items   = readBatchItems();
      elBatchProgress.textContent = `Batch: ${batchIndex + 1}/${items.length} · t=${elapsed}s`;
    }, 200);

    runBatchSequence().finally(() => {
      if (batchProgressTimer !== null) { clearInterval(batchProgressTimer); batchProgressTimer = null; }
      elBtnBatchRun.disabled = false;
    });
  }
  ```

### 4e — Wire up batch buttons

- [ ] After the existing `elBtnRecipeRun.addEventListener` line, add:
  ```typescript
  elBtnAddBatchItem.addEventListener("click", () => { if (!batchRunning) addBatchRow(); });
  elBtnBatchRun.addEventListener("click", startBatch);
  elBtnBatchStop.addEventListener("click", () => {
    stopBatch();
    const ip = elIp.value.trim();
    if (ip) api.StopController(ip).catch(() => {});
  });
  ```

- [ ] Commit:
  ```bash
  git add apps/hil-go/frontend/src/main.ts
  git commit -m "feat(frontend): add sequential batch runner with auto-save per scenario"
  ```

---

## Task 5: Build and smoke test

- [ ] Build frontend:
  ```bash
  cd apps/hil-go/frontend && npm run build
  ```
  Expected: no TypeScript errors, dist rebuilt.

- [ ] Copy new dist into gateway static:
  ```bash
  cp -r apps/hil-go/frontend/dist/* apps/hil-go/cmd/gateway/static/
  ```

- [ ] Commit bundles:
  ```bash
  git add apps/hil-go/cmd/gateway/static
  git commit -m "build(gateway): update embedded frontend bundle"
  ```
