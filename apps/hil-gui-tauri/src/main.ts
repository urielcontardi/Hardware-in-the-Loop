import "uplot/dist/uPlot.min.css";
import "./styles.css";

import uPlot from "uplot";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type TelemetrySample = { t_ms: number; regs: number[] };

type StreamConfig = {
  portName: string;
  baudRate: number;
  sampleHz: number;
  flushMs: number;
  chunkSamples: number;
  dataWidth: number;
};

// ─────────────────────────────────────────────────────────────────────────────
// Channel definitions
// ─────────────────────────────────────────────────────────────────────────────
const FP_SCALE = 268_435_456; // 2^28  (Q14.28)

const CHANNELS = [
  { name: "VDC_BUS",     unit: "V",     color: "#4fc3f7" },
  { name: "TORQUE_LOAD", unit: "N·m",   color: "#ffb74d" },
  { name: "VA_MOTOR",    unit: "V",     color: "#81c784" },
  { name: "VB_MOTOR",    unit: "V",     color: "#ce93d8" },
  { name: "VC_MOTOR",    unit: "V",     color: "#4dd0e1" },
  { name: "I_ALPHA",     unit: "A",     color: "#fff176" },
  { name: "I_BETA",      unit: "A",     color: "#ef9a9a" },
  { name: "FLUX_ALPHA",  unit: "Wb",    color: "#80cbc4" },
  { name: "FLUX_BETA",   unit: "Wb",    color: "#b39ddb" },
  { name: "SPEED_MECH",  unit: "rad/s", color: "#ffcc80" },
] as const;

const N_CH = CHANNELS.length;

// ─────────────────────────────────────────────────────────────────────────────
// Application state
// ─────────────────────────────────────────────────────────────────────────────
const samples: TelemetrySample[] = [];
const MAX_SAMPLES = 60_000;
let latestRegs = new Array<number>(N_CH).fill(0);
let visibleChannels = new Array<boolean>(N_CH).fill(true);
let renderPending = false;

let cfg = { baudRate: 115200, sampleHz: 80, flushMs: 50, chunkSamples: 32, dataWidth: 42 };

