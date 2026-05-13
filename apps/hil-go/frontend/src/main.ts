import "uplot/dist/uPlot.min.css";
import "./styles.css";
import uPlot from "uplot";
import * as WailsRuntime from "../wailsjs/runtime/runtime";
import * as WailsApp from "../wailsjs/go/main/App";

// ── Types ─────────────────────────────────────────────────────────────────────
type Sample = { Ia: number; Ib: number; FluxA: number; FluxB: number; Speed: number };
type HilStatus = {
  status: string;
  state: "idle" | "running" | "paused" | "stopped" | string;
  speed_rad_s: number; ialpha_A: number; ibeta_A: number;
  flux_alpha_Wb: number; flux_beta_Wb: number;
  freq_hz: number; freq_actual_hz: number;
  vdc_v: number; torque_nm: number;
  base_freq_hz: number; max_v_pu: number; accel_time_s: number;
  enable: number;
  telem_dst: string;
  telem_active: number;
  telem_packets_sent?: number;
  telem_send_errors?: number;
  board_ip?: string;
};
type DiscoveryResponse = {
  type: string;
  name: string;
  ip: string;
  mac: string;
  cmd_port: number;
  telem_port: number;
  state: string;
};

type HilApi = {
  onTelemetry(cb: (samples: Sample[]) => void): void;
  DiscoverBoard(ip?: string): Promise<DiscoveryResponse>;
  SetParams(ip: string, freqHz: number, vdcV: number, torqueNm: number, baseFreqHz: number, maxVPu: number, accelTimeSec: number, enable: boolean, applyEnable: boolean, attachTelem: boolean): Promise<HilStatus>;
  GetStatus(ip: string): Promise<HilStatus>;
  Run(ip: string): Promise<HilStatus>;
  Pause(ip: string): Promise<HilStatus>;
  StopController(ip: string): Promise<HilStatus>;
  ResetSolver(ip: string): Promise<HilStatus>;
  AttachTelemetry(ip: string): Promise<HilStatus>;
  DetachTelemetry(ip: string): Promise<HilStatus>;
  GetStats(): Promise<Record<string, number>>;
  GetLocalIP(): Promise<string>;
};

const isWails = typeof window !== "undefined" && !!(window as any).go?.main?.App;
const BOARD_IP_STORAGE_KEY = "hil-board-ip";

function responseError(res: Response, text: string): string {
  const title = text.match(/<title>(.*?)<\/title>/is)?.[1]?.replace(/\s+/g, " ").trim();
  if (title) return title;
  return text || `HTTP ${res.status}: ${res.statusText}`;
}

async function postJSON<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let parsed: any = null;
  try { parsed = text ? JSON.parse(text) : null; } catch {}
  if (!res.ok) throw new Error(parsed?.error || responseError(res, text));
  if (parsed == null) throw new Error("empty response from gateway");
  return parsed as T;
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  const text = await res.text();
  let parsed: any = null;
  try { parsed = text ? JSON.parse(text) : null; } catch {}
  if (!res.ok) throw new Error(parsed?.error || responseError(res, text));
  if (parsed == null) throw new Error("empty response from gateway");
  return parsed as T;
}

