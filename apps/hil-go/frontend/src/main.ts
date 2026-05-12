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
  freq_hz: number; vdc_v: number; torque_nm: number;
  base_freq_hz: number; max_v_pu: number; boost_v_pu: number;
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
  SetParams(ip: string, freqHz: number, vdcV: number, torqueNm: number, baseFreqHz: number, maxVPu: number, boostVPu: number, enable: boolean, applyEnable: boolean, decim: number, attachTelem: boolean): Promise<HilStatus>;
  GetStatus(ip: string): Promise<HilStatus>;
  Run(ip: string): Promise<HilStatus>;
  Pause(ip: string): Promise<HilStatus>;
  StopController(ip: string): Promise<HilStatus>;
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
  SetParams(ip, freqHz, vdcV, torqueNm, baseFreqHz, maxVPu, boostVPu, enable, applyEnable, decim, attachTelem) {
    const body: Record<string, unknown> = {
      ip,
      freq_hz: freqHz,
      vdc_v: vdcV,
      torque_nm: torqueNm,
      base_freq_hz: baseFreqHz,
      max_v_pu: maxVPu,
      boost_v_pu: boostVPu,
      decim,
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
let t0 = performance.now();
let lastBoardState: string = "idle";
let lastSampleAt = 0;             // ms — for "stream stalled" detection
let liveMode = true;

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
          <label>Freq (Hz)</label>
          <input id="freq" type="number" value="60" min="0" max="200" step="1" class="write-input" />
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
          <label>Base Freq (Hz)</label>
          <input id="base-freq" type="number" value="60" min="1" max="400" step="1" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Max V/F (pu)</label>
          <input id="max-vpu" type="number" value="1" min="0" max="1" step="0.01" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Boost (pu)</label>
          <input id="boost-vpu" type="number" value="0" min="0" max="1" step="0.01" class="write-input" />
        </div>
        <div class="field-inline">
          <label>Decim</label>
          <input id="decim" type="number" value="0" min="0" max="100000" step="1" class="write-input" />
        </div>
        <div class="btn-row" style="margin-top:8px">
          <button id="btn-apply" class="btn btn-write">Apply Params</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">CONTROL</div>
        <div class="btn-row">
          <button id="btn-run"   class="btn btn-primary" title="Enable motor with current params">▶ Run</button>
          <button id="btn-stop"  class="btn btn-danger" title="Disable motor, reset params (daemon stays alive)">■ Stop</button>
        </div>
        <div id="ps-status" class="ps-status hidden"></div>
      </section>

      <section class="panel">
        <div class="panel-title">PLOTS</div>

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
          <button id="btn-live" class="btn btn-sm">Live</button>
          <button id="btn-fit" class="btn btn-sm">Fit</button>
          <button id="btn-clear" class="btn btn-sm">Clear plot</button>
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
const elBaseFreq    = document.querySelector<HTMLInputElement>("#base-freq")!;
const elMaxVPu      = document.querySelector<HTMLInputElement>("#max-vpu")!;
const elBoostVPu    = document.querySelector<HTMLInputElement>("#boost-vpu")!;
const elDecim       = document.querySelector<HTMLInputElement>("#decim")!;
const elBtnConnect  = document.querySelector<HTMLButtonElement>("#btn-connect")!;
const elBtnDiscover = document.querySelector<HTMLButtonElement>("#btn-discover")!;
const elBtnApply    = document.querySelector<HTMLButtonElement>("#btn-apply")!;
const elBtnRun      = document.querySelector<HTMLButtonElement>("#btn-run")!;
const elBtnStop     = document.querySelector<HTMLButtonElement>("#btn-stop")!;
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
      value: opts => CHANNELS[ci].unit,
    }));

    const yPos = chIdx.map(ci => CHANNELS[ci].name).join(", ");

    const p = new uPlot(
      {
        width: w,
        height: h,
        pxAlign: 0,
        cursor: { show: true, drag: { x: true, y: false, uni: 50 } },
        scales: { x: { time: false } },
        axes: [
          { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" } },
          {
            stroke: "#3a5575",
            grid: { stroke: "#0e1d30", width: 1 },
            ticks: { stroke: "#0e1d30" },
            label: yPos || "Y",
          },
        ],
        series,
        legend: { show: true, live: true },
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
      if (liveMode) p.setScale("x", { min: null, max: null });
    });

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
    CHANNELS.forEach((ch, i) => yBufs[i].push(s[ch.key as ChKey]));
    sampleCount++;
  }

  if (tBuf.length > MAX_SAMPLES) {
    const drop = tBuf.length - MAX_SAMPLES;
    tBuf.splice(0, drop);
    for (let i = 0; i < N_CH; i++) yBufs[i].splice(0, drop);
  }

  const last = samples[samples.length - 1];
  CHANNELS.forEach((ch, i) => {
    valSpans[i].textContent = last[ch.key as ChKey].toFixed(4);
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
function readParams() {
  return {
    ip:     elIp.value.trim(),
    freq:   Number(elFreq.value),
    vdc:    Number(elVdc.value),
    torque: Number(elTorque.value),
    baseFreq: Number(elBaseFreq.value),
    maxVPu: Number(elMaxVPu.value),
    boostVPu: Number(elBoostVPu.value),
    decim: Number(elDecim.value),
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
    if (s.freq_hz   != null) elFreq.value   = String(s.freq_hz);
    if (s.vdc_v     != null) elVdc.value    = String(s.vdc_v);
    if (s.torque_nm != null) elTorque.value = String(s.torque_nm);
    if (s.base_freq_hz != null) elBaseFreq.value = String(s.base_freq_hz);
    if (s.max_v_pu     != null) elMaxVPu.value   = String(s.max_v_pu);
    if (s.boost_v_pu   != null) elBoostVPu.value = String(s.boost_v_pu);
  }
  const tx = s.telem_packets_sent != null ? ` tx=${s.telem_packets_sent}` : "";
  const txErr = s.telem_send_errors ? ` tx_err=${s.telem_send_errors}` : "";
  const tlm = `freq=${s.freq_hz.toFixed(1)}Hz vdc=${s.vdc_v.toFixed(0)}V τ=${s.torque_nm.toFixed(2)} en=${s.enable}${tx}${txErr} → ${s.state.toUpperCase()}`;
  showPsStatus(tlm, true);
}

function resetPlotBuffer() {
  liveMode = true;
  tBuf.length = 0;
  for (let i = 0; i < N_CH; i++) yBufs[i].length = 0;
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
  const { ip, freq, vdc, torque, baseFreq, maxVPu, boostVPu, decim } = readParams();
  // applyEnable=false → params only; do not toggle FSM
  const s = await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, boostVPu, false, false, decim, true) as HilStatus;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Params applied", "ok");
  applyResponse(s);
}));