// ─────────────────────────────────────────────────────────────────────────────
// DOM scaffold
// ─────────────────────────────────────────────────────────────────────────────
const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <header class="topbar">
    <div class="topbar-brand">
      <img src="/lse_logo.png" alt="LSE" class="app-logo" />
      <div>
        <span class="app-name">HIL Monitor</span>
        <span class="app-sub">Hardware-in-the-Loop</span>
      </div>
    </div>
    <div class="topbar-right">
      <div id="stream-badge" class="badge badge-idle">● IDLE</div>
      <button id="btn-settings" class="icon-btn" title="Stream settings">⚙</button>
    </div>
  </header>

  <div class="workspace">
    <!-- ── SIDEBAR ── -->
    <aside class="sidebar">

      <section class="panel">
        <div class="panel-title">SERIAL CONNECTION</div>
        <div class="conn-row">
          <select id="port" class="port-select"></select>
          <button id="refreshPorts" class="icon-btn" title="Refresh ports">↺</button>
        </div>
        <div class="btn-row">
          <button id="startStream" class="btn btn-primary">▶ Start</button>
          <button id="stopStream" class="btn btn-danger">■ Stop</button>
        </div>
      </section>

      <section class="panel panel-channels">
        <div class="panel-title">
          CHANNELS
          <span class="panel-title-actions">
            <button id="checkAll"   class="link-btn">all</button>
            <span class="sep">/</span>
            <button id="uncheckAll" class="link-btn">none</button>
          </span>
        </div>
        <div id="channelList" class="channel-list"></div>
      </section>

      <section class="panel">
        <div class="panel-title">WRITE REGISTERS</div>
        <div class="write-row">
          <label>VDC_BUS</label>
          <input id="vdc"    type="number" value="320.0" step="any" class="write-input" />
          <span class="write-unit">V</span>
          <button id="writeVdc"    class="btn btn-write">↑</button>
        </div>
        <div class="write-row">
          <label>TORQUE</label>
          <input id="torque" type="number" value="0.0"   step="any" class="write-input" />
          <span class="write-unit">N·m</span>
          <button id="writeTorque" class="btn btn-write">↑</button>
        </div>
      </section>

      <section class="panel panel-ps">
        <div class="panel-title">
          PS CONTROL
          <span id="ps-badge" class="ps-badge ps-badge-off">OFF</span>
        </div>

        <div class="field-inline">
          <label>Board IP</label>
          <input id="ps-ip" type="text" value="192.168.15.13" class="write-input" placeholder="192.168.x.x" />
        </div>

        <div class="field-inline">
          <label>Freq (Hz)</label>
          <input id="ps-freq" type="number" value="60" min="1" max="200" step="1" class="write-input" />
        </div>

        <div class="field-inline">
          <label>Vdc (V)</label>
          <input id="ps-vdc" type="number" value="311" min="0" max="600" step="1" class="write-input" />
        </div>

        <div class="field-inline">
          <label>Torque (N·m)</label>
          <input id="ps-torque" type="number" value="0" min="-50" max="50" step="0.1" class="write-input" />
        </div>

        <div class="field-inline">
          <label>Enable</label>
          <label class="toggle">
            <input id="ps-enable" type="checkbox" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="btn-row">
          <button id="ps-set"  class="btn btn-primary">▶ Set</button>
          <button id="ps-get"  class="btn btn-write">↓ Get</button>
          <button id="ps-stop" class="btn btn-danger">■ Stop</button>
        </div>

        <div class="field-inline">
          <label>Monitor</label>
          <label class="toggle">
            <input id="ps-monitor" type="checkbox" />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div id="ps-telemetry" class="ps-telemetry hidden">
          <div class="ps-telem-row"><span class="ps-telem-label">Speed</span>    <span id="pt-speed">—</span> <span class="ps-telem-unit">rad/s</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Iα</span>       <span id="pt-ia">—</span>    <span class="ps-telem-unit">A</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Iβ</span>       <span id="pt-ib">—</span>    <span class="ps-telem-unit">A</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Φα</span>       <span id="pt-fa">—</span>    <span class="ps-telem-unit">Wb</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Φβ</span>       <span id="pt-fb">—</span>    <span class="ps-telem-unit">Wb</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Freq</span>     <span id="pt-freq">—</span>  <span class="ps-telem-unit">Hz</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Vdc</span>      <span id="pt-vdc">—</span>   <span class="ps-telem-unit">V</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Enable</span>   <span id="pt-en">—</span></div>
        </div>
      </section>

      <div id="status" class="status-bar">● Idle</div>
    </aside>

    <!-- ── PLOT AREA ── -->
    <main class="plot-area">
      <div class="plot-toolbar">
        <button id="clearPlot" class="btn btn-sm">Clear</button>
        <span id="plot-info" class="plot-info">0 samples</span>
      </div>
      <div id="plot" class="plot-container"></div>
    </main>
  </div>

  <!-- ── SETTINGS MODAL ── -->
  <div id="settings-modal" class="modal-overlay hidden">
    <div class="modal-box">
      <div class="modal-header">
        <span>⚙ Stream Settings</span>
        <button id="closeSettings" class="icon-btn">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>Baud Rate</label>
          <input id="cfg-baud"         type="number" value="115200" min="9600"  step="100" />
        </div>
        <div class="field">
          <label>Sample Rate (Hz)</label>
          <input id="cfg-sampleHz"     type="number" value="80"     min="1"     max="2000" />
        </div>
        <div class="field">
          <label>Flush Interval (ms)</label>
          <input id="cfg-flushMs"      type="number" value="50"     min="10"    max="500" />
        </div>
        <div class="field">
          <label>Chunk Size (samples)</label>
          <input id="cfg-chunkSamples" type="number" value="32"     min="2"     max="1024" />
        </div>
        <div class="field">
          <label>Data Width (bits)</label>
          <input id="cfg-dataWidth"    type="number" value="42"     min="8"     max="64" />
        </div>
      </div>
      <div class="modal-footer">
        <button id="applySettings"  class="btn btn-primary">Apply</button>
        <button id="cancelSettings" class="btn">Cancel</button>
      </div>
    </div>
  </div>