const api: HilApi = isWails ? {
  onTelemetry(cb) {
    WailsRuntime.EventsOn("telemetry", cb);
  },
  DiscoverBoard() {
    return WailsApp.DiscoverBoard() as Promise<DiscoveryResponse>;
  },
  SetParams: WailsApp.SetParams as HilApi["SetParams"],
  GetStatus: WailsApp.GetStatus as HilApi["GetStatus"],
  Run: WailsApp.Run as HilApi["Run"],
  Pause: WailsApp.Pause as HilApi["Pause"],
  StopController: WailsApp.StopController as HilApi["StopController"],
  ResetSolver: WailsApp.ResetSolver as HilApi["ResetSolver"],
  AttachTelemetry: WailsApp.AttachTelemetry as HilApi["AttachTelemetry"],
  DetachTelemetry(ip) {
    return WailsApp.StopController(ip) as Promise<HilStatus>;
  },
  GetStats: WailsApp.GetStats as HilApi["GetStats"],
  GetLocalIP: WailsApp.GetLocalIP as HilApi["GetLocalIP"],
} : {
  onTelemetry(cb) {
    const events = new EventSource("/events");
    events.addEventListener("telemetry", ev => {
      try {
        const samples = JSON.parse((ev as MessageEvent).data);
        cb(samples);
      } catch {
        /* ignore malformed event */
      }
    });
    events.onerror = () => setTelemBadge(false, true);
  },
  DiscoverBoard(ip) {
    return postJSON<DiscoveryResponse>("/api/discover", { ip });
  },
  SetParams(ip, freqHz, vdcV, torqueNm, baseFreqHz, maxVPu, accelTimeSec, enable, applyEnable, attachTelem) {
    const body: Record<string, unknown> = {
      ip,
      freq_hz: freqHz,
      vdc_v: vdcV,
      torque_nm: torqueNm,
      base_freq_hz: baseFreqHz,
      max_v_pu: maxVPu,
      accel_time_s: accelTimeSec,
      attach_udp: attachTelem,
    };
    if (applyEnable) body.enable = enable ? 1 : 0;
    return postJSON<HilStatus>("/api/set", body);
  },
  GetStatus(ip) {
    return getJSON<HilStatus>(`/api/status?ip=${encodeURIComponent(ip)}`);
  },
  Run(ip) {
    return postJSON<HilStatus>("/api/run", { ip });
  },
  Pause(ip) {
    return postJSON<HilStatus>("/api/pause", { ip });
  },
  StopController(ip) {
    return postJSON<HilStatus>("/api/stop", { ip });
  },
  ResetSolver(ip) {
    return postJSON<HilStatus>("/api/reset", { ip });
  },
  AttachTelemetry(ip) {
    return postJSON<HilStatus>("/api/attach", { ip });
  },
  DetachTelemetry(ip) {
    return postJSON<HilStatus>("/api/detach", { ip });
  },
  GetStats() {
    return getJSON<Record<string, number>>("/api/stats");
  },
  GetLocalIP() {
    return getJSON<{ ip: string }>("/api/local-ip").then(r => r.ip);
  },
};

// ── Channels ──────────────────────────────────────────────────────────────────
// Storage is always αβ (matches what the board pushes); rendering may convert
// to abc on-the-fly via the channel `read` function below.
type ChDef = {
  name: string;
  unit: string;
  color: string;
  read: (s: Sample) => number;
  defaultSubplot: number;
};

const SQRT3_2 = Math.sqrt(3) / 2;
// Inverse Clarke (amplitude-invariant, matches FPGA convention):
//   xa = xα, xb = -xα/2 + (√3/2)·xβ, xc = -xα/2 - (√3/2)·xβ
const xa = (a: number, _b: number) => a;
const xb = (a: number, b: number)  => -a / 2 + SQRT3_2 * b;
const xc = (a: number, b: number)  => -a / 2 - SQRT3_2 * b;

const CHANNELS_AB: ChDef[] = [
  { name: "Iα",    unit: "A",     color: "#4fc3f7", read: s => s.Ia,    defaultSubplot: 0 },
  { name: "Iβ",    unit: "A",     color: "#ef9a9a", read: s => s.Ib,    defaultSubplot: 0 },
  { name: "Φα",    unit: "Wb",    color: "#81c784", read: s => s.FluxA, defaultSubplot: 1 },
  { name: "Φβ",    unit: "Wb",    color: "#ce93d8", read: s => s.FluxB, defaultSubplot: 1 },
  { name: "Speed", unit: "RPM",   color: "#ffcc80", read: s => s.Speed * 60 / (2 * Math.PI), defaultSubplot: 2 },
];

