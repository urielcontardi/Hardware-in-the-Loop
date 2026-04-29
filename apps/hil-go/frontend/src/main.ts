import "uplot/dist/uPlot.min.css";
import "./styles.css";
import uPlot from "uplot";
import { EventsOn } from "../wailsjs/runtime/runtime";
import {
  SetParams,
  GetStatus,
  StopController,
  GetStats,
  GetLocalIP,
} from "../wailsjs/go/main/App";

// ── Types ─────────────────────────────────────────────────────────────────────
type Sample = { Ia: number; Ib: number; FluxA: number; FluxB: number; Speed: number };
type HilStatus = {
  speed_rad_s: number; ialpha_A: number; ibeta_A: number;
  flux_alpha_Wb: number; flux_beta_Wb: number;
  freq_hz: number; vdc_v: number; enable: number;
};

// ── Channels ──────────────────────────────────────────────────────────────────
const CHANNELS = [
  { name: "Iα",    unit: "A",     color: "#4fc3f7", key: "Ia"    },
  { name: "Iβ",    unit: "A",     color: "#ef9a9a", key: "Ib"    },
  { name: "Φα",    unit: "Wb",    color: "#81c784", key: "FluxA" },
  { name: "Φβ",    unit: "Wb",    color: "#ce93d8", key: "FluxB" },
  { name: "Speed", unit: "rad/s", color: "#ffcc80", key: "Speed" },
] as const;
type ChKey = typeof CHANNELS[number]["key"];
const N_CH = CHANNELS.length;
const MAX_SAMPLES = 100_000;

// ── App state ─────────────────────────────────────────────────────────────────
const tBuf: number[]    = [];
const yBufs: number[][] = Array.from({ length: N_CH }, () => []);
let sampleCount = 0;
let telemActive = false;
let t0 = 0;

// Subplot state — default: Iα Iβ → plot 0, Φα Φβ Speed → plot 1
let nSubplots = 2;
const chSubplot = [0, 0, 1, 1, 1];
const visible   = Array(N_CH).fill(true);

// uPlot instances (one per subplot)
let plots: uPlot[] = [];
let isBuilding = false;