elBtnRun.addEventListener("click", () => withButton(elBtnRun, async () => {
  const { ip, freq, vdc, torque, baseFreq, maxVPu, boostVPu, decim } = readParams();
  // Each Run is a fresh experiment: clear the plot before the board starts
  // pushing samples so the time axis restarts at 0.
  resetPlotBuffer();
  // Push current params first (so Run uses fresh values), then enable
  await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, boostVPu, false, false, decim, true);
  const s = await api.Run(ip) as HilStatus;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Running", "ok");
  applyResponse(s);
}));

elBtnStop.addEventListener("click", () => withButton(elBtnStop, async () => {
  const { ip } = readParams();
  const s = await api.StopController(ip) as HilStatus;
  applyBoardIP(s.board_ip);
  // Board stops its telem thread on Stop — reflect it in the badge.
  // The form values stay as the user typed them (applyResponse won't hydrate
  // on the "stopped" state) so the next Run reuses the same config.
  setTelemBadge(false, false);
  resetPlotBuffer();
  setStatus("Stopped (daemon alive — can Run again)", "ok");
  applyResponse(s);
}));

function fitPlots() {
  liveMode = false;
  plots.forEach(p => p.setScale("x", { min: null, max: null }));
  setStatus("Plot fitted to buffered data", "ok");
}

function enableLiveMode() {
  liveMode = true;
  plots.forEach(p => p.setScale("x", { min: null, max: null }));
  setStatus("Live plot mode", "ok");
}

elBtnFit.addEventListener("click", fitPlots);
elBtnLive.addEventListener("click", enableLiveMode);

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
setInterval(async () => {
  try {
    const s = await api.GetStats() as Record<string, number>;
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