const CHANNELS_ABC: ChDef[] = [
  { name: "Ia",    unit: "A",     color: "#4fc3f7", read: s => xa(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Ib",    unit: "A",     color: "#ef9a9a", read: s => xb(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Ic",    unit: "A",     color: "#ffd54f", read: s => xc(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Φa",    unit: "Wb",    color: "#81c784", read: s => xa(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Φb",    unit: "Wb",    color: "#ce93d8", read: s => xb(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Φc",    unit: "Wb",    color: "#a5d6a7", read: s => xc(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Speed", unit: "RPM",   color: "#ffcc80", read: s => s.Speed * 60 / (2 * Math.PI), defaultSubplot: 2 },
];

const DISPLAY_MODE_STORAGE_KEY = "hil-display-mode";
let displayMode: "ab" | "abc" = (localStorage.getItem(DISPLAY_MODE_STORAGE_KEY) as "ab" | "abc") || "abc";
let CHANNELS: ChDef[] = displayMode === "abc" ? CHANNELS_ABC : CHANNELS_AB;
let N_CH = CHANNELS.length;
const MAX_SAMPLES = 100_000;

// ── App state ─────────────────────────────────────────────────────────────────
const tBuf: number[]      = [];
const samplesBuf: Sample[] = [];   // raw αβ samples paralelos a tBuf
let sampleCount = 0;
let t0 = performance.now();
let lastBoardState: string = "idle";
let lastSampleAt = 0;             // ms — for "stream stalled" detection
let liveMode = true;

// Subplot state — derived from each channel's defaultSubplot.
let nSubplots = 3;
let chSubplot: number[] = CHANNELS.map(c => c.defaultSubplot);
let visible:   boolean[] = Array(N_CH).fill(true);

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
      <div id="freq-badge" class="badge badge-idle" style="font-variant-numeric:tabular-nums">— Hz</div>
      <div id="state-badge" class="state-badge state-idle">IDLE</div>
      <div id="ws-badge" class="badge badge-idle">● TELEM OFF</div>
    </div>
  </header>

  <div class="workspace">
    <aside class="sidebar">

      <section class="panel">
        <div class="panel-title">CONNECTION</div>
        <div class="field-inline">
          <label>Board IP</label>
          <input id="ip" type="text" value="192.168.15.14" class="write-input" />
        </div>
        <div class="btn-row">
          <button id="btn-discover" class="btn btn-write">Find</button>
          <button id="btn-connect" class="btn btn-write">Connect</button>
        </div>
        <div id="conn-status" class="ps-status hidden"></div>
      </section>

      <section class="panel">
        <div class="panel-title">PARAMETERS</div>
        <div class="field-inline">
          <label>Speed (RPM)</label>
          <input id="rpm" type="number" value="1800" min="0" max="12000" step="60" class="write-input" />
        </div>
        <div class="field-inline">
          <label title="Tempo para rampar 0 → velocidade nominal">Accel (s)</label>
          <input id="accel-time" type="number" value="5" min="0.1" max="300" step="0.5" class="write-input" />
        </div>
        <div class="field-inline">
          <label title="Tensão do barramento DC do inversor">Vdc (V)</label>
          <input id="vdc" type="number" value="311" min="0" max="600" step="1" class="write-input" />
        </div>
        <div class="field-inline">
          <label title="Torque de carga mecânica aplicado ao rotor">Torque (N·m)</label>
          <input id="torque" type="number" value="0" min="-200" max="200" step="1" class="write-input" />
        </div>
        <details class="adv-details">
          <summary class="adv-summary">▸ Advanced</summary>
          <div class="field-inline" style="margin-top:6px">
            <label title="Número de pares de polos do motor">Pole pairs</label>
            <input id="npp" type="number" value="2" min="1" max="8" step="1" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Velocidade síncrona nominal — tensão máxima é aplicada aqui">Rated RPM</label>
            <input id="rated-rpm" type="number" value="1800" min="60" max="12000" step="60" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Tensão máxima de modulação em pu de Vdc/2">Max V/F (pu)</label>
            <input id="max-vpu" type="number" value="1" min="0" max="1" step="0.01" class="write-input" />
          </div>
        </details>
        <div class="btn-row" style="margin-top:8px">
          <button id="btn-apply" class="btn btn-write">Apply Params</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">CONTROL</div>
        <div class="btn-row">
          <button id="btn-run"   class="btn btn-primary" title="Enable motor with current params (also pulses solver reset)">▶ Run</button>
          <button id="btn-stop"  class="btn btn-danger" title="Disable motor, reset params (daemon stays alive)">■ Stop</button>
        </div>
        <div class="btn-row" style="margin-top:6px">
          <button id="btn-reset" class="btn btn-sm" title="Pulse FPGA solver reset — clears integrator states (currents/flux/speed) without changing params">⟲ Reset solver</button>
        </div>
        <div id="ps-status" class="ps-status hidden"></div>
      </section>

      <section class="panel">
        <div class="panel-title">PLOTS</div>

        <div class="subplot-layout-row">
          <span class="subplot-layout-label">Frame</span>
          <div class="subplot-n-group" id="mode-group">
            <button class="subplot-n-btn" data-mode="ab">αβ</button>
            <button class="subplot-n-btn" data-mode="abc">abc</button>
          </div>
        </div>

        <div class="subplot-layout-row">
          <span class="subplot-layout-label">Subplots</span>
          <div class="subplot-n-group">
            <button class="subplot-n-btn" data-n="1">1</button>
            <button class="subplot-n-btn" data-n="2">2</button>
            <button class="subplot-n-btn active" data-n="3">3</button>
            <button class="subplot-n-btn" data-n="4">4</button>
          </div>
        </div>

        <div id="ch-list" class="channel-list"></div>

        <div class="btn-row" style="margin-top:8px">
          <button id="btn-live" class="btn btn-sm">Live</button>
          <button id="btn-fit" class="btn btn-sm">Fit</button>
          <button id="btn-smooth" class="btn btn-sm" title="Filtro passa-baixa: remove ripple do PWM (janela 10 amostras = 1 período de 1kHz)">Smooth</button>
          <button id="btn-clear" class="btn btn-sm">Clear</button>
        </div>
        <span id="sample-count" class="plot-info">0 samples</span>
      </section>

      <section class="panel">
        <div class="panel-title">STATS</div>
        <div class="ps-telemetry">
          <div class="ps-telem-row"><span class="ps-telem-label">Fs</span>      <span id="st-fs">—</span>     <span class="ps-telem-unit">Hz</span></div>
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
const elRpm         = document.querySelector<HTMLInputElement>("#rpm")!;
const elAccelTime   = document.querySelector<HTMLInputElement>("#accel-time")!;
const elVdc         = document.querySelector<HTMLInputElement>("#vdc")!;
const elTorque      = document.querySelector<HTMLInputElement>("#torque")!;
const elNpp         = document.querySelector<HTMLInputElement>("#npp")!;
const elRatedRpm    = document.querySelector<HTMLInputElement>("#rated-rpm")!;
const elMaxVPu      = document.querySelector<HTMLInputElement>("#max-vpu")!;
const elBtnConnect  = document.querySelector<HTMLButtonElement>("#btn-connect")!;
const elBtnDiscover = document.querySelector<HTMLButtonElement>("#btn-discover")!;
const elBtnApply    = document.querySelector<HTMLButtonElement>("#btn-apply")!;
const elBtnRun      = document.querySelector<HTMLButtonElement>("#btn-run")!;
const elBtnStop     = document.querySelector<HTMLButtonElement>("#btn-stop")!;
const elBtnReset    = document.querySelector<HTMLButtonElement>("#btn-reset")!;
const elFreqBadge   = document.querySelector<HTMLDivElement>("#freq-badge")!;
const elBtnLive     = document.querySelector<HTMLButtonElement>("#btn-live")!;
const elBtnFit      = document.querySelector<HTMLButtonElement>("#btn-fit")!;
const elBtnClear    = document.querySelector<HTMLButtonElement>("#btn-clear")!;
const elPsStatus    = document.querySelector<HTMLDivElement>("#ps-status")!;
const elConnStatus  = document.querySelector<HTMLDivElement>("#conn-status")!;
const elStateBadge  = document.querySelector<HTMLDivElement>("#state-badge")!;
const elWsBadge     = document.querySelector<HTMLDivElement>("#ws-badge")!;
const elStatus      = document.querySelector<HTMLDivElement>("#status")!;
const elSampleCount = document.querySelector<HTMLSpanElement>("#sample-count")!;
const elChList      = document.querySelector<HTMLDivElement>("#ch-list")!;
const elPlotArea    = document.querySelector<HTMLElement>("#plot-area")!;

const savedBoardIP = localStorage.getItem(BOARD_IP_STORAGE_KEY);
if (savedBoardIP) elIp.value = savedBoardIP;

// ── Subplot count selector ────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-n]").forEach(btn => {
  btn.addEventListener("click", () => setNSubplots(Number(btn.dataset.n)));
});