// ── DOM ───────────────────────────────────────────────────────────────────────
document.querySelector<HTMLDivElement>("#app")!.innerHTML = `
  <header class="topbar">
    <div class="topbar-brand">
      <img src="/LSE_LOGO.png" alt="LSE" class="app-logo" />
      <div class="topbar-sep"></div>
      <div>
        <span class="app-name">HIL Monitor</span>
        <span class="app-sub">Hardware-in-the-Loop · LSE</span>
      </div>
    </div>
    <div class="topbar-right">
      <div id="ws-badge" class="badge badge-idle">● OFFLINE</div>
    </div>
  </header>

  <div class="workspace">
    <aside class="sidebar">

      <section class="panel">
        <div class="panel-title">PS CONTROL</div>
        <div class="field-inline">
          <label>Board IP</label>
          <input id="ip" type="text" value="192.168.15.13" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Freq (Hz)</label>
          <input id="freq" type="number" value="60" min="1" max="200" step="1" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Vdc (V)</label>
          <input id="vdc" type="number" value="311" min="0" max="600" step="1" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Torque (N·m)</label>
          <input id="torque" type="number" value="0" min="-50" max="50" step="0.1" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Enable</label>
          <label class="toggle">
            <input id="enable" type="checkbox" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>
        <div class="btn-row" style="margin-top:8px">
          <button id="btn-set"  class="btn btn-primary">▶ Set</button>
          <button id="btn-get"  class="btn btn-write">↓ Get</button>
          <button id="btn-stop" class="btn btn-danger">■ Stop</button>
        </div>
        <div id="ps-status" class="ps-status hidden"></div>
      </section>

      <section class="panel">
        <div class="panel-title">TELEMETRY
          <span class="panel-title-actions">
            <label class="toggle" style="vertical-align:middle">
              <input id="telem-toggle" type="checkbox" />
              <span class="toggle-slider"></span>
            </label>
          </span>
        </div>

        <div class="subplot-layout-row">
          <span class="subplot-layout-label">Subplots</span>
          <div class="subplot-n-group">
            <button class="subplot-n-btn" data-n="1">1</button>
            <button class="subplot-n-btn active" data-n="2">2</button>
            <button class="subplot-n-btn" data-n="3">3</button>
            <button class="subplot-n-btn" data-n="4">4</button>
          </div>
        </div>

        <div id="ch-list" class="channel-list"></div>

        <div class="btn-row" style="margin-top:8px">
          <button id="btn-clear" class="btn btn-sm">Clear</button>
          <span id="sample-count" class="plot-info">0 samples</span>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">STATS</div>
        <div class="ps-telemetry">
          <div class="ps-telem-row"><span class="ps-telem-label">Rx</span>      <span id="st-rx">—</span>     <span class="ps-telem-unit">samples</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Packets</span> <span id="st-pkt">—</span>    <span class="ps-telem-unit">UDP</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Dropped</span> <span id="st-drop">—</span>   <span class="ps-telem-unit">samples</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">CRC err</span> <span id="st-crc">—</span></div>
          <div class="ps-telem-row"><span class="ps-telem-label">Seq miss</span><span id="st-seq">—</span></div>
        </div>
      </section>

      <div id="status" class="status-bar">● Idle</div>
    </aside>

    <main class="plot-area" id="plot-area"></main>
  </div>
`;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const elIp          = document.querySelector<HTMLInputElement>("#ip")!;
const elFreq        = document.querySelector<HTMLInputElement>("#freq")!;
const elVdc         = document.querySelector<HTMLInputElement>("#vdc")!;
const elTorque      = document.querySelector<HTMLInputElement>("#torque")!;
const elEnable      = document.querySelector<HTMLInputElement>("#enable")!;
const elBtnSet      = document.querySelector<HTMLButtonElement>("#btn-set")!;
const elBtnGet      = document.querySelector<HTMLButtonElement>("#btn-get")!;
const elBtnStop     = document.querySelector<HTMLButtonElement>("#btn-stop")!;
const elBtnClear    = document.querySelector<HTMLButtonElement>("#btn-clear")!;
const elPsStatus    = document.querySelector<HTMLDivElement>("#ps-status")!;
const elWsBadge     = document.querySelector<HTMLDivElement>("#ws-badge")!;
const elStatus      = document.querySelector<HTMLDivElement>("#status")!;
const elTelemToggle = document.querySelector<HTMLInputElement>("#telem-toggle")!;
const elSampleCount = document.querySelector<HTMLSpanElement>("#sample-count")!;
const elChList      = document.querySelector<HTMLDivElement>("#ch-list")!;
const elPlotArea    = document.querySelector<HTMLElement>("#plot-area")!;

// ── Subplot count selector ────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn").forEach(btn => {
  btn.addEventListener("click", () => setNSubplots(Number(btn.dataset.n)));
});

// ── Channel list ──────────────────────────────────────────────────────────────
const valSpans: HTMLSpanElement[]     = [];
const subplotBadges: HTMLButtonElement[] = [];

CHANNELS.forEach((ch, i) => {
  const row = document.createElement("label");
  row.className = "ch-row";

  const dot = document.createElement("span");
  dot.className = "ch-dot";
  dot.style.background = ch.color;

  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = true; cb.className = "ch-cb";

  const name = document.createElement("span");
  name.className = "ch-name"; name.textContent = ch.name;

  const val = document.createElement("span");
  val.className = "ch-value"; val.textContent = "—";
  valSpans.push(val);

  const unit = document.createElement("span");
  unit.className = "ch-unit"; unit.textContent = ch.unit;

  const badge = document.createElement("button");
  badge.className = "ch-subplot-badge";
  badge.dataset.sp = String(chSubplot[i]);
  badge.textContent = String(chSubplot[i] + 1);
  badge.title = "Click to move to next subplot";
  subplotBadges.push(badge);

  row.append(dot, cb, name, val, unit, badge);
  elChList.append(row);

  cb.addEventListener("change", () => {
    visible[i] = cb.checked;
    const s = chSubplot[i];
    if (s < plots.length) {
      const chIdx = getChIdx(s);
      const seriesIdx = chIdx.indexOf(i) + 1;
      if (seriesIdx > 0) plots[s].setSeries(seriesIdx, { show: cb.checked });
    }
  });

  badge.addEventListener("click", e => {
    e.preventDefault();
    e.stopPropagation();
    chSubplot[i] = (chSubplot[i] + 1) % nSubplots;
    badge.textContent = String(chSubplot[i] + 1);
    badge.dataset.sp  = String(chSubplot[i]);
    buildPlots();
  });
});