`;

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs
// ─────────────────────────────────────────────────────────────────────────────
const elPort           = document.querySelector<HTMLSelectElement>("#port")!;
const elRefreshPorts   = document.querySelector<HTMLButtonElement>("#refreshPorts")!;
const elStartStream    = document.querySelector<HTMLButtonElement>("#startStream")!;
const elStopStream     = document.querySelector<HTMLButtonElement>("#stopStream")!;
const elVdc            = document.querySelector<HTMLInputElement>("#vdc")!;
const elTorque         = document.querySelector<HTMLInputElement>("#torque")!;
const elWriteVdc       = document.querySelector<HTMLButtonElement>("#writeVdc")!;
const elWriteTorque    = document.querySelector<HTMLButtonElement>("#writeTorque")!;
const elStatus         = document.querySelector<HTMLDivElement>("#status")!;
const elBadge          = document.querySelector<HTMLDivElement>("#stream-badge")!;
const elPlotContainer  = document.querySelector<HTMLDivElement>("#plot")!;
const elPlotInfo       = document.querySelector<HTMLSpanElement>("#plot-info")!;
const elClearPlot      = document.querySelector<HTMLButtonElement>("#clearPlot")!;
const elChannelList    = document.querySelector<HTMLDivElement>("#channelList")!;
const elCheckAll       = document.querySelector<HTMLButtonElement>("#checkAll")!;
const elUncheckAll     = document.querySelector<HTMLButtonElement>("#uncheckAll")!;
const elSettingsBtn    = document.querySelector<HTMLButtonElement>("#btn-settings")!;
const elSettingsModal  = document.querySelector<HTMLDivElement>("#settings-modal")!;
const elCloseSettings  = document.querySelector<HTMLButtonElement>("#closeSettings")!;
const elCancelSettings = document.querySelector<HTMLButtonElement>("#cancelSettings")!;
const elApplySettings  = document.querySelector<HTMLButtonElement>("#applySettings")!;
const elCfgBaud        = document.querySelector<HTMLInputElement>("#cfg-baud")!;
const elCfgSampleHz    = document.querySelector<HTMLInputElement>("#cfg-sampleHz")!;
const elCfgFlushMs     = document.querySelector<HTMLInputElement>("#cfg-flushMs")!;
const elCfgChunkSamples= document.querySelector<HTMLInputElement>("#cfg-chunkSamples")!;
const elCfgDataWidth   = document.querySelector<HTMLInputElement>("#cfg-dataWidth")!;

// ─────────────────────────────────────────────────────────────────────────────
// Build channel rows in sidebar
// ─────────────────────────────────────────────────────────────────────────────
const valueSpans: HTMLSpanElement[] = [];

CHANNELS.forEach((ch, i) => {
  const row   = document.createElement("label");  row.className = "ch-row";

  const dot   = document.createElement("span");   dot.className = "ch-dot";
  dot.style.background = ch.color;

  const cb    = document.createElement("input");  cb.type = "checkbox";  cb.checked = true;
  cb.className = "ch-cb";  cb.dataset.idx = String(i);

  const name  = document.createElement("span");   name.className = "ch-name";
  name.textContent = ch.name;

  const val   = document.createElement("span");   val.className = "ch-value";
  val.id = `val-${i}`;  val.textContent = "0.0000";
  valueSpans.push(val);

  const unit  = document.createElement("span");   unit.className = "ch-unit";
  unit.textContent = ch.unit;

  row.append(dot, cb, name, val, unit);
  elChannelList.append(row);

  cb.addEventListener("change", () => {
    visibleChannels[i] = cb.checked;
    plot.setSeries(i + 1, { show: cb.checked });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// uPlot — multi-channel
// ─────────────────────────────────────────────────────────────────────────────
function plotSize(): { width: number; height: number } {
  return {
    width:  Math.max(400, elPlotContainer.clientWidth),
    height: Math.max(300, elPlotContainer.clientHeight),
  };
}

const plot = new uPlot(
  {
    ...plotSize(),
    pxAlign: 0,
    cursor: { show: true, drag: { x: true, y: false, uni: 50 } },
    scales: { x: { time: false } },
    axes: [
      {
        stroke: "#3a5575",
        grid:  { stroke: "#0e1d30", width: 1 },
        ticks: { stroke: "#0e1d30" },
      },
      {
        stroke: "#3a5575",
        grid:  { stroke: "#0e1d30", width: 1 },
        ticks: { stroke: "#0e1d30" },
      },
    ],
    series: [
      { label: "t [s]" },
      ...CHANNELS.map((ch) => ({
        label: ch.name,
        stroke: ch.color,
        width: 1.5,
        show: true,
      })),
    ],
    legend: { show: true, live: true },
  },
  [new Array<number>(0), ...CHANNELS.map(() => new Array<number>(0))],
  elPlotContainer,
);

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function rawToFloat(raw: number): number { return raw / FP_SCALE; }
function floatToRaw(v: number): number   { return Math.round(v * FP_SCALE); }

function setStatus(text: string, kind: "ok" | "error" | "idle" = "idle"): void {
  elStatus.textContent = `● ${text}`;
  elStatus.className = `status-bar${kind !== "idle" ? " " + kind : ""}`;
}

function setBadge(state: "idle" | "streaming" | "error"): void {
  const labels = { idle: "● IDLE", streaming: "● STREAMING", error: "● ERROR" } as const;
  elBadge.className = `badge badge-${state}`;
  elBadge.textContent = labels[state];
}

// Build plot data arrays with uniform stride decimation (all channels aligned)
function buildPlotData(maxPts: number): number[][] {
  const n = samples.length;
  if (n === 0) return [[], ...CHANNELS.map(() => [])];

  const step = n <= maxPts ? 1 : Math.ceil(n / maxPts);
  const indices: number[] = [];
  for (let i = 0; i < n; i += step) indices.push(i);

  const xArr = indices.map((i) => samples[i].t_ms * 0.001);
  const yArrs = CHANNELS.map((_, ch) =>
    indices.map((i) => rawToFloat(samples[i].regs[ch] ?? 0)),
  );

  return [xArr, ...yArrs];
}

function scheduleRender(): void {
  if (renderPending) return;
  renderPending = true;

  requestAnimationFrame(() => {
    renderPending = false;

    const { width } = plotSize();
    const maxPts = Math.max(600, width * 2);

    plot.setData(buildPlotData(maxPts) as uPlot.AlignedData);

    // Update channel value displays
    for (let i = 0; i < N_CH; i++) {
      valueSpans[i].textContent = rawToFloat(latestRegs[i]).toFixed(4);
    }

    elPlotInfo.textContent = `${samples.length.toLocaleString()} samples`;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Serial port
// ─────────────────────────────────────────────────────────────────────────────
async function refreshPorts(): Promise<void> {
  try {
    const ports = await invoke<string[]>("list_serial_ports");
    elPort.innerHTML = "";

    if (ports.length === 0) {
      elPort.innerHTML = `<option value="">No ports found</option>`;
      setStatus("No serial ports found", "error");
      return;
    }

    for (const p of ports) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = p;
      elPort.append(opt);
    }

    setStatus(`${ports.length} port(s) found`, "ok");
  } catch (e) {
    setStatus(`Port list error: ${String(e)}`, "error");
  }
}

function buildStreamConfig(): StreamConfig {
  return {
    portName:     elPort.value,
    baudRate:     cfg.baudRate,
    sampleHz:     cfg.sampleHz,
    flushMs:      cfg.flushMs,
    chunkSamples: cfg.chunkSamples,
    dataWidth:    cfg.dataWidth,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Settings modal
// ─────────────────────────────────────────────────────────────────────────────
function openSettings(): void {
  elCfgBaud.value         = String(cfg.baudRate);
  elCfgSampleHz.value     = String(cfg.sampleHz);
  elCfgFlushMs.value      = String(cfg.flushMs);
  elCfgChunkSamples.value = String(cfg.chunkSamples);
  elCfgDataWidth.value    = String(cfg.dataWidth);
  elSettingsModal.classList.remove("hidden");
}

function closeSettings(): void { elSettingsModal.classList.add("hidden"); }

function applySettings(): void {
  cfg = {
    baudRate:     Number(elCfgBaud.value),
    sampleHz:     Number(elCfgSampleHz.value),
    flushMs:      Number(elCfgFlushMs.value),
    chunkSamples: Number(elCfgChunkSamples.value),
    dataWidth:    Number(elCfgDataWidth.value),
  };
  closeSettings();
  setStatus("Settings applied", "ok");
}

// ─────────────────────────────────────────────────────────────────────────────
// Event listeners
// ─────────────────────────────────────────────────────────────────────────────
elRefreshPorts.addEventListener("click", () => void refreshPorts());

elStartStream.addEventListener("click", async () => {
  const config = buildStreamConfig();
  if (!config.portName) { setStatus("Select a serial port first", "error"); return; }
  try {
    samples.length = 0;
    await invoke("start_stream", { config });
    setBadge("streaming");
    setStatus("Streaming…", "ok");
  } catch (e) {
    setStatus(`Start failed: ${String(e)}`, "error");
    setBadge("error");
  }
});

elStopStream.addEventListener("click", async () => {
  try {
    await invoke("stop_stream");
    setBadge("idle");
    setStatus("Stream stopped");
  } catch (e) {
    setStatus(`Stop failed: ${String(e)}`, "error");
  }
});

elWriteVdc.addEventListener("click", async () => {
  try {
    await invoke("write_vdc_bus", {
      port_name:  elPort.value,
      baud_rate:  cfg.baudRate,
      value:      floatToRaw(Number(elVdc.value)),
      data_width: cfg.dataWidth,
    });
    setStatus("VDC_BUS updated", "ok");
  } catch (e) { setStatus(`Write VDC failed: ${String(e)}`, "error"); }
});

elWriteTorque.addEventListener("click", async () => {
  try {
    await invoke("write_torque_load", {
      port_name:  elPort.value,
      baud_rate:  cfg.baudRate,
      value:      floatToRaw(Number(elTorque.value)),
      data_width: cfg.dataWidth,
    });
    setStatus("TORQUE_LOAD updated", "ok");
  } catch (e) { setStatus(`Write torque failed: ${String(e)}`, "error"); }
});

elClearPlot.addEventListener("click", () => {
  samples.length = 0;
  plot.setData([[], ...CHANNELS.map(() => [])] as uPlot.AlignedData);
  elPlotInfo.textContent = "0 samples";
});

elCheckAll.addEventListener("click", () => {
  elChannelList.querySelectorAll<HTMLInputElement>(".ch-cb").forEach((cb) => {
    cb.checked = true;
    const idx = Number(cb.dataset.idx);
    visibleChannels[idx] = true;
    plot.setSeries(idx + 1, { show: true });
  });
  scheduleRender();
});

elUncheckAll.addEventListener("click", () => {
  elChannelList.querySelectorAll<HTMLInputElement>(".ch-cb").forEach((cb) => {
    cb.checked = false;
    const idx = Number(cb.dataset.idx);
    visibleChannels[idx] = false;
    plot.setSeries(idx + 1, { show: false });
  });
});

elSettingsBtn.addEventListener("click", openSettings);
elCloseSettings.addEventListener("click", closeSettings);
elCancelSettings.addEventListener("click", closeSettings);
elApplySettings.addEventListener("click", applySettings);
elSettingsModal.addEventListener("click", (e) => {
  if (e.target === elSettingsModal) closeSettings();
});

// ─────────────────────────────────────────────────────────────────────────────
// PS Control (UDP → hil_controller)
// ─────────────────────────────────────────────────────────────────────────────
type HilStatus = {
  speed_rad_s:   number;
  ialpha_a:      number;
  ibeta_a:       number;
  flux_alpha_wb: number;
  flux_beta_wb:  number;
  freq_hz:       number;
  vdc_v:         number;
  enable:        number;
};

const elPsIp       = document.querySelector<HTMLInputElement>("#ps-ip")!;
const elPsFreq     = document.querySelector<HTMLInputElement>("#ps-freq")!;
const elPsVdc      = document.querySelector<HTMLInputElement>("#ps-vdc")!;
const elPsTorque   = document.querySelector<HTMLInputElement>("#ps-torque")!;
const elPsEnable   = document.querySelector<HTMLInputElement>("#ps-enable")!;
const elPsSet      = document.querySelector<HTMLButtonElement>("#ps-set")!;
const elPsGet      = document.querySelector<HTMLButtonElement>("#ps-get")!;
const elPsStop     = document.querySelector<HTMLButtonElement>("#ps-stop")!;
const elPsMonitor  = document.querySelector<HTMLInputElement>("#ps-monitor")!;
const elPsBadge    = document.querySelector<HTMLSpanElement>("#ps-badge")!;
const elPsTelemetry= document.querySelector<HTMLDivElement>("#ps-telemetry")!;

const ptSpeed = document.querySelector<HTMLSpanElement>("#pt-speed")!;
const ptIa    = document.querySelector<HTMLSpanElement>("#pt-ia")!;
const ptIb    = document.querySelector<HTMLSpanElement>("#pt-ib")!;
const ptFa    = document.querySelector<HTMLSpanElement>("#pt-fa")!;
const ptFb    = document.querySelector<HTMLSpanElement>("#pt-fb")!;
const ptFreq  = document.querySelector<HTMLSpanElement>("#pt-freq")!;
const ptVdc   = document.querySelector<HTMLSpanElement>("#pt-vdc")!;
const ptEn    = document.querySelector<HTMLSpanElement>("#pt-en")!;

let psMonitorTimer: ReturnType<typeof setInterval> | null = null;

function psIp(): string { return elPsIp.value.trim(); }

function updatePsTelemetry(s: HilStatus): void {
  ptSpeed.textContent = s.speed_rad_s.toFixed(3);
  ptIa.textContent    = s.ialpha_a.toFixed(4);
  ptIb.textContent    = s.ibeta_a.toFixed(4);
  ptFa.textContent    = s.flux_alpha_wb.toFixed(4);
  ptFb.textContent    = s.flux_beta_wb.toFixed(4);
  ptFreq.textContent  = s.freq_hz.toFixed(2);
  ptVdc.textContent   = s.vdc_v.toFixed(2);
  ptEn.textContent    = s.enable ? "ON" : "OFF";
  elPsBadge.textContent = s.enable ? "ON" : "OFF";
  elPsBadge.className = `ps-badge ${s.enable ? "ps-badge-on" : "ps-badge-off"}`;
  elPsTelemetry.classList.remove("hidden");
}

elPsSet.addEventListener("click", async () => {
  try {
    await invoke("hil_set", {
      params: {
        ip:       psIp(),
        freqHz:   Number(elPsFreq.value),
        vdcV:     Number(elPsVdc.value),
        torqueNm: Number(elPsTorque.value),
        enable:   elPsEnable.checked,
      },
    });
    setStatus("PS: params applied", "ok");
  } catch (e) {
    setStatus(`PS set failed: ${String(e)}`, "error");
  }
});

elPsGet.addEventListener("click", async () => {
  try {
    const s = await invoke<HilStatus>("hil_get", { ip: psIp() });
    updatePsTelemetry(s);
    setStatus("PS: status updated", "ok");
  } catch (e) {
    setStatus(`PS get failed: ${String(e)}`, "error");
  }
});

elPsStop.addEventListener("click", async () => {
  try {
    await invoke("hil_stop", { ip: psIp() });
    elPsBadge.textContent = "OFF";
    elPsBadge.className = "ps-badge ps-badge-off";
    setStatus("PS: controller stopped", "ok");
    // stop monitor too
    elPsMonitor.checked = false;
    if (psMonitorTimer !== null) { clearInterval(psMonitorTimer); psMonitorTimer = null; }
  } catch (e) {
    setStatus(`PS stop failed: ${String(e)}`, "error");
  }
});

elPsMonitor.addEventListener("change", () => {
  if (elPsMonitor.checked) {
    psMonitorTimer = setInterval(async () => {
      try {
        const s = await invoke<HilStatus>("hil_get", { ip: psIp() });
        updatePsTelemetry(s);
      } catch {
        // silently skip missed polls
      }
    }, 1000);
  } else {
    if (psMonitorTimer !== null) { clearInterval(psMonitorTimer); psMonitorTimer = null; }
  }
});

// Responsive plot resize via ResizeObserver
new ResizeObserver(() => {
  const { width, height } = plotSize();
  plot.setSize({ width, height });
}).observe(elPlotContainer);

// ─────────────────────────────────────────────────────────────────────────────
// Tauri events
// ─────────────────────────────────────────────────────────────────────────────
void listen<TelemetrySample[]>("telemetry-chunk", (ev) => {
  if (!Array.isArray(ev.payload)) return;

  for (const s of ev.payload) {
    if (!s || !Array.isArray(s.regs) || s.regs.length < N_CH) continue;
    samples.push(s);
    latestRegs = s.regs.slice(0, N_CH);
  }

  if (samples.length > MAX_SAMPLES) samples.splice(0, samples.length - MAX_SAMPLES);

  scheduleRender();
});

void listen<string>("stream-error", (ev) => {
  setStatus(ev.payload, "error");
  setBadge("error");
});

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
void refreshPorts();