// ── αβ ↔ abc toggle ───────────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-mode]").forEach(btn => {
  btn.classList.toggle("active", btn.dataset.mode === displayMode);
  btn.addEventListener("click", () => setDisplayMode(btn.dataset.mode as "ab" | "abc"));
});

// ── Channel list ──────────────────────────────────────────────────────────────
let valSpans: HTMLSpanElement[]     = [];
let subplotBadges: HTMLButtonElement[] = [];

function buildChannelList() {
  elChList.innerHTML = "";
  valSpans = [];
  subplotBadges = [];

  CHANNELS.forEach((ch, i) => {
    const row = document.createElement("label");
    row.className = "ch-row";

    const dot = document.createElement("span");
    dot.className = "ch-dot";
    dot.style.background = ch.color;

    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = visible[i]; cb.className = "ch-cb";

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
}

buildChannelList();

function setDisplayMode(mode: "ab" | "abc") {
  if (mode === displayMode) return;
  displayMode = mode;
  localStorage.setItem(DISPLAY_MODE_STORAGE_KEY, mode);
  CHANNELS = mode === "abc" ? CHANNELS_ABC : CHANNELS_AB;
  N_CH = CHANNELS.length;
  chSubplot = CHANNELS.map(c => Math.min(c.defaultSubplot, nSubplots - 1));
  visible = Array(N_CH).fill(true);
  document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-mode]").forEach(b => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  buildChannelList();
  buildPlots();
  scheduleRender();
}

// ── Subplot helpers ───────────────────────────────────────────────────────────
function getChIdx(s: number): number[] {
  return CHANNELS.map((_, i) => i).filter(i => chSubplot[i] === s);
}

function plotHeight(): number {
  return Math.max(80, Math.floor(elPlotArea.clientHeight / nSubplots));
}

function setNSubplots(n: number) {
  nSubplots = n;
  document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-n]").forEach(b => {
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

// Min/max decimation: for each bucket, emit the sample at the min AND max of
// the primary channel (channel 0) in time order. This preserves the signal
// envelope so AC waveforms don't alias into jagged noise at low zoom levels.
// smoothWin > 1 activates a moving-average pre-filter that removes PWM
// switching ripple. Win=10 ≈ one 1 kHz PWM period at 10 kHz sample rate.
let smoothWin = 1;

function decimateAndProject(maxPts: number): { xs: number[]; ys: number[][] } {
  const n = tBuf.length;
  if (n === 0) return { xs: [], ys: Array.from({ length: N_CH }, () => []) };

  // Helper: return the smoothed value for channel c at index i.
  // When smoothWin=1 this is just a direct read (no overhead).
  const smoothed = smoothWin <= 1
    ? (c: number, i: number) => CHANNELS[c].read(samplesBuf[i])
    : (c: number, i: number) => {
        const half = Math.floor(smoothWin / 2);
        const lo = Math.max(0, i - half);
        const hi = Math.min(n - 1, i + half);
        let sum = 0;
        for (let k = lo; k <= hi; k++) sum += CHANNELS[c].read(samplesBuf[k]);
        return sum / (hi - lo + 1);
      };

  if (n <= maxPts) {
    return {
      xs: tBuf.slice(),
      ys: Array.from({ length: N_CH }, (_, c) => samplesBuf.map((_, i) => smoothed(c, i))),
    };
  }

  const buckets = Math.max(1, Math.floor(maxPts / 2));
  const bucketSize = n / buckets;
  const xs: number[] = [];
  const ys: number[][] = Array.from({ length: N_CH }, () => []);

  for (let b = 0; b < buckets; b++) {
    const i0 = Math.floor(b * bucketSize);
    const i1 = Math.min(Math.floor((b + 1) * bucketSize), n) - 1;
    if (i0 > i1) continue;

    if (smoothWin > 1) {
      // In smooth mode: one point per bucket (mean), no min/max needed.
      const mid = Math.floor((i0 + i1) / 2);
      xs.push(tBuf[mid]);
      for (let c = 0; c < N_CH; c++) ys[c].push(smoothed(c, mid));
    } else {
      // Raw mode: min/max envelope to preserve AC waveform peaks.
      let minIdx = i0, maxIdx = i0;
      let minV = CHANNELS[0].read(samplesBuf[i0]);
      let maxV = minV;
      for (let i = i0 + 1; i <= i1; i++) {
        const v = CHANNELS[0].read(samplesBuf[i]);
        if (v < minV) { minV = v; minIdx = i; }
        if (v > maxV) { maxV = v; maxIdx = i; }
      }
      const [first, second] = minIdx <= maxIdx ? [minIdx, maxIdx] : [maxIdx, minIdx];
      xs.push(tBuf[first]);
      for (let c = 0; c < N_CH; c++) ys[c].push(CHANNELS[c].read(samplesBuf[first]));
      if (first !== second) {
        xs.push(tBuf[second]);
        for (let c = 0; c < N_CH; c++) ys[c].push(CHANNELS[c].read(samplesBuf[second]));
      }
    }
  }

  return { xs, ys };
}

// Shared cursor sync key — all subplots show the cursor at the same x position.
const cursorSync = (uPlot as any).sync("hil");

// X-axis sync guard — prevents recursive setScale loops when propagating.
let scaleSyncing = false;

function syncXScale(source: uPlot) {
  if (scaleSyncing) return;
  scaleSyncing = true;
  const { min, max } = source.scales.x;
  plots.forEach(p => { if (p !== source) p.setScale("x", { min: min ?? null, max: max ?? null }); });
  // leaving live mode when user zooms/pans
  if (min != null || max != null) liveMode = false;
  scaleSyncing = false;
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

  const maxPts = Math.max(600, w * 2);
  const { xs, ys } = decimateAndProject(maxPts);

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
      value: (_u: uPlot) => CHANNELS[ci].unit,
    }));

    const yLabel = chIdx.map(ci => CHANNELS[ci].unit).find(Boolean) ?? "Y";

    const p = new uPlot(
      {
        width: w,
        height: h,
        pxAlign: 0,
        cursor: {
          show: true,
          drag: { x: true, y: false, uni: 50 },
          sync: { key: cursorSync.key },
        },
        scales: { x: { time: false } },
        axes: [
          { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" } },
          {
            stroke: "#3a5575",
            grid: { stroke: "#0e1d30", width: 1 },
            ticks: { stroke: "#0e1d30" },
            label: yLabel,
          },
        ],
        series,
        legend: { show: true, live: true },
        hooks: {
          setScale: [(u: uPlot, key: string) => { if (key === "x") syncXScale(u); }],
        },
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
    const { xs, ys } = decimateAndProject(maxPts);

    plots.forEach((p, s) => {
      const chIdx = getChIdx(s);
      p.setData([xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData);
    });
    if (liveMode) {
      scaleSyncing = true;
      plots.forEach(p => p.setScale("x", { min: null, max: null }));
      scaleSyncing = false;
    }

    elSampleCount.textContent = `${sampleCount.toLocaleString()} samples`;
  });
}

// ── Telemetry events ──────────────────────────────────────────────────────────
api.onTelemetry((samples: Sample[]) => {
  if (!Array.isArray(samples) || samples.length === 0) return;
  lastSampleAt = performance.now();

  for (const s of samples) {
    const t = (performance.now() - t0) / 1000;
    tBuf.push(t);
    samplesBuf.push(s);
    sampleCount++;
  }

  if (tBuf.length > MAX_SAMPLES) {
    const drop = tBuf.length - MAX_SAMPLES;
    tBuf.splice(0, drop);
    samplesBuf.splice(0, drop);
  }

  const last = samples[samples.length - 1];
  CHANNELS.forEach((ch, i) => {
    valSpans[i].textContent = ch.read(last).toFixed(4);
  });

  scheduleRender();
});

// ── Status helpers ────────────────────────────────────────────────────────────
function setStatus(text: string, kind: "ok" | "error" | "idle" = "idle") {
  elStatus.textContent = `● ${text}`;
  elStatus.className = `status-bar${kind !== "idle" ? " " + kind : ""}`;
}

function showPsStatus(text: string, ok: boolean) {
  elPsStatus.textContent = text;
  elPsStatus.className = `ps-status ${ok ? "ps-status-ok" : "ps-status-err"}`;
}

function showConnStatus(text: string, ok: boolean) {
  elConnStatus.textContent = text;
  elConnStatus.className = `ps-status ${ok ? "ps-status-ok" : "ps-status-err"}`;
}

function setStateBadge(state: string) {
  lastBoardState = state;
  elStateBadge.textContent = state.toUpperCase();
  elStateBadge.className = `state-badge state-${state}`;
}

function setTelemBadge(active: boolean, stalled: boolean) {
  if (!active) {
    elWsBadge.className   = "badge badge-idle";
    elWsBadge.textContent = "● TELEM OFF";
  } else if (stalled) {
    elWsBadge.className   = "badge badge-error";
    elWsBadge.textContent = "● NO STREAM";
  } else {
    elWsBadge.className   = "badge badge-streaming";
    elWsBadge.textContent = "● TELEM ON";
  }
}

// ── Param push ────────────────────────────────────────────────────────────────
function getNpp()  { return Math.max(1, Number(elNpp.value) || 2); }

function readParams() {
  const npp      = getNpp();
  const rpm      = Number(elRpm.value);
  const ratedRpm = Number(elRatedRpm.value) || 1800;
  return {
    ip:        elIp.value.trim(),
    freq:      rpm * npp / 60,        // electrical Hz
    baseFreq:  ratedRpm * npp / 60,   // base electrical Hz (rated V at this freq)
    vdc:       Number(elVdc.value),
    torque:    Number(elTorque.value),
    maxVPu:    Number(elMaxVPu.value),
    accelTime: Number(elAccelTime.value),
  };
}

function rememberBoardIP(ip: string) {
  if (ip) localStorage.setItem(BOARD_IP_STORAGE_KEY, ip);
}

function applyBoardIP(ip?: string) {
  if (!ip || ip === elIp.value.trim()) return;
  elIp.value = ip;
  rememberBoardIP(ip);
  showConnStatus(`Using board ${ip}`, true);
}

async function withButton<T>(btn: HTMLButtonElement, fn: () => Promise<T>): Promise<T | null> {
  btn.disabled = true;
  try {
    return await fn();
  } catch (e) {
    showPsStatus(String(e), false);
    setStatus(`Command failed: ${String(e)}`, "error");
    return null;
  } finally {
    btn.disabled = false;
  }
}

function applyResponse(s: HilStatus | null, opts: { hydrate?: boolean } = {}) {
  if (!s) return;
  setStateBadge(s.state);
  applyBoardIP(s.board_ip);
  // Hydrate form fields only when the board carries a real config (running/paused).
  // After Stop the board reports zeroed safe-defaults — we don't want those
  // clobbering whatever the user typed in.
  const hydrate = opts.hydrate ?? (s.state !== "stopped" && s.state !== "idle");
  if (hydrate) {
    const npp = getNpp();
    if (s.freq_hz      != null) elRpm.value       = String(Math.round(s.freq_hz * 60 / npp));
    if (s.base_freq_hz != null) elRatedRpm.value  = String(Math.round(s.base_freq_hz * 60 / npp));
    if (s.vdc_v        != null) elVdc.value       = String(s.vdc_v);
    if (s.torque_nm    != null) elTorque.value    = String(s.torque_nm);
    if (s.max_v_pu     != null) elMaxVPu.value    = String(s.max_v_pu);
    if (s.accel_time_s != null) elAccelTime.value = String(s.accel_time_s);
  }
  if (s.freq_actual_hz != null) {
    const npp = getNpp();
    const actualRpm = Math.round(s.freq_actual_hz * 60 / npp);
    elFreqBadge.textContent = `${actualRpm} RPM`;
    elFreqBadge.className = actualRpm > 0 ? "badge badge-streaming" : "badge badge-idle";
  }
  const tx = s.telem_packets_sent != null ? ` tx=${s.telem_packets_sent}` : "";
  const txErr = s.telem_send_errors ? ` tx_err=${s.telem_send_errors}` : "";
  const tlm = `freq=${s.freq_hz.toFixed(1)}Hz vdc=${s.vdc_v.toFixed(0)}V τ=${s.torque_nm.toFixed(2)} en=${s.enable}${tx}${txErr} → ${s.state.toUpperCase()}`;
  showPsStatus(tlm, true);
}

function resetPlotBuffer() {
  liveMode = true;
  tBuf.length = 0;
  samplesBuf.length = 0;
  sampleCount = 0;
  t0 = performance.now();
  plots.forEach((p, s) => {
    const chIdx = getChIdx(s);
    p.setData([[], ...chIdx.map(() => [])] as uPlot.AlignedData);
  });
  elSampleCount.textContent = "0 samples";
}

// ── Button handlers ───────────────────────────────────────────────────────────
elBtnDiscover.addEventListener("click", () => withButton(elBtnDiscover, async () => {
  showConnStatus("Searching on LAN...", true);
  const d = await api.DiscoverBoard(elIp.value.trim()) as DiscoveryResponse;
  elIp.value = d.ip;
  rememberBoardIP(d.ip);
  const id = d.mac ? ` (${d.mac})` : "";
  showConnStatus(`Found ${d.name || "HIL"} at ${d.ip}${id}`, true);
  setStatus(`Board found: ${d.ip}`, "ok");
  if (d.state) setStateBadge(d.state);
}));

elBtnConnect.addEventListener("click", () => withButton(elBtnConnect, async () => {
  const { ip } = readParams();
  // single hello → attaches telemetry to this PC and pulls current state
  const s = await api.AttachTelemetry(ip) as HilStatus;
  const boardIP = s.board_ip || ip;
  applyBoardIP(boardIP);
  rememberBoardIP(boardIP);
  showConnStatus(`Connected to ${boardIP} — daemon ${s.state}`, true);
  setStatus(`Connected to ${boardIP}`, "ok");
  applyResponse(s);
}));

elBtnApply.addEventListener("click", () => withButton(elBtnApply, async () => {
  const { ip, freq, vdc, torque, baseFreq, maxVPu, accelTime } = readParams();
  const s = await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, accelTime, false, false, false) as HilStatus;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Params applied", "ok");
  applyResponse(s);
}));