// ── Subplot helpers ───────────────────────────────────────────────────────────
function getChIdx(s: number): number[] {
  return CHANNELS.map((_, i) => i).filter(i => chSubplot[i] === s);
}

function plotHeight(): number {
  return Math.max(80, Math.floor(elPlotArea.clientHeight / nSubplots));
}

function setNSubplots(n: number) {
  nSubplots = n;
  document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn").forEach(b => {
    b.classList.toggle("active", Number(b.dataset.n) === n);
  });
  for (let i = 0; i < N_CH; i++) {
    if (chSubplot[i] >= nSubplots) {
      chSubplot[i] = nSubplots - 1;
      subplotBadges[i].textContent  = String(nSubplots);
      subplotBadges[i].dataset.sp   = String(nSubplots - 1);
    }
  }
  buildPlots();
}

// ── Build / rebuild all uPlot instances ───────────────────────────────────────
function buildPlots() {
  if (isBuilding) return;
  isBuilding = true;

  plots.forEach(p => p.destroy());
  plots = [];
  elPlotArea.innerHTML = "";

  const w = Math.max(400, elPlotArea.clientWidth);
  const h = plotHeight();

  // Downsample shared buffers once
  const n = tBuf.length;
  const maxPts = Math.max(600, w * 2);
  const step = n <= maxPts ? 1 : Math.ceil(n / maxPts);
  const xs: number[] = [];
  const ys: number[][] = Array.from({ length: N_CH }, () => []);
  for (let j = 0; j < n; j += step) {
    xs.push(tBuf[j]);
    for (let c = 0; c < N_CH; c++) ys[c].push(yBufs[c][j] ?? 0);
  }

  for (let s = 0; s < nSubplots; s++) {
    const chIdx = getChIdx(s);

    const wrap = document.createElement("div");
    wrap.className = "subplot-wrap";
    elPlotArea.appendChild(wrap);

    const series: uPlot.Series[] = [{ label: "t [s]" }];
    chIdx.forEach(ci => series.push({
      label: CHANNELS[ci].name,
      stroke: CHANNELS[ci].color,
      width: 1.5,
      show: visible[ci],
    }));

    const p = new uPlot(
      {
        width: w,
        height: h,
        pxAlign: 0,
        cursor: { show: true, drag: { x: true, y: false, uni: 50 } },
        scales: { x: { time: false } },
        axes: [
          { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" } },
          { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" } },
        ],
        series,
        legend: { show: chIdx.length > 0, live: true },
      },
      [xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData,
      wrap,
    );

    plots.push(p);
  }

  isBuilding = false;
}

// ── Resize observer ───────────────────────────────────────────────────────────
new ResizeObserver(() => {
  if (isBuilding || plots.length === 0) return;
  const w = Math.max(400, elPlotArea.clientWidth);
  const h = plotHeight();
  plots.forEach(p => p.setSize({ width: w, height: h }));
}).observe(elPlotArea);

requestAnimationFrame(() => buildPlots());

// ── Render ────────────────────────────────────────────────────────────────────
let renderPending = false;

function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => {
    renderPending = false;
    const w = elPlotArea.clientWidth || 800;
    const maxPts = Math.max(600, w * 2);
    const n = tBuf.length;
    const step = n <= maxPts ? 1 : Math.ceil(n / maxPts);

    const xs: number[] = [];
    const ys: number[][] = Array.from({ length: N_CH }, () => []);
    for (let i = 0; i < n; i += step) {
      xs.push(tBuf[i]);
      for (let c = 0; c < N_CH; c++) ys[c].push(yBufs[c][i] ?? 0);
    }

    plots.forEach((p, s) => {
      const chIdx = getChIdx(s);
      p.setData([xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData);
    });

    elSampleCount.textContent = `${sampleCount.toLocaleString()} samples`;
  });
}

// ── Telemetry events ──────────────────────────────────────────────────────────
EventsOn("telemetry", (samples: Sample[]) => {
  if (!telemActive || !Array.isArray(samples)) return;

  for (const s of samples) {
    const t = (performance.now() - t0) / 1000;
    tBuf.push(t);
    CHANNELS.forEach((ch, i) => yBufs[i].push(s[ch.key as ChKey]));
    sampleCount++;
  }

  if (tBuf.length > MAX_SAMPLES) {
    const drop = tBuf.length - MAX_SAMPLES;
    tBuf.splice(0, drop);
    for (let i = 0; i < N_CH; i++) yBufs[i].splice(0, drop);
  }

  if (samples.length > 0) {
    const last = samples[samples.length - 1];
    CHANNELS.forEach((ch, i) => {
      valSpans[i].textContent = last[ch.key as ChKey].toFixed(4);
    });
  }

  scheduleRender();
});

// ── Telemetry toggle ──────────────────────────────────────────────────────────
elTelemToggle.addEventListener("change", () => {
  telemActive = elTelemToggle.checked;
  if (telemActive) {
    t0 = performance.now();
    elWsBadge.className = "badge badge-streaming";
    elWsBadge.textContent = "● ONLINE";
    setStatus("Telemetry stream active", "ok");
  } else {
    elWsBadge.className = "badge badge-idle";
    elWsBadge.textContent = "● OFFLINE";
    setStatus("Telemetry paused", "idle");
  }
});

// ── PS control ────────────────────────────────────────────────────────────────
function setStatus(text: string, kind: "ok" | "error" | "idle" = "idle") {
  elStatus.textContent = `● ${text}`;
  elStatus.className = `status-bar${kind !== "idle" ? " " + kind : ""}`;
}

function showPsStatus(text: string, ok: boolean) {
  elPsStatus.textContent = text;
  elPsStatus.className = `ps-status ${ok ? "ps-status-ok" : "ps-status-err"}`;
}

elBtnSet.addEventListener("click", async () => {
  try {
    await SetParams(
      elIp.value.trim(),
      Number(elFreq.value),
      Number(elVdc.value),
      Number(elTorque.value),
      elEnable.checked,
      0,
    );
    showPsStatus("OK — params applied", true);
    setStatus("PS params applied", "ok");
  } catch (e) {
    showPsStatus(String(e), false);
    setStatus(`Set failed: ${String(e)}`, "error");
  }
});

elBtnGet.addEventListener("click", async () => {
  try {
    const s = await GetStatus(elIp.value.trim()) as HilStatus;
    showPsStatus(
      `freq=${s.freq_hz.toFixed(1)}Hz  vdc=${s.vdc_v.toFixed(0)}V  en=${s.enable}  speed=${s.speed_rad_s.toFixed(2)}rad/s`,
      true,
    );
    setStatus("PS status updated", "ok");
  } catch (e) {
    showPsStatus(String(e), false);
    setStatus(`Get failed: ${String(e)}`, "error");
  }
});

elBtnStop.addEventListener("click", async () => {
  try {
    await StopController(elIp.value.trim());
    showPsStatus("Controller stopped", true);
    setStatus("PS stopped", "ok");
    elTelemToggle.checked = false;
    telemActive = false;
    elWsBadge.className = "badge badge-idle";
    elWsBadge.textContent = "● OFFLINE";
  } catch (e) {
    showPsStatus(String(e), false);
    setStatus(`Stop failed: ${String(e)}`, "error");
  }
});

elBtnClear.addEventListener("click", () => {
  tBuf.length = 0;
  for (let i = 0; i < N_CH; i++) yBufs[i].length = 0;
  sampleCount = 0;
  plots.forEach((p, s) => {
    const chIdx = getChIdx(s);
    p.setData([[], ...chIdx.map(() => [])] as uPlot.AlignedData);
  });
  elSampleCount.textContent = "0 samples";
});

// ── Stats polling ─────────────────────────────────────────────────────────────
setInterval(async () => {
  try {
    const s = await GetStats() as Record<string, number>;
    (document.querySelector("#st-rx")   as HTMLElement).textContent = s.samples_rx?.toLocaleString() ?? "—";
    (document.querySelector("#st-pkt")  as HTMLElement).textContent = s.packets_rx?.toLocaleString() ?? "—";
    (document.querySelector("#st-drop") as HTMLElement).textContent = s.dropped?.toLocaleString()    ?? "—";
    (document.querySelector("#st-crc")  as HTMLElement).textContent = String(s.crc_errors ?? "—");
    (document.querySelector("#st-seq")  as HTMLElement).textContent = String(s.seq_missed  ?? "—");
  } catch { /* ignore */ }
}, 2000);

// ── Show local IP on startup ──────────────────────────────────────────────────
GetLocalIP().then(ip => setStatus(`Ready — local IP: ${ip}`, "ok")).catch(() => {});