elBtnRun.addEventListener("click", () => withButton(elBtnRun, async () => {
  const { ip, freq, vdc, torque, baseFreq, maxVPu, accelTime } = readParams();
  resetPlotBuffer();
  await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, accelTime, false, false, true);
  const s = await api.Run(ip) as HilStatus;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Running", "ok");
  applyResponse(s);
}));

elBtnReset.addEventListener("click", () => withButton(elBtnReset, async () => {
  const { ip } = readParams();
  const s = await api.ResetSolver(ip) as HilStatus;
  applyBoardIP(s.board_ip);
  setStatus("Solver states reset", "ok");
  applyResponse(s);
}));

elBtnStop.addEventListener("click", () => withButton(elBtnStop, async () => {
  const { ip } = readParams();
  const s = await api.StopController(ip) as HilStatus;
  applyBoardIP(s.board_ip);
  // Board stops its telem thread on Stop — reflect it in the badge. The plot
  // is intentionally left intact so the user can inspect the last run; the
  // next Run will clear it. Form values also stay (applyResponse won't
  // hydrate on the "stopped" state).
  setTelemBadge(false, false);
  setStatus("Stopped (daemon alive — can Run again)", "ok");
  applyResponse(s);
}));

function fitPlots() {
  liveMode = false;
  scaleSyncing = true;
  plots.forEach(p => p.setScale("x", { min: null, max: null }));
  scaleSyncing = false;
  setStatus("Plot fitted to buffered data", "ok");
}

function enableLiveMode() {
  liveMode = true;
  scaleSyncing = true;
  plots.forEach(p => p.setScale("x", { min: null, max: null }));
  scaleSyncing = false;
  setStatus("Live mode", "ok");
}

elBtnFit.addEventListener("click", fitPlots);
elBtnLive.addEventListener("click", enableLiveMode);

const elBtnSmooth = document.querySelector<HTMLButtonElement>("#btn-smooth")!;
elBtnSmooth.addEventListener("click", () => {
  smoothWin = smoothWin <= 1 ? 10 : 1;
  elBtnSmooth.classList.toggle("active", smoothWin > 1);
  scheduleRender();
});

function detachOnExit() {
  const ip = elIp.value.trim();
  if (!ip || isWails) return;
  const payload = JSON.stringify({ ip });
  if (navigator.sendBeacon) {
    navigator.sendBeacon("/api/detach", new Blob([payload], { type: "application/json" }));
    return;
  }
  fetch("/api/detach", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

window.addEventListener("pagehide", detachOnExit);

elBtnClear.addEventListener("click", resetPlotBuffer);

// ── Stats polling ─────────────────────────────────────────────────────────────
let prevSamplesRx = 0;
let prevStatsAt   = performance.now();
setInterval(async () => {
  try {
    const s = await api.GetStats() as Record<string, number>;
    const now = performance.now();
    const dt  = (now - prevStatsAt) / 1000;
    const fs  = dt > 0 ? Math.round((s.samples_rx - prevSamplesRx) / dt) : 0;
    prevSamplesRx = s.samples_rx;
    prevStatsAt   = now;
    (document.querySelector("#st-fs")   as HTMLElement).textContent = fs > 0 ? fs.toLocaleString() : "—";
    (document.querySelector("#st-rx")   as HTMLElement).textContent = s.samples_rx?.toLocaleString() ?? "—";
    (document.querySelector("#st-pkt")  as HTMLElement).textContent = s.packets_rx?.toLocaleString() ?? "—";
    (document.querySelector("#st-drop") as HTMLElement).textContent = s.dropped?.toLocaleString()    ?? "—";
    (document.querySelector("#st-crc")  as HTMLElement).textContent = String(s.crc_errors ?? "—");
    (document.querySelector("#st-seq")  as HTMLElement).textContent = String(s.seq_missed  ?? "—");
  } catch { /* ignore */ }
}, 2000);

// ── Background status poll — keeps FSM badge accurate ─────────────────────────
setInterval(async () => {
  const ip = elIp.value.trim();
  if (!ip) return;
  try {
    const s = await api.GetStatus(ip) as HilStatus;
    applyBoardIP(s.board_ip);
    setStateBadge(s.state);
    // refresh telem badge: if board says telem_active but we haven't seen
    // samples in 2s, flag it as stalled
    const stalled = (performance.now() - lastSampleAt) > 2500;
    setTelemBadge(s.telem_active === 1, stalled);
  } catch {
    // board unreachable: state may have drifted — flag it
    elStateBadge.textContent = "OFFLINE";
    elStateBadge.className = "state-badge state-offline";
    setTelemBadge(false, true);
  }
}, 1000);

// ── Show local IP on startup ──────────────────────────────────────────────────
api.GetLocalIP().then(ip => {
  setStatus(`Ready — ${isWails ? "local" : "gateway"} IP: ${ip}`, "ok");
  // suppress unused warning
  void lastBoardState;
}).catch(() => {});
