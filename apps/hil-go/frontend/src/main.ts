import "uplot/dist/uPlot.min.css";
import "./styles.css";
import uPlot from "uplot";
import * as WailsRuntime from "../wailsjs/runtime/runtime";
import * as WailsApp from "../wailsjs/go/main/App";
import { ViewportController, selectTier, indicesForWindow, type TierMeta } from "./viewport";
import { TileCache, type FetchedTile } from "./tilecache";
import { type TileData } from "./tile";

// ── Types ─────────────────────────────────────────────────────────────────────
type Sample = { t_cycles?: number; epoch?: number; Ia: number; Ib: number; FluxA: number; FluxB: number; Speed: number; TL?: number };
type PwmEvent = { t_cycles: number; a: number; b: number; c: number; mask: number; epoch: number };
type PwmPlotEvent = PwmEvent & { t_sec: number };
type PwmEventBatch = { type: string; seq: number; clock_hz: number; status: number; events: PwmEvent[] };
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
  telem_source?: string;
  telem_hz?: number;
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
  onPwmEvents(cb: (batch: PwmEventBatch) => void): void;
  DiscoverBoard(ip?: string): Promise<DiscoveryResponse>;
  SetParams(ip: string, freqHz: number, vdcV: number, torqueNm: number, baseFreqHz: number, maxVPu: number, accelTimeSec: number, enable: boolean, applyEnable: boolean, attachTelem: boolean): Promise<HilStatus>;
  ProgramMotor(ip: string, rs: number, rr: number, ls: number, lr: number, lm: number, j: number, npp: number): Promise<HilStatus>;
  GetStatus(ip: string): Promise<HilStatus>;
  Run(ip: string): Promise<HilStatus>;
  Pause(ip: string): Promise<HilStatus>;
  StopController(ip: string): Promise<HilStatus>;
  ResetSolver(ip: string): Promise<HilStatus>;
  AttachTelemetry(ip: string): Promise<HilStatus>;
  DetachTelemetry(ip: string): Promise<HilStatus>;
  GetStats(): Promise<Record<string, number>>;
  GetLocalIP(): Promise<string>;
  SaveRun?(dataB64: string, name: string): Promise<void>;
  LoadRun?(): Promise<string>;
};

const isWails = typeof window !== "undefined" && !!(window as any).go?.main?.App;
const BOARD_IP_STORAGE_KEY = "hil-board-ip";

function gatewayURL(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const clean = path.replace(/^\/+/, "");
  const proxy = window.location.pathname.match(/^(.*\/proxy\/\d+\/)/);
  const base = proxy ? proxy[1] : "/";
  return base + clean;
}

function responseError(res: Response, text: string): string {
  const title = text.match(/<title>(.*?)<\/title>/is)?.[1]?.replace(/\s+/g, " ").trim();
  if (title) return title;
  return text || `HTTP ${res.status}: ${res.statusText}`;
}

async function postJSON<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(gatewayURL(url), {
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
  const res = await fetch(gatewayURL(url));
  const text = await res.text();
  let parsed: any = null;
  try { parsed = text ? JSON.parse(text) : null; } catch {}
  if (!res.ok) throw new Error(parsed?.error || responseError(res, text));
  if (parsed == null) throw new Error("empty response from gateway");
  return parsed as T;
}

let sharedEvents: EventSource | null = null;
function getSharedEvents(): EventSource {
  if (!sharedEvents) sharedEvents = new EventSource(gatewayURL("/events"));
  return sharedEvents;
}

const api: HilApi = isWails ? {
  onTelemetry(cb) {
    WailsRuntime.EventsOn("telemetry", cb);
  },
  onPwmEvents(cb) {
    WailsRuntime.EventsOn("pwm_events", cb);
  },
  DiscoverBoard() {
    return WailsApp.DiscoverBoard() as Promise<DiscoveryResponse>;
  },
  SetParams: WailsApp.SetParams as HilApi["SetParams"],
  ProgramMotor(ip, rs, rr, ls, lr, lm, j, npp) {
    return (window as any).go.main.App.ProgramMotor(ip, rs, rr, ls, lr, lm, j, npp) as Promise<HilStatus>;
  },
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
  SaveRun: (WailsApp as any).SaveRun as HilApi["SaveRun"],
  LoadRun: (WailsApp as any).LoadRun as HilApi["LoadRun"],
} : {
  onTelemetry(cb) {
    const events = getSharedEvents();
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
  onPwmEvents(cb) {
    const events = getSharedEvents();
    events.addEventListener("pwm_events", ev => {
      try { cb(JSON.parse((ev as MessageEvent).data)); } catch {}
    });
  },
  DiscoverBoard(ip) {
    return postJSON<DiscoveryResponse>("/api/discover", { ip });
  },
  ProgramMotor(ip, rs, rr, ls, lr, lm, j, npp) {
    return postJSON<HilStatus>("/api/motor", { ip, rs, rr, ls, lr, lm, j, npp });
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
  dash?: number[];
};

// Pole pairs cached from the motor-model input — used to compute electromagnetic
// torque from telemetry without a DOM read per decimated point.
// FluxA/FluxB are *rotor* fluxes (flux_rotor_alpha/beta_o from the TIM
// solver), so Te = 1.5·npp·(Lm/Lr_total)·(Φrα·Iβ − Φrβ·Iα).
let motorNpp = 2;
let motorLm  = 0.1099442;   // defaults match firmware motor_params
let motorLr  = 0.1099442 + 0.0063264;  // lm + lr_leak

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
  { name: "Te",    unit: "N·m",   color: "#ffb74d", read: s => 1.5 * motorNpp * (motorLm / motorLr) * (s.FluxA * s.Ib - s.FluxB * s.Ia), defaultSubplot: 3 },
  { name: "TL",    unit: "N·m",   color: "#b0bec5", read: s => s.TL ?? 0, defaultSubplot: 3, dash: [6, 4] },
];

const CHANNELS_ABC: ChDef[] = [
  { name: "Ia",    unit: "A",     color: "#4fc3f7", read: s => xa(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Ib",    unit: "A",     color: "#ef9a9a", read: s => xb(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Ic",    unit: "A",     color: "#ffd54f", read: s => xc(s.Ia, s.Ib),       defaultSubplot: 0 },
  { name: "Φa",    unit: "Wb",    color: "#81c784", read: s => xa(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Φb",    unit: "Wb",    color: "#ce93d8", read: s => xb(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Φc",    unit: "Wb",    color: "#a5d6a7", read: s => xc(s.FluxA, s.FluxB), defaultSubplot: 1 },
  { name: "Speed", unit: "RPM",   color: "#ffcc80", read: s => s.Speed * 60 / (2 * Math.PI), defaultSubplot: 2 },
  { name: "Te",    unit: "N·m",   color: "#ffb74d", read: s => 1.5 * motorNpp * (motorLm / motorLr) * (s.FluxA * s.Ib - s.FluxB * s.Ia), defaultSubplot: 3 },
  { name: "TL",    unit: "N·m",   color: "#b0bec5", read: s => s.TL ?? 0, defaultSubplot: 3, dash: [6, 4] },
];

const DISPLAY_MODE_STORAGE_KEY = "hil-display-mode";
let displayMode: "ab" | "abc" = (localStorage.getItem(DISPLAY_MODE_STORAGE_KEY) as "ab" | "abc") || "abc";
let CHANNELS: ChDef[] = displayMode === "abc" ? CHANNELS_ABC : CHANNELS_AB;
let N_CH = CHANNELS.length;
// Full-rate detail arrives through the cursor-based raw transport. The SSE
// extrema stream is only a low-rate fallback if that transport is unavailable.
const TELEM_DISPLAY_HZ = 100_000;
const MAX_SAMPLES = 600_000;  // approximately 6 s of full-rate detail
// Long-history overview: one 100 ms bucket contains about six 60 Hz cycles.
// Each bucket keeps extrema from every independent raw state, so derived ABC
// channels and flux are not projected from Ialpha extrema only.
const OVERVIEW_EVERY = 10_000;
const MAX_OVERVIEW_SAMPLES = 144_000;
// Both telemetry samples and PWM events are timestamped by the SAME run-local
// FPGA counter (hil_time <= pwm_cap_time in RTL). Using hardware time for both
// gives exact alignment. Two edge-cases are handled:
//   • Counter frozen when solver is idle → duplicate t_cycles → enforce
//     strict monotonicity by nudging forward by a nominal period.
//   • Counter resets to 0 on each run (epoch++) → clear telemetry buffers
//     on epoch change so old samples never bleed into the new run's view.
const HW_CLOCK_HZ             = 100_000_000;
const TELEM_NOMINAL_PERIOD_S  = 1 / TELEM_DISPLAY_HZ;

// ── App state ─────────────────────────────────────────────────────────────────
const tBuf: number[]      = [];
const samplesBuf: Sample[] = [];   // display-rate αβ samples parallel to tBuf
// Overview buffers — min+max envelope pairs per OVERVIEW_EVERY raw samples.
// Used for rendering when the view extends further back than the high-res buffer.
const ovTBuf: number[]    = [];
const ovSBuf:  Sample[]   = [];
let   ovCounter            = 0;
// Extrema are tracked for the independent raw solver states. Derived ABC and
// torque channels are reconstructed from the retained complete samples.
const OVERVIEW_READERS = [
  (s: Sample) => s.Ia,
  (s: Sample) => s.Ib,
  (s: Sample) => s.FluxA,
  (s: Sample) => s.FluxB,
  (s: Sample) => s.Speed,
];
let ovBucketMinV = Array(OVERVIEW_READERS.length).fill(Infinity) as number[];
let ovBucketMaxV = Array(OVERVIEW_READERS.length).fill(-Infinity) as number[];
let ovBucketMinT = Array(OVERVIEW_READERS.length).fill(0) as number[];
let ovBucketMaxT = Array(OVERVIEW_READERS.length).fill(0) as number[];
let ovBucketMinS = Array<Sample | null>(OVERVIEW_READERS.length).fill(null);
let ovBucketMaxS = Array<Sample | null>(OVERVIEW_READERS.length).fill(null);
let sampleCount = 0;
let lastBoardState: string = "idle";
let lastSampleAt = 0;             // ms — for stream stalled detection
let telemLastRawCycles: number | null = null;
let telemWrapOffsetCycles = 0;
let telemBaseAbsCycles: number | null = null;
let telemEpoch: number | null = null;
let lastTelemPlotTime = -Infinity; // enforces strict monotonicity in tBuf
let pwmClockHz = 100_000_000;
let pwmEpoch: number | null = null;
let pwmActive = false;
const pwmEvents: PwmPlotEvent[] = [];
const PWM_COUNTER_MOD = 2 ** 32;
const MAX_PWM_EVENTS = 1_500_000;
const PWM_OVERVIEW_DT_SEC = 0.005;
const MAX_PWM_OVERVIEW_SAMPLES = 1_500_000;
let pwmLastRawCycles: number | null = null;
let pwmWrapOffsetCycles = 0;
const pwmOverviewT: number[] = [];
const pwmOverviewA: number[] = [];
const pwmOverviewB: number[] = [];
const pwmOverviewC: number[] = [];
let pwmOverviewNextT: number | null = null;
let pwmOverviewAState = 0;
let pwmOverviewBState = 0;
let pwmOverviewCState = 0;
let captureTelemetry = false;
let capturePwm = false;
// ── Scope-style view state ────────────────────────────────────────────────────
// Visible window = [viewEndSec - windowSec, viewEndSec].
//   • Live (paused = false): viewEndSec tracks the latest sample.
//   • Paused: viewEndSec is frozen at the value at pause time and only moves
//     when the user pans (drag-x). Window can still change (wheel / buttons).
// All plots share the SAME x range — we set it explicitly each frame instead
// of relying on uPlot's auto-fit, which avoids the whole "live vs auto-fit"
// guessing game that produced the prior bugs.
let paused = false;
let windowSec = 1.0;
let viewEndSec = 0;
// PWM events are timestamped by the FPGA hardware counter, which drifts from
// the host-paced telemetry clock (it freezes while the solver is idle). So the
// PWM plot needs its own right edge in hardware time: live, it tracks the last
// PWM event; paused, it follows the telemetry window by the drift offset
// captured at pause, so pan/zoom keep both plots on the same relative range.
let pwmViewEndSec = 0;
let pwmTelemOffset = 0;
const WINDOW_PRESETS_MS = [500, 1000, 5000, 30000, 60000];
const WINDOW_MIN_SEC = 0.01;     //  10 ms — finest zoom
const WINDOW_MAX_SEC = 60.0;     // overview may span 60 s; raw detail retains about 6 s

// Subplot state — derived from each channel's defaultSubplot.
let nSubplots = 4;  // currents, flux, speed, torque (load)
let chSubplot: number[] = CHANNELS.map(c => c.defaultSubplot);
let visible:   boolean[] = Array(N_CH).fill(true);
// References for syncing visibility across the side-panel checkbox and the
// per-subplot clickable legend chip. Indexed by channel; rebuilt on each
// buildChannelList()/buildPlots(). pwmVisible persists across plot rebuilds.
let chCheckboxes:  HTMLInputElement[]        = [];
let chLegendItems: (HTMLElement | null)[]    = [];
const pwmVisible = [true, true, true];

// uPlot instances (one per subplot)
let plots: uPlot[] = [];
let pwmPlot: uPlot | null = null;
let isBuilding = false;

// ── DOM ───────────────────────────────────────────────────────────────────────
document.querySelector<HTMLDivElement>("#app")!.innerHTML = `
  <div class="workspace">
    <aside class="sidebar">

      <div class="sidebar-brand">
        <img src="/LSE_LOGO.png" alt="LSE" class="app-logo" />
        <span class="app-name">HIL Monitor</span>
      </div>

      <div class="sidebar-scroll">

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

      <div class="sidebar-tabs" role="tablist" aria-label="HIL panels">
        <button class="tab-btn active" data-tab="plant" type="button">Plant</button>
        <button class="tab-btn" data-tab="control" type="button">Control</button>
        <button class="tab-btn" data-tab="scenario" type="button">Scenarios</button>
        <button class="tab-btn" data-tab="telemetry" type="button">Telemetry</button>
        <button class="tab-btn" data-tab="history" type="button">History</button>
      </div>

      <div class="tab-pane active" data-tab-panel="plant">
        <section class="panel">
          <div class="panel-title">MOTOR MODEL</div>
          <div class="motor-model" aria-label="Induction motor T equivalent model">
            <div class="model-node source">Vs</div>
            <div class="model-part resistor">Rs</div>
            <div class="model-part inductor">Lsσ</div>
            <div class="model-junction"></div>
            <div class="model-part inductor">Lrσ</div>
            <div class="model-part resistor">Rr</div>
            <div class="model-node rotor">jωrψr</div>
            <div class="model-branch"><span>Lm</span></div>
            <div class="model-return"></div>
          </div>
          <div class="field-inline">
            <label title="Número de pares de polos do motor">Pole pairs</label>
            <input id="npp" type="number" value="2" min="1" max="8" step="1" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Resistência do estator usada para recalcular as matrizes do solver">Rs (Ω)</label>
            <input id="motor-rs" type="number" value="0.4396" min="0" step="0.0001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Resistência do rotor usada para recalcular as matrizes do solver">Rr (Ω)</label>
            <input id="motor-rr" type="number" value="0.2826" min="0" step="0.0001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Indutância de dispersão do estator">Ls leak (H)</label>
            <input id="motor-ls" type="number" value="0.0031364" min="0" step="0.000001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Indutância de dispersão do rotor">Lr leak (H)</label>
            <input id="motor-lr" type="number" value="0.0063264" min="0" step="0.000001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Indutância mútua">Lm (H)</label>
            <input id="motor-lm" type="number" value="0.1099442" min="0" step="0.000001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Momento de inércia">J (kg·m²)</label>
            <input id="motor-j" type="number" value="0.4" min="0.0001" step="0.001" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Torque de carga mecânica aplicado ao rotor">Load Torque (N·m)</label>
            <input id="torque" type="number" value="0" min="-200" max="200" step="1" class="write-input" />
          </div>
          <div class="btn-row" style="margin-top:8px">
            <button id="btn-apply-motor" class="btn btn-write" title="Recompute TIM matrices and atomically swap the active motor model at the next solver-safe boundary.">Apply Motor</button>
          </div>
        </section>
      </div>

      <div class="tab-pane" data-tab-panel="control">
        <section class="panel">
          <div class="panel-title">CONTROLLER SETPOINTS</div>
          <div class="field-inline">
            <label title="Tensão do barramento DC usada pelo inversor/controlador">DC link (V)</label>
            <input id="vdc" type="number" value="1240" min="0" max="2000" step="1" class="write-input" />
          </div>
          <div class="field-inline">
            <label>Speed (RPM)</label>
            <input id="rpm" type="number" value="1800" min="0" max="12000" step="60" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Tempo para rampar 0 -> velocidade nominal">Accel (s)</label>
            <input id="accel-time" type="number" value="1" min="0.1" max="300" step="0.5" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Velocidade síncrona nominal — tensão máxima é aplicada aqui">Rated RPM</label>
            <input id="rated-rpm" type="number" value="1800" min="60" max="12000" step="60" class="write-input" />
          </div>
          <div class="field-inline">
            <label title="Tensão máxima de modulação em pu de Vdc/2">Max V/F (pu)</label>
            <input id="max-vpu" type="number" value="1" min="0" max="1" step="0.01" class="write-input" />
          </div>
          <div class="btn-row" style="margin-top:8px">
            <button id="btn-run"   class="btn btn-primary" title="Enable motor with current params (also pulses solver reset)">Run</button>
            <button id="btn-stop"  class="btn btn-danger" title="Disable motor, reset params (daemon stays alive)">Stop</button>
          </div>
          <div class="btn-row" style="margin-top:6px">
            <button id="btn-apply" class="btn btn-sm" title="Apply controller/DC setpoints without changing the motor model">Apply Setpoints</button>
            <button id="btn-reset" class="btn btn-sm" title="Pulse FPGA solver reset — clears integrator states without changing params">Reset solver</button>
          </div>
          <div id="ps-status" class="ps-status hidden"></div>
        </section>
      </div>

      <div class="tab-pane" data-tab-panel="scenario">
        <section class="panel">
          <div class="panel-title">SCENARIO RECIPE</div>
          <div class="scenario-name-row">
            <input id="scenario-name" type="text" value="speed_load_steps" class="write-input scenario-name-input" placeholder="recipe name" />
            <button id="btn-recipe-load" class="btn btn-sm" type="button">Load</button>
            <button id="btn-recipe-save" class="btn btn-sm" type="button">Save</button>
          </div>
          <div class="scenario-toolbar">
            <button id="btn-recipe-add-batch" class="btn btn-sm btn-accent" type="button" title="Save recipe and add to Batch queue">+ Batch</button>
            <button id="btn-recipe-run"  class="btn btn-sm" type="button">▶ Run</button>
            <span   id="scenario-progress" class="scenario-progress"></span>
          </div>
          <div class="scenario-run-card" id="scenario-run-card">
            <div class="scenario-run-status">
              <span class="scenario-run-dot" id="scenario-run-dot"></span>
              <span id="scenario-run-state">Ready</span>
            </div>
            <div class="scenario-run-meter" aria-hidden="true">
              <div id="scenario-run-meter-fill"></div>
            </div>
            <div class="scenario-run-meta">
              <span id="scenario-event-count">7 events</span>
              <span id="scenario-duration">13.5 s</span>
              <span id="scenario-next-event">Next: t=0.0 s</span>
            </div>
          </div>
          <div id="scenario-table" class="scenario-table" aria-label="Scenario event editor">
            <div class="scenario-head">
              <span>t [s]</span>
              <span>Target</span>
              <span>Param</span>
              <span>Value</span>
              <span></span>
            </div>
            <div class="scenario-row">
              <input type="number" value="0.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>control</option>
                <option>motor</option>
                <option>load</option>
              </select>
              <select class="write-input">
                <option>speed_rpm</option>
              </select>
              <input type="number" value="900" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="2.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>control</option>
                <option>motor</option>
                <option>load</option>
              </select>
              <select class="write-input">
                <option>speed_rpm</option>
              </select>
              <input type="number" value="1800" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="4.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>control</option>
                <option>motor</option>
                <option>load</option>
              </select>
              <select class="write-input">
                <option>speed_rpm</option>
              </select>
              <input type="number" value="1200" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="6.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>load</option>
                <option>control</option>
                <option>motor</option>
              </select>
              <select class="write-input">
                <option>torque_nm</option>
              </select>
              <input type="number" value="5" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="8.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>load</option>
                <option>control</option>
                <option>motor</option>
              </select>
              <select class="write-input">
                <option>torque_nm</option>
              </select>
              <input type="number" value="15" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="10.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>load</option>
                <option>control</option>
                <option>motor</option>
              </select>
              <select class="write-input">
                <option>torque_nm</option>
              </select>
              <input type="number" value="30" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="12.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>load</option>
                <option>control</option>
                <option>motor</option>
              </select>
              <select class="write-input">
                <option>torque_nm</option>
              </select>
              <input type="number" value="0" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row scenario-end-row" id="scenario-end-row">
              <input type="number" value="13.5" min="0" step="0.5" class="write-input" title="Auto-stop at this time (s from Run)" />
              <span class="scenario-end-label" style="grid-column:2/6">⏹ END — auto-stop</span>
            </div>
          </div>
          <button id="btn-add-scenario-event" class="btn btn-sm scenario-add" type="button">+ Add event</button>
        </section>

        <section class="panel">
          <div class="panel-title-row">
            <span class="panel-title">BATCH</span>
            <span id="batch-count" class="panel-note">0 queued</span>
          </div>
          <div id="batch-table" class="scenario-table" aria-label="Batch recipe list">
            <div class="batch-head">
              <span>Recipe</span>
              <span>Gap (s)</span>
              <span></span>
              <span></span>
            </div>
            <div class="batch-empty-hint" id="batch-empty-hint">Add saved recipes to run in sequence.</div>
          </div>
          <div class="btn-row" style="margin-top:6px">
            <button id="btn-add-batch-item" class="btn btn-sm" type="button">+ Add</button>
            <button id="btn-batch-run"  class="btn btn-sm" type="button">▶ Run Batch</button>
            <button id="btn-batch-stop" class="btn btn-sm btn-danger" type="button" disabled>■ Stop</button>
          </div>
          <div class="batch-progress-wrap">
            <span id="batch-progress" class="scenario-progress"></span>
            <div class="scenario-run-meter" aria-hidden="true">
              <div id="batch-meter-fill"></div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">CONFIG</div>
          <div class="btn-row">
            <button id="btn-config-export" class="btn btn-sm" type="button">Export JSON</button>
            <button id="btn-config-import" class="btn btn-sm" type="button">Import JSON</button>
          </div>
          <input id="config-import-input" type="file" accept=".json" style="display:none" />
        </section>
      </div>

      <div class="tab-pane" data-tab-panel="history">
        <section class="panel">
          <div class="panel-title-row">
            <span class="panel-title">RUN HISTORY</span>
            <span id="runs-summary" class="panel-note">0 runs</span>
          </div>
          <input id="runs-search" class="write-input" type="search" placeholder="Filter runs" style="margin-bottom:6px" />
          <div id="runs-list" class="runs-list">
            <div class="runs-empty" id="runs-empty">No runs saved yet.</div>
          </div>
        </section>
      </div>

      <div class="tab-pane" data-tab-panel="telemetry">
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
            <span class="subplot-layout-label">Signal</span>
            <div class="subplot-n-group" id="render-group">
              <button class="subplot-n-btn active" data-render="trend" title="Centerline view for readable long windows; raw capture is unchanged">Trend</button>
              <button class="subplot-n-btn" data-render="raw" title="Show min/max envelope from the 100 ksample/s stream">Raw</button>
            </div>
          </div>

          <div class="subplot-layout-row">
            <span class="subplot-layout-label">Subplots</span>
            <div class="subplot-n-group">
              <button class="subplot-n-btn" data-n="1">1</button>
              <button class="subplot-n-btn" data-n="2">2</button>
              <button class="subplot-n-btn" data-n="3">3</button>
              <button class="subplot-n-btn active" data-n="4">4</button>
            </div>
          </div>



          <div class="btn-row" style="margin-top:6px">
            <button id="btn-pause" class="btn btn-sm" title="Pause the live view (or use mouse wheel on plot)">Pause</button>
            <button id="btn-latest" class="btn btn-sm" title="Snap to the latest sample and resume live follow">Latest</button>
            <button id="btn-live" class="btn btn-sm" title="Regrudar a borda direita ao tempo real">⏵ Ao vivo</button>
          </div>

          <div id="ch-list" class="channel-list"></div>

          <div class="btn-row" style="margin-top:8px">
            <button id="btn-clear" class="btn btn-sm">Clear</button>
          </div>
          <div class="btn-row" style="margin-top:6px">
            <button id="btn-save-run" class="btn btn-sm">Save run</button>
            <button id="btn-load-run" class="btn btn-sm">Load run</button>
            <button id="btn-export-csv" class="btn btn-sm">Export CSV</button>
          </div>
          <input id="load-file-input" type="file" accept=".hilbin" style="display:none" />
          <div id="run-meta-badge" class="run-meta-badge hidden"></div>
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
      </div>

      </div>

      <div class="sidebar-footer">
        <div class="sidebar-badges">
          <div id="freq-badge" class="badge badge-idle">— Hz</div>
          <div id="state-badge" class="state-badge state-idle">IDLE</div>
          <div id="ws-badge" class="badge badge-idle">● TELEM OFF</div>
        </div>
        <div id="status" class="status-bar">● Idle</div>
      </div>
    </aside>

    <main class="graph-shell">
      <section class="plot-area" id="plot-area"></section>
      <div class="timeline-control graph-timeline">
        <div class="timeline-head">
          <span class="timeline-title">Timeline</span>
          <span id="timeline-range" class="timeline-range">0.000 - 1.000 s</span>
        </div>
        <div id="timeline-track" class="timeline-track">
          <div id="timeline-window" class="timeline-window">
            <div id="timeline-left" class="timeline-handle timeline-handle-left"></div>
            <div class="timeline-grip"></div>
            <div id="timeline-right" class="timeline-handle timeline-handle-right"></div>
          </div>
        </div>
      </div>
    </main>
  </div>
`;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const elIp          = document.querySelector<HTMLInputElement>("#ip")!;
const elRpm         = document.querySelector<HTMLInputElement>("#rpm")!;
const elAccelTime   = document.querySelector<HTMLInputElement>("#accel-time")!;
const elVdc         = document.querySelector<HTMLInputElement>("#vdc")!;
const elTorque      = document.querySelector<HTMLInputElement>("#torque")!;
const elNpp         = document.querySelector<HTMLInputElement>("#npp")!;
motorNpp = Math.max(1, Number(elNpp.value) || 2);
elNpp.addEventListener("input", () => { motorNpp = Math.max(1, Number(elNpp.value) || 2); });
const elRatedRpm    = document.querySelector<HTMLInputElement>("#rated-rpm")!;
const elMaxVPu      = document.querySelector<HTMLInputElement>("#max-vpu")!;
const elMotorRs     = document.querySelector<HTMLInputElement>("#motor-rs")!;
const elMotorRr     = document.querySelector<HTMLInputElement>("#motor-rr")!;
const elMotorLs     = document.querySelector<HTMLInputElement>("#motor-ls")!;
const elMotorLr     = document.querySelector<HTMLInputElement>("#motor-lr")!;
const elMotorLm     = document.querySelector<HTMLInputElement>("#motor-lm")!;
const elMotorJ      = document.querySelector<HTMLInputElement>("#motor-j")!;
// Keep Lm and Lr_total in sync so the Te formula (Lm/Lr) stays correct.
// Must be placed after elMotorLm/elMotorLr declarations (const is not hoisted).
const syncMotorLmLr = () => {
  motorLm = Math.max(1e-9, Number(elMotorLm.value) || motorLm);
  motorLr = motorLm + Math.max(0, Number(elMotorLr.value) || 0);
};
syncMotorLmLr();  // initialise from current input values
elMotorLm.addEventListener("input", syncMotorLmLr);
elMotorLr.addEventListener("input", syncMotorLmLr);
const elBtnConnect  = document.querySelector<HTMLButtonElement>("#btn-connect")!;
const elBtnDiscover = document.querySelector<HTMLButtonElement>("#btn-discover")!;
const elBtnApply    = document.querySelector<HTMLButtonElement>("#btn-apply")!;
const elBtnApplyMotor = document.querySelector<HTMLButtonElement>("#btn-apply-motor")!;
const elBtnRun      = document.querySelector<HTMLButtonElement>("#btn-run")!;
const elBtnStop     = document.querySelector<HTMLButtonElement>("#btn-stop")!;
const elBtnReset    = document.querySelector<HTMLButtonElement>("#btn-reset")!;
const elFreqBadge   = document.querySelector<HTMLDivElement>("#freq-badge")!;
const elBtnClear    = document.querySelector<HTMLButtonElement>("#btn-clear")!;
const elBtnPause    = document.querySelector<HTMLButtonElement>("#btn-pause")!;
const elBtnLatest   = document.querySelector<HTMLButtonElement>("#btn-latest")!;
const elBtnLive     = document.querySelector<HTMLButtonElement>("#btn-live")!;
const elPsStatus    = document.querySelector<HTMLDivElement>("#ps-status")!;
const elConnStatus  = document.querySelector<HTMLDivElement>("#conn-status")!;
const elStateBadge  = document.querySelector<HTMLDivElement>("#state-badge")!;
const elWsBadge     = document.querySelector<HTMLDivElement>("#ws-badge")!;
const elStatus      = document.querySelector<HTMLDivElement>("#status")!;
const elSampleCount = document.querySelector<HTMLSpanElement>("#sample-count")!;
const elTimelineRange = document.querySelector<HTMLSpanElement>("#timeline-range")!;
const elTimelineTrack = document.querySelector<HTMLDivElement>("#timeline-track")!;
const elTimelineWindow = document.querySelector<HTMLDivElement>("#timeline-window")!;
const elTimelineLeft = document.querySelector<HTMLDivElement>("#timeline-left")!;
const elTimelineRight = document.querySelector<HTMLDivElement>("#timeline-right")!;
const elChList      = document.querySelector<HTMLDivElement>("#ch-list")!;
const elPlotArea    = document.querySelector<HTMLElement>("#plot-area")!;

// ── Faithful viewport rendering via /api/series (min/max envelope) ──────────────
// The gateway serves a per-pixel min/max envelope over the full-rate session on
// disk, with Te/abc derived at full rate. This is the primary plot source; the
// client-side buffers remain a fallback until the endpoint returns data, and for
// the αβ display mode (the envelope is wired for the abc channel set).
const PLOT_TO_SERIES: Record<string, number> = {
  Ia: 0, Ib: 1, Ic: 2, "Φa": 3, "Φb": 4, "Φc": 5, Speed: 6, Te: 7,
};
const RPM_PER_RAD_S = 60 / (2 * Math.PI);
type RenderMode = "trend" | "raw";
let renderMode: RenderMode = "trend";
void renderMode;

// Pyramid tile state: tier layout + the most recently fetched window of tiles.
let tierMeta: TierMeta[] = [];
let bucketsPerTile = 1024;
let tilesActive = false;
let latestTiles: TileData[] = [];

async function loadTierMeta(): Promise<void> {
  try {
    const res = await fetch(gatewayURL("/api/tiers"), { cache: "no-store" });
    if (!res.ok) return;
    const meta = await res.json();
    tierMeta = meta.tiers as TierMeta[];
    bucketsPerTile = meta.bucketsPerTile ?? 1024;
  } catch { /* gateway not ready yet */ }
}

const tileCache = new TileCache(
  async (tier, index): Promise<FetchedTile> => {
    const res = await fetch(gatewayURL(`/api/tiles?tier=${tier}&index=${index}`), { cache: "default" });
    return { data: await res.arrayBuffer(), sealed: res.headers.get("Cache-Control")?.includes("immutable") ?? false };
  },
  bucketsPerTile, 200,
);

const tileViewport = new ViewportController<TileData[]>(async (from, to, width) => {
  if (tierMeta.length === 0) await loadTierMeta();
  const secPerPx = (to - from) / Math.max(1, width);
  const tIdx = selectTier(tierMeta, secPerPx);
  if (tIdx < 0) return []; // raw: render direto do tBuf
  const meta = tierMeta[tIdx];
  const indices = indicesForWindow(meta.bucketSec, bucketsPerTile, from, to);
  await tileCache.ensure(tIdx, indices);
  return tileCache.window(tIdx, indices);
}, 60);
tileViewport.onData = (tiles) => {
  latestTiles = tiles;
  tilesActive = tiles.length > 0;
  scheduleRender();
};

// Flatten loaded tiles into AlignedData: min/max vertical strokes per bucket
// (raw envelope) plus a mean centerline, in the live CHANNELS order.
function tilesToProjected(tiles: TileData[]): { xs: number[]; ys: number[][] } {
  let n = 0;
  for (const t of tiles) n += t.t.length;
  const xs: number[] = new Array(n * 2);
  const ys: number[][] = CHANNELS.map(() => new Array<number>(n * 2));
  const tl = Number(elTorque.value) || 0;
  let w = 0;
  for (const tile of tiles) {
    for (let i = 0; i < tile.t.length; i++) {
      const base = w * 2;
      xs[base] = tile.t[i];
      xs[base + 1] = tile.t[i];
      for (let k = 0; k < CHANNELS.length; k++) {
        const si = PLOT_TO_SERIES[CHANNELS[k].name];
        if (si === undefined) {
          const v = CHANNELS[k].name === "TL" ? tl : NaN;
          ys[k][base] = v; ys[k][base + 1] = v;
          continue;
        }
        let mn = tile.min[si][i], mx = tile.max[si][i];
        if (CHANNELS[k].name === "Speed") { mn *= RPM_PER_RAD_S; mx *= RPM_PER_RAD_S; }
        ys[k][base] = mn;
        ys[k][base + 1] = mx;
      }
      w++;
    }
  }
  return { xs, ys };
}

// Poll the visible window for the faithful envelope, independent of the render
// cadence (the controller debounces). viewEndSec/windowSec track the live edge
// via the existing /api/raw tail poll; only the abc channel set is wired.
setInterval(() => {
  if (plots.length === 0 || displayMode !== "abc") return;
  const hiResStart = tBuf.length > 0 ? tBuf[0] : Infinity;
  const viewEnd = viewEndSec;
  const viewStart = Math.max(0, viewEnd - windowSec);
  if (!paused || viewStart >= hiResStart) return; // dentro do tail raw: render local
  const w = elPlotArea.clientWidth || 800;
  tileViewport.request(viewStart, viewEnd, Math.max(600, w * 2));
}, 100);
const elScenarioTable    = document.querySelector<HTMLDivElement>("#scenario-table")!;
const elBtnAddScenarioEvent = document.querySelector<HTMLButtonElement>("#btn-add-scenario-event")!;
const elBtnRecipeLoad    = document.querySelector<HTMLButtonElement>("#btn-recipe-load")!;
const elBtnRecipeSave    = document.querySelector<HTMLButtonElement>("#btn-recipe-save")!;
const elBtnRecipeRun     = document.querySelector<HTMLButtonElement>("#btn-recipe-run")!;
const elScenarioName     = document.querySelector<HTMLInputElement>("#scenario-name")!;
const elScenarioProgress = document.querySelector<HTMLSpanElement>("#scenario-progress")!;
const elScenarioEndRow   = document.querySelector<HTMLDivElement>("#scenario-end-row")!;
const elScenarioRunCard  = document.querySelector<HTMLDivElement>("#scenario-run-card")!;
const elScenarioRunState = document.querySelector<HTMLSpanElement>("#scenario-run-state")!;
const elScenarioMeterFill = document.querySelector<HTMLDivElement>("#scenario-run-meter-fill")!;
const elScenarioEventCount = document.querySelector<HTMLSpanElement>("#scenario-event-count")!;
const elScenarioDuration = document.querySelector<HTMLSpanElement>("#scenario-duration")!;
const elScenarioNextEvent = document.querySelector<HTMLSpanElement>("#scenario-next-event")!;
const elBtnRecipeAddBatch = document.querySelector<HTMLButtonElement>("#btn-recipe-add-batch")!;
const elSidebar       = document.querySelector<HTMLElement>(".sidebar")!;
const elBtnSaveRun    = document.querySelector<HTMLButtonElement>("#btn-save-run")!;
const elBtnLoadRun    = document.querySelector<HTMLButtonElement>("#btn-load-run")!;
const elBtnExportCsv  = document.querySelector<HTMLButtonElement>("#btn-export-csv")!;
const elLoadFileInput = document.querySelector<HTMLInputElement>("#load-file-input")!;
const elRunMetaBadge  = document.querySelector<HTMLDivElement>("#run-meta-badge")!;
const elBatchTable      = document.querySelector<HTMLDivElement>("#batch-table")!;
const elBtnAddBatchItem = document.querySelector<HTMLButtonElement>("#btn-add-batch-item")!;
const elBtnBatchRun     = document.querySelector<HTMLButtonElement>("#btn-batch-run")!;
const elBtnBatchStop    = document.querySelector<HTMLButtonElement>("#btn-batch-stop")!;
const elBatchProgress   = document.querySelector<HTMLSpanElement>("#batch-progress")!;
const elBatchEmptyHint     = document.querySelector<HTMLDivElement>("#batch-empty-hint")!;
const elBatchCount         = document.querySelector<HTMLSpanElement>("#batch-count")!;
const elBatchMeterFill     = document.querySelector<HTMLDivElement>("#batch-meter-fill")!;
const elBtnConfigExport    = document.querySelector<HTMLButtonElement>("#btn-config-export")!;
const elBtnConfigImport    = document.querySelector<HTMLButtonElement>("#btn-config-import")!;
const elConfigImportInput  = document.querySelector<HTMLInputElement>("#config-import-input")!;
const elRunsSearch         = document.querySelector<HTMLInputElement>("#runs-search")!;
const elRunsSummary        = document.querySelector<HTMLSpanElement>("#runs-summary")!;
const elRunsList           = document.querySelector<HTMLDivElement>("#runs-list")!;
const elRunsEmpty          = document.querySelector<HTMLDivElement>("#runs-empty")!;

const savedBoardIP = localStorage.getItem(BOARD_IP_STORAGE_KEY);
if (savedBoardIP) elIp.value = savedBoardIP;

const tabButtons = Array.from(document.querySelectorAll<HTMLButtonElement>(".tab-btn"));
const tabPanes = Array.from(document.querySelectorAll<HTMLDivElement>(".tab-pane"));

function setActiveTab(tab: string) {
  tabButtons.forEach(btn => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  tabPanes.forEach(pane => {
    pane.classList.toggle("active", pane.dataset.tabPanel === tab);
  });
}

tabButtons.forEach(btn => {
  btn.setAttribute("role", "tab");
  btn.setAttribute("aria-selected", btn.classList.contains("active") ? "true" : "false");
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab || "plant";
    setActiveTab(tab);
    elSidebar.classList.toggle("sidebar-wide", tab === "scenario");
    if (tab === "scenario") refreshBatchRecipeSelects();
    if (tab === "history")  loadRunHistory();
  });
});

// ── Scenario recipe ───────────────────────────────────────────────────────────
// Param options per target keep the table self-consistent and prevent the user
// from accidentally mixing motor fault params with control targets.
const SCENARIO_PARAMS: Record<string, string[]> = {
  control: ["speed_rpm", "torque_nm", "vdc_v", "accel_time_s", "max_v_pu", "base_freq_hz"],
  motor:   ["rs", "rr", "ls", "lr", "lm", "j", "npp"],
  load:    ["torque_nm"],
};

function syncScenarioParamSelect(row: HTMLElement) {
  const tSel = row.querySelectorAll<HTMLSelectElement>("select")[0];
  const pSel = row.querySelectorAll<HTMLSelectElement>("select")[1];
  const opts = SCENARIO_PARAMS[tSel.value] ?? SCENARIO_PARAMS.control;
  const cur  = pSel.value;
  pSel.innerHTML = opts.map(o => `<option${o === cur ? " selected" : ""}>${o}</option>`).join("");
}

function bindScenarioRow(row: HTMLElement) {
  row.querySelector<HTMLButtonElement>(".scenario-remove")
    ?.addEventListener("click", () => { if (!scenarioRunning) row.remove(); });
  row.querySelectorAll<HTMLSelectElement>("select")[0]
    ?.addEventListener("change", () => syncScenarioParamSelect(row));
  syncScenarioParamSelect(row);
}

function addScenarioRow(preset?: { t: number; target: string; param: string; value: number }): HTMLElement {
  const target  = preset?.target ?? "control";
  const param   = preset?.param  ?? "speed_rpm";
  const opts    = (SCENARIO_PARAMS[target] ?? SCENARIO_PARAMS.control)
    .map(o => `<option${o === param ? " selected" : ""}>${o}</option>`).join("");
  const row = document.createElement("div");
  row.className = "scenario-row";
  row.innerHTML = `
    <input  type="number" value="${preset?.t ?? 0}"     min="0" step="0.001" class="write-input" />
    <select class="write-input">
      <option${target === "control" ? " selected" : ""}>control</option>
      <option${target === "motor"   ? " selected" : ""}>motor</option>
      <option${target === "load"    ? " selected" : ""}>load</option>
    </select>
    <select class="write-input">${opts}</select>
    <input  type="number" value="${preset?.value ?? 0}" step="0.001" class="write-input" />
    <button class="scenario-remove" type="button" title="Remove event">x</button>`;
  elScenarioTable.insertBefore(row, elScenarioEndRow);
  bindScenarioRow(row);
  return row;
}

document.querySelectorAll<HTMLElement>(".scenario-row:not(.scenario-end-row)").forEach(bindScenarioRow);
elBtnAddScenarioEvent.addEventListener("click", () => { if (!scenarioRunning) { addScenarioRow(); updateScenarioSummary(); } });
elScenarioTable.addEventListener("input", () => updateScenarioSummary());
elScenarioTable.addEventListener("change", () => updateScenarioSummary());

// ── Scenario execution state ──────────────────────────────────────────────────
let scenarioRunning = false;
let scenarioTimeouts: number[] = [];
let scenarioProgressTimer: number | null = null;
let scenarioT0 = 0;

// ── Batch runner state ────────────────────────────────────────────────────────
type BatchItem = { recipeName: string; endDelaySec: number };
type RunMeta   = { name: string; size: number; modified: string };
let batchRunning = false;
let batchIndex   = 0;
let batchTimeouts: number[] = [];
let batchSleepResolvers: Array<() => void> = [];
let batchT0 = 0;
let batchProgressTimer: number | null = null;
let batchCurrentStartedAt = 0;
let batchCurrentDuration = 0;

function getScenarioEndTime(): number {
  return Number(elScenarioEndRow.querySelector<HTMLInputElement>("input")!.value) || 0;
}

function setScenarioEndTime(t: number) {
  elScenarioEndRow.querySelector<HTMLInputElement>("input")!.value = String(t);
}

function formatScenarioSeconds(t: number): string {
  if (!Number.isFinite(t)) return "0.0 s";
  return `${t.toFixed(t < 10 ? 1 : 0)} s`;
}

function updateScenarioSummary(state: "ready" | "starting" | "running" | "done" | "error" = scenarioRunning ? "running" : "ready") {
  const events = readScenarioEvents();
  const lastT = events.length ? events[events.length - 1].t : 0;
  const endTime = Math.max(getScenarioEndTime(), lastT);
  const elapsed = scenarioRunning ? Math.max(0, (performance.now() - scenarioT0) / 1000) : 0;
  const next = events.find(ev => ev.t >= elapsed - 0.02);
  const progress = state === "done" ? 100 : endTime > 0 ? Math.min(100, Math.max(0, elapsed / endTime * 100)) : 0;

  elScenarioRunCard.dataset.state = state;
  elScenarioRunState.textContent = state === "running" ? "Running" : state === "starting" ? "Starting" : state === "done" ? "Complete" : state === "error" ? "Error" : "Ready";
  elScenarioMeterFill.style.width = `${progress}%`;
  elScenarioEventCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
  elScenarioDuration.textContent = `End ${formatScenarioSeconds(endTime)}`;
  elScenarioNextEvent.textContent = next ? `Next ${next.target}.${next.param} @ ${formatScenarioSeconds(next.t)}` : events.length ? "No pending events" : "Add events to run";
}

function readScenarioEvents() {
  return Array.from(elScenarioTable.querySelectorAll<HTMLElement>(".scenario-row:not(.scenario-end-row)"))
    .map(row => {
      const inputs  = row.querySelectorAll<HTMLInputElement>("input");
      const selects = row.querySelectorAll<HTMLSelectElement>("select");
      return {
        t:      Number(inputs[0].value)  || 0,
        target: selects[0].value,
        param:  selects[1].value,
        value:  Number(inputs[1].value)  || 0,
        row,
      };
    })
    .sort((a, b) => a.t - b.t);
}

updateScenarioSummary();

function applyScenarioValueToForm(ev: { target: string; param: string; value: number }) {
  if (ev.target === "control") {
    switch (ev.param) {
      case "speed_rpm":    elRpm.value       = String(ev.value); break;
      case "vdc_v":        elVdc.value       = String(ev.value); break;
      case "accel_time_s": elAccelTime.value = String(ev.value); break;
      case "max_v_pu":     elMaxVPu.value    = String(ev.value); break;
      case "base_freq_hz": elRatedRpm.value  = String(Math.round(ev.value * 60 / getNpp())); break;
      case "torque_nm":    elTorque.value    = String(ev.value); break;
    }
  } else if (ev.target === "load" && ev.param === "torque_nm") {
    elTorque.value = String(ev.value);
  } else if (ev.target === "motor") {
    switch (ev.param) {
      case "rs":  elMotorRs.value = String(ev.value); break;
      case "rr":  elMotorRr.value = String(ev.value); break;
      case "ls":  elMotorLs.value = String(ev.value); break;
      case "lr":  elMotorLr.value = String(ev.value); break;
      case "lm":  elMotorLm.value = String(ev.value); break;
      case "j":   elMotorJ.value  = String(ev.value); break;
      case "npp": elNpp.value     = String(ev.value); motorNpp = Math.max(1, ev.value || 2); break;
    }
    syncMotorLmLr();
  }
}

async function dispatchScenarioEvent(ev: { target: string; param: string; value: number }) {
  const ip = elIp.value.trim();
  if (!ip) return;
  try {
    applyScenarioValueToForm(ev);
    const p = readParams();
    if (ev.target === "control" || ev.target === "load") {
      // Send only the changed field — never include `enable` so the motor
      // keeps running. In gateway mode, use postJSON so only the touched field
      // is sent; in Wails mode, SetParams is the available local bridge.
      if (isWails) {
        const s = await api.SetParams(ip, p.freq, p.vdc, p.torque, p.baseFreq, p.maxVPu, p.accelTime, false, false, false);
        applyResponse(s, { hydrate: false });
        return;
      }
      const body: Record<string, unknown> = { ip };
      switch (ev.param) {
        case "speed_rpm":    body.freq_hz      = ev.value * p.npp / 60; break;
        case "torque_nm":    body.torque_nm    = ev.value;              break;
        case "vdc_v":        body.vdc_v        = ev.value;              break;
        case "accel_time_s": body.accel_time_s = ev.value;              break;
        case "max_v_pu":     body.max_v_pu     = ev.value;              break;
        case "base_freq_hz": body.base_freq_hz = ev.value;              break;
      }
      const s = await postJSON<HilStatus>("/api/set", body);
      applyResponse(s, { hydrate: false });
    } else if (ev.target === "motor") {
      const m: Record<string, number> = {
        rs: p.motorRs, rr: p.motorRr, ls: p.motorLs,
        lr: p.motorLr, lm: p.motorLm, j:  p.motorJ,  npp: p.npp,
      };
      m[ev.param] = ev.value;
      const s = await api.ProgramMotor(ip, m.rs, m.rr, m.ls, m.lr, m.lm, m.j, m.npp);
      applyResponse(s, { hydrate: false });
    }
  } catch (e) {
    setStatus(`Scenario event failed: ${String(e)}`, "error");
  }
}

function stopScenario() {
  scenarioRunning = false;
  scenarioTimeouts.forEach(clearTimeout);
  scenarioTimeouts = [];
  if (scenarioProgressTimer !== null) { clearInterval(scenarioProgressTimer); scenarioProgressTimer = null; }
  elScenarioTable.querySelectorAll(".scenario-row").forEach(r =>
    r.classList.remove("sc-active", "sc-done"));
  elScenarioProgress.textContent = "";
  updateScenarioSummary("ready");
  elBtnRecipeRun.textContent = "▶ Run";
  elBtnRecipeRun.classList.remove("btn-danger");
  elBtnRecipeLoad.disabled = false;
  elBtnRecipeSave.disabled = false;
  elBtnAddScenarioEvent.disabled = false;
  elScenarioTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
    .forEach(b => { b.disabled = false; });
}

async function prepareScenarioRun() {
  let { ip, freq, vdc, torque, baseFreq, maxVPu, accelTime } = readParams();
  if (!ip) throw new Error("missing board IP");

  // Scenario runs should be one-click: resolve a stale saved/default IP before
  // sending control commands, then keep the input and storage aligned.
  const found = await api.DiscoverBoard(ip) as DiscoveryResponse;
  ip = found.ip || ip;
  applyBoardIP(ip);
  rememberBoardIP(ip);

  captureTelemetry = false;
  capturePwm = false;
  resetPlotBuffer();
  await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, accelTime, false, false, true);
  const s = await api.Run(ip) as HilStatus;
  resetPlotBuffer();
  captureTelemetry = true;
  capturePwm = true;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Scenario running", "ok");
  applyResponse(s, { hydrate: false });
}

async function startScenario() {
  if (scenarioRunning) { stopScenario(); return; }
  const events = readScenarioEvents();
  if (events.length === 0) {
    elScenarioProgress.textContent = "Adicione eventos à receita.";
    return;
  }
  elBtnRecipeRun.disabled = true;
  elScenarioProgress.textContent = "Starting...";
  updateScenarioSummary("starting");
  try {
    await prepareScenarioRun();
  } catch (e) {
    elScenarioProgress.textContent = "Start failed";
    updateScenarioSummary("error");
    setStatus(`Scenario start failed: ${String(e)}`, "error");
    showPsStatus(String(e), false);
    elBtnRecipeRun.disabled = false;
    return;
  }

  scenarioRunning = true;
  scenarioT0 = performance.now();
  scenarioTimeouts = [];

  setActiveTab("telemetry");
  elSidebar.classList.remove("sidebar-wide");

  elBtnRecipeRun.disabled = false;
  elBtnRecipeRun.textContent = "■ Stop";
  updateScenarioSummary("running");
  elBtnRecipeRun.classList.add("btn-danger");
  elBtnRecipeLoad.disabled = true;
  elBtnRecipeSave.disabled = true;
  elBtnAddScenarioEvent.disabled = true;
  elScenarioTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
    .forEach(b => { b.disabled = true; });

  events.forEach((ev, idx) => {
    scenarioTimeouts.push(window.setTimeout(async () => {
      if (idx > 0) {
        events[idx - 1].row.classList.remove("sc-active");
        events[idx - 1].row.classList.add("sc-done");
      }
      ev.row.classList.add("sc-active");
      await dispatchScenarioEvent(ev);
    }, ev.t * 1000));
  });

  // Auto-stop at the END row time (clamped to at least 0.5s after the last event)
  const lastEventT = events.length ? events[events.length - 1].t : 0;
  const endTime    = Math.max(getScenarioEndTime(), lastEventT + 0.5);
  scenarioTimeouts.push(window.setTimeout(async () => {
    events.forEach(ev => { ev.row.classList.remove("sc-active"); ev.row.classList.add("sc-done"); });
    stopScenario();
    const ip = elIp.value.trim();
    if (ip) { try { await api.StopController(ip); } catch { /* ignore */ } }
  }, endTime * 1000));

  scenarioProgressTimer = window.setInterval(() => {
    const elapsed = (performance.now() - scenarioT0) / 1000;
    elScenarioProgress.textContent = `t = ${elapsed.toFixed(1)} s`;
    updateScenarioSummary("running");
  }, 100);
}

// ── Recipe persistence (localStorage) ────────────────────────────────────────
const RECIPE_KEY = "hil-scenario-recipes";

type RecipeEvent = { t: number; target: string; param: string; value: number };
type RecipeData  = { events: RecipeEvent[]; endTime: number } | RecipeEvent[];

function parseRecipeData(raw: RecipeData): { events: RecipeEvent[]; endTime: number } {
  if (Array.isArray(raw)) {
    const maxT = raw.length ? Math.max(...raw.map(e => e.t)) : 0;
    return { events: raw, endTime: maxT + 2 };
  }
  return { events: raw.events ?? [], endTime: raw.endTime ?? 5 };
}

function saveRecipe() {
  const name    = elScenarioName.value.trim() || "default";
  const events  = readScenarioEvents().map(({ t, target, param, value }) => ({ t, target, param, value }));
  const endTime = getScenarioEndTime();
  try {
    const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
    all[name] = { events, endTime };
    localStorage.setItem(RECIPE_KEY, JSON.stringify(all));
    refreshBatchRecipeSelects();
    const orig = elBtnRecipeSave.textContent!;
    elBtnRecipeSave.textContent = "Saved ✓";
    window.setTimeout(() => { elBtnRecipeSave.textContent = orig; }, 1500);
  } catch { /* storage not available */ }
}

function loadRecipe() {
  const name = elScenarioName.value.trim() || "default";
  try {
    const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
    const raw = all[name] as RecipeData | undefined;
    if (!raw) {
      const orig = elBtnRecipeLoad.textContent!;
      elBtnRecipeLoad.textContent = "Not found";
      window.setTimeout(() => { elBtnRecipeLoad.textContent = orig; }, 1500);
      return;
    }
    const { events, endTime } = parseRecipeData(raw);
    elScenarioTable.querySelectorAll(".scenario-row:not(.scenario-end-row)").forEach(r => r.remove());
    events.forEach(ev => addScenarioRow(ev));
    setScenarioEndTime(endTime);
    refreshBatchRecipeSelects();
    updateScenarioSummary();
  } catch { /* storage not available */ }
}

elBtnRecipeLoad.addEventListener("click", loadRecipe);
elBtnRecipeSave.addEventListener("click", saveRecipe);
elBtnRecipeRun.addEventListener("click", startScenario);

elBtnRecipeAddBatch.addEventListener("click", () => {
  saveRecipe();                                           // save (also refreshes dropdowns)
  const name = elScenarioName.value.trim() || "default";
  addBatchRow({ recipeName: name, endDelaySec: 2 });      // add to batch immediately
  const orig = elBtnRecipeAddBatch.textContent!;
  elBtnRecipeAddBatch.textContent = "Added ✓";
  window.setTimeout(() => { elBtnRecipeAddBatch.textContent = orig; }, 1500);
});

elBtnAddBatchItem.addEventListener("click", () => { if (!batchRunning) { refreshBatchRecipeSelects(); addBatchRow(); } });
elBtnBatchRun.addEventListener("click", startBatch);
elBtnBatchStop.addEventListener("click", () => {
  stopBatch();
  const ip = elIp.value.trim();
  if (ip) api.StopController(ip).catch(() => {});
});

elBtnSaveRun.addEventListener("click", () => withButton(elBtnSaveRun, async () => {
  const name = `hil_run_${new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}`;
  if (isWails) {
    await triggerSave(name);
  } else {
    await saveRunToServer(name);
    setStatus(`Saved: ${name}.hilbin`, "ok");
  }
}));

elBtnExportCsv.addEventListener("click", exportToCsv);
elBtnConfigExport.addEventListener("click", exportConfig);
elBtnConfigImport.addEventListener("click", () => elConfigImportInput.click());
elConfigImportInput.addEventListener("change", () => {
  const file = elConfigImportInput.files?.[0];
  if (file) importConfig(file);
});

elRunsSearch.addEventListener("input", applyRunFilter);
updateBatchSummary();
applyRunFilter();

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

// ── Subplot count selector ────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-n]").forEach(btn => {
  btn.addEventListener("click", () => setNSubplots(Number(btn.dataset.n)));
});

// ── αβ ↔ abc toggle ───────────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-mode]").forEach(btn => {
  btn.classList.toggle("active", btn.dataset.mode === displayMode);
  btn.addEventListener("click", () => setDisplayMode(btn.dataset.mode as "ab" | "abc"));
});

// ── Trend/raw plot rendering toggle ─────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-render]").forEach(btn => {
  btn.addEventListener("click", () => {
    renderMode = btn.dataset.render === "raw" ? "raw" : "trend";
    document.querySelectorAll<HTMLButtonElement>(".subplot-n-btn[data-render]").forEach(b => {
      b.classList.toggle("active", b === btn);
    });
    scheduleRender();
  });
});

// ── Channel list ──────────────────────────────────────────────────────────────
let valSpans: HTMLSpanElement[]     = [];
let subplotBadges: HTMLButtonElement[] = [];

// Single source of truth for channel visibility: updates the plot series and
// keeps the side-panel checkbox/row and the on-plot legend chip in sync, so a
// click in either place is reflected everywhere.
function setChannelVisible(i: number, show: boolean) {
  visible[i] = show;
  const s = chSubplot[i];
  if (s < plots.length) {
    const chIdx = getChIdx(s);
    const seriesIdx = chIdx.indexOf(i) + 1;
    if (seriesIdx > 0) plots[s].setSeries(seriesIdx, { show });
  }
  const cb = chCheckboxes[i];
  if (cb) {
    cb.checked = show;
    cb.closest(".ch-row")?.classList.toggle("ch-hidden", !show);
  }
  chLegendItems[i]?.classList.toggle("legend-off", !show);
}

function buildChannelList() {
  elChList.innerHTML = "";
  valSpans = [];
  subplotBadges = [];
  chCheckboxes = [];

  CHANNELS.forEach((ch, i) => {
    const row = document.createElement("label");
    row.className = "ch-row";

    const dot = document.createElement("span");
    dot.className = "ch-dot";
    dot.style.background = ch.color;

    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = visible[i]; cb.className = "ch-cb";
    chCheckboxes[i] = cb;

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

    row.classList.toggle("ch-hidden", !visible[i]);  // initial state class
    cb.addEventListener("change", () => setChannelVisible(i, cb.checked));

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
  return Math.max(72, Math.floor(elPlotArea.clientHeight / (nSubplots + 1)));
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
// FPGA filtering and gateway extrema reduction already prepare display data.
// Averaging the extrema envelope would cancel alternating peaks.
let smoothWin = 1;

// Binary search: first index i with buf[i] >= target.
function lowerBound(target: number, buf = tBuf): number {
  let lo = 0, hi = buf.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (buf[mid] < target) lo = mid + 1; else hi = mid;
  }
  return lo;
}

// Returns total session duration in seconds (from overview if available).
function getSessionSec(): number {
  if (ovTBuf.length > 1) return ovTBuf[ovTBuf.length - 1] - ovTBuf[0];
  if (tBuf.length  > 1) return tBuf[tBuf.length - 1]  - tBuf[0];
  return 0;
}

function latestDataSec(): number {
  const latestTelem = tBuf.length ? tBuf[tBuf.length - 1] : 0;
  const latestOverview = ovTBuf.length ? ovTBuf[ovTBuf.length - 1] : 0;
  const latestPwmOverview = pwmOverviewT.length ? pwmOverviewT[pwmOverviewT.length - 1] : 0;
  const latestPwm = pwmEvents.length ? pwmTime(pwmEvents[pwmEvents.length - 1]) : 0;
  return Math.max(latestTelem, latestOverview, latestPwmOverview, latestPwm);
}

function latestTimelineSec(): number {
  return Math.max(WINDOW_MIN_SEC, latestDataSec());
}

function clampViewEndToTimeZero(endSec = viewEndSec): number {
  const total = latestTimelineSec();
  const minEnd = Math.min(windowSec, total);
  return clamp(endSec, minEnd, total);
}

function formatTimelineSec(t: number): string {
  if (t < 1) return `${(t * 1000).toFixed(0)} ms`;
  if (t < 10) return `${t.toFixed(3)} s`;
  if (t < 60) return `${t.toFixed(2)} s`;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

function updateTimelineBar() {
  const total = latestTimelineSec();
  const start = Math.max(0, viewEndSec - windowSec);
  const end = Math.min(total, viewEndSec);
  const leftPct = clamp(start / total * 100, 0, 100);
  const rightPct = clamp(end / total * 100, leftPct, 100);
  elTimelineWindow.style.left = `${leftPct}%`;
  elTimelineWindow.style.width = `${Math.max(0.5, rightPct - leftPct)}%`;
  elTimelineRange.textContent = `${formatTimelineSec(start)} - ${formatTimelineSec(end)}`;
}

function timelineTimeAtClientX(clientX: number): number {
  const rect = elTimelineTrack.getBoundingClientRect();
  const ratio = clamp((clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  return ratio * latestTimelineSec();
}

function freezeTimelineView() {
  if (paused) return;
  paused = true;
  viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
}

function applyTimelineWindow(start: number, end: number) {
  const total = latestTimelineSec();
  const maxSec = Math.max(WINDOW_MAX_SEC, getSessionSec() + 10);
  const clampedEnd = clamp(end, WINDOW_MIN_SEC, total);
  const clampedStart = clamp(start, 0, clampedEnd - WINDOW_MIN_SEC);
  windowSec = clamp(clampedEnd - clampedStart, WINDOW_MIN_SEC, maxSec);
  viewEndSec = clampViewEndToTimeZero(clampedEnd);
  updateWindowButtons();
  scheduleRender();
}

function attachTimelineNavigation() {
  type DragMode = "window" | "left" | "right";
  let dragMode: DragMode | null = null;
  let dragStartX = 0;
  let dragStartEnd = 0;

  const beginDrag = (mode: DragMode, e: PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    freezeTimelineView();
    dragMode = mode;
    dragStartX = e.clientX;
    dragStartEnd = viewEndSec;
    elTimelineTrack.setPointerCapture(e.pointerId);
  };

  elTimelineLeft.addEventListener("pointerdown", e => beginDrag("left", e));
  elTimelineRight.addEventListener("pointerdown", e => beginDrag("right", e));
  elTimelineWindow.addEventListener("pointerdown", e => beginDrag("window", e));

  elTimelineTrack.addEventListener("pointerdown", e => {
    if (e.target !== elTimelineTrack) return;
    freezeTimelineView();
    const center = timelineTimeAtClientX(e.clientX);
    viewEndSec = clampViewEndToTimeZero(center + windowSec / 2);
    updateWindowButtons();
    scheduleRender();
  });

  elTimelineTrack.addEventListener("pointermove", e => {
    if (!dragMode) return;
    if (dragMode === "window") {
      const rect = elTimelineTrack.getBoundingClientRect();
      const total = latestTimelineSec();
      const delta = (e.clientX - dragStartX) / Math.max(1, rect.width) * total;
      viewEndSec = clampViewEndToTimeZero(dragStartEnd + delta);
      scheduleRender();
      return;
    }

    const t = timelineTimeAtClientX(e.clientX);
    const start = Math.max(0, viewEndSec - windowSec);
    const end = viewEndSec;
    if (dragMode === "left") {
      applyTimelineWindow(Math.min(t, end - WINDOW_MIN_SEC), end);
    } else {
      applyTimelineWindow(start, Math.max(t, start + WINDOW_MIN_SEC));
    }
  });

  const endDrag = (e: PointerEvent) => {
    if (!dragMode) return;
    dragMode = null;
    try { elTimelineTrack.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  };
  elTimelineTrack.addEventListener("pointerup", endDrag);
  elTimelineTrack.addEventListener("pointercancel", endDrag);
}

// Decimate an arbitrary time/sample buffer pair to ~maxPts points in [xMin, xMax].
// xMin/xMax === null means "use the entire buffer".
// Decimation works on the VISIBLE slice so zooming in always gives full resolution.
function decimateFrom(
  tbuf: number[], sbuf: Sample[],
  maxPts: number, xMin: number | null, xMax: number | null,
  smoothingWindow = smoothWin,
): { xs: number[]; ys: number[][] } {
  const total = tbuf.length;
  if (total === 0) return { xs: [], ys: Array.from({ length: N_CH }, () => []) };

  const iStart = xMin == null ? 0     : lowerBound(xMin, tbuf);
  const iEnd   = xMax == null ? total : lowerBound(xMax, tbuf);
  const n = Math.max(0, iEnd - iStart);
  if (n === 0) return { xs: [], ys: Array.from({ length: N_CH }, () => []) };

  const smoothed = smoothingWindow <= 1
    ? (c: number, i: number) => CHANNELS[c].read(sbuf[i])
    : (c: number, i: number) => {
        const half = Math.floor(smoothingWindow / 2);
        const lo = Math.max(0, i - half);
        const hi = Math.min(total - 1, i + half);
        let sum = 0;
        for (let k = lo; k <= hi; k++) sum += CHANNELS[c].read(sbuf[k]);
        return sum / (hi - lo + 1);
      };

  if (n <= maxPts) {
    const xs = tbuf.slice(iStart, iEnd);
    const ys = Array.from({ length: N_CH }, (_, c) => {
      const arr = new Array<number>(n);
      for (let k = 0; k < n; k++) arr[k] = smoothed(c, iStart + k);
      return arr;
    });
    return { xs, ys };
  }

  const extremaPerBucket = Math.max(2, 2 * N_CH);
  const buckets = Math.max(1, Math.floor(maxPts / extremaPerBucket));
  const bucketSize = n / buckets;
  const xs: number[] = [];
  const ys: number[][] = Array.from({ length: N_CH }, () => []);

  for (let b = 0; b < buckets; b++) {
    const i0 = iStart + Math.floor(b * bucketSize);
    const i1 = Math.min(iStart + Math.floor((b + 1) * bucketSize), iEnd) - 1;
    if (i0 > i1) continue;

    const extrema = new Set<number>();
    for (let c = 0; c < N_CH; c++) {
      let minIdx = i0, maxIdx = i0;
      let minV = smoothed(c, i0), maxV = minV;
      for (let i = i0 + 1; i <= i1; i++) {
        const value = smoothed(c, i);
        if (value < minV) { minV = value; minIdx = i; }
        if (value > maxV) { maxV = value; maxIdx = i; }
      }
      extrema.add(minIdx); extrema.add(maxIdx);
    }

    const ordered = [...extrema].sort((a, b) => a - b);
    for (const idx of ordered) {
      xs.push(tbuf[idx]);
      for (let c = 0; c < N_CH; c++) ys[c].push(smoothed(c, idx));
    }
  }

  return { xs, ys };
}

// Route to the overview (downsampled) buffer only when the high-res buffer has
// actually rolled (tBuf filled to capacity and started dropping old samples) AND
// the view extends before the surviving high-res window. While the session is
// younger than MAX_SAMPLES/fs (~6 s), tBuf still holds every sample since t=0
// and the overview is never needed — bypassing this avoids the zigzag artifact
// that appears when viewStart goes slightly negative on a fresh session.
function decimateAndProject(
  maxPts: number,
  xMin: number | null = null,
  xMax: number | null = null,
): { xs: number[]; ys: number[][] } {
  const hiResRolled = tBuf.length >= MAX_SAMPLES;
  const hiResStart  = tBuf.length > 0 ? tBuf[0] : null;
  const useOverview = hiResRolled
    && ovTBuf.length > 1
    && hiResStart != null
    && xMin != null
    && xMin < hiResStart - 1.0;
  return decimateFrom(
    useOverview ? ovTBuf : tBuf,
    useOverview ? ovSBuf : samplesBuf,
    maxPts, xMin, xMax,
    useOverview ? 1 : smoothWin,
  );
}

// Shared cursor sync key — all subplots show the cursor at the same x position.
const cursorSync = (uPlot as any).sync("hil");

// ── Tooltip ───────────────────────────────────────────────────────────────────
const elTooltip = document.createElement("div");
elTooltip.className = "plot-tooltip";
elTooltip.style.display = "none";
document.body.appendChild(elTooltip);

function showTooltip(u: uPlot) {
  const idx = u.cursor.idx;
  if (idx == null || idx < 0 || (u.data[0] as number[]).length === 0) {
    elTooltip.style.display = "none";
    return;
  }
  const t = (u.data[0] as number[])[idx];
  if (t == null) { elTooltip.style.display = "none"; return; }

  let html = `<div class="tt-time">t = ${t.toFixed(5)} s</div>`;

  // Collect values from all subplots at this cursor index (all share same xs).
  plots.forEach((p, s) => {
    const chIdx = getChIdx(s);
    chIdx.forEach((ci, si) => {
      if (!visible[ci]) return;
      const val = (p.data[si + 1] as number[])?.[idx];
      if (val == null || !isFinite(val)) return;
      html += `<div class="tt-row">
        <span class="tt-dot" style="background:${CHANNELS[ci].color}"></span>
        <span class="tt-name">${CHANNELS[ci].name}</span>
        <span class="tt-val">${val.toFixed(4)}</span>
        <span class="tt-unit">${CHANNELS[ci].unit}</span>
      </div>`;
    });
  });

  elTooltip.innerHTML = html;
  elTooltip.style.display = "block";

  // Position near cursor, avoiding screen edges.
  const rect = u.root.getBoundingClientRect();
  const cx = rect.left + (u.cursor.left ?? 0);
  const cy = rect.top  + (u.cursor.top  ?? 0);
  const margin = 14;
  const tw = elTooltip.offsetWidth;
  const th = elTooltip.offsetHeight;
  const tx = (cx + margin + tw > window.innerWidth  - 8) ? cx - tw - margin : cx + margin;
  const ty = (cy + margin + th > window.innerHeight - 8) ? cy - th - margin : cy + margin;
  elTooltip.style.left = `${tx}px`;
  elTooltip.style.top  = `${ty}px`;
}

// X-axis sync guard — prevents recursive setScale loops when propagating.
let scaleSyncing = false;

// All x-scale work is done explicitly in scheduleRender(); we keep the guard
// flag because cursor.sync still needs to call setScale internally.

function attachPlotNavigation(wrap: HTMLElement) {
  // Wheel: zoom the time window around the cursor and freeze live-follow while
  // inspecting history. This handler is shared by telemetry and PWM plots.
  wrap.addEventListener("wheel", (e: WheelEvent) => {
    freezeTimelineView();
    e.preventDefault();
    const notches = Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY) / 100, 3);
    const factor = Math.pow(1.10, notches);
    const maxSec = Math.max(WINDOW_MAX_SEC, getSessionSec() + 10);
    const next = clamp(windowSec * factor, WINDOW_MIN_SEC, maxSec);
    if (next === windowSec) return;

    const plotRect = (wrap.querySelector(".u-over") as HTMLElement | null)?.getBoundingClientRect() ?? wrap.getBoundingClientRect();
    const mouseRatio = clamp((e.clientX - plotRect.left) / Math.max(1, plotRect.width), 0, 1);
    const timeCursor = Math.max(0, viewEndSec - windowSec) + mouseRatio * Math.min(windowSec, Math.max(WINDOW_MIN_SEC, viewEndSec));
    windowSec = next;
    viewEndSec = clampViewEndToTimeZero(timeCursor + (1 - mouseRatio) * next);
    updateWindowButtons();
    scheduleRender();
  }, { passive: false });

  // Drag horizontal: pan in time. If live, first freeze at the latest sample.
  let dragStartX: number | null = null;
  let dragStartViewEnd = 0;
  wrap.addEventListener("mousedown", (e: MouseEvent) => {
    if (e.button !== 0) return;
    if (!paused) {
      paused = true;
      viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
      scheduleRender();
    }
    dragStartX = e.clientX;
    dragStartViewEnd = viewEndSec;
    wrap.style.cursor = "grabbing";
  });
  const onMove = (e: MouseEvent) => {
    if (dragStartX == null) return;
    const dx = e.clientX - dragStartX;
    const plotRect = (wrap.querySelector(".u-over") as HTMLElement | null)?.getBoundingClientRect() ?? wrap.getBoundingClientRect();
    const pxPerSec = plotRect.width / Math.max(WINDOW_MIN_SEC, Math.min(windowSec, Math.max(WINDOW_MIN_SEC, viewEndSec)));
    viewEndSec = clampViewEndToTimeZero(dragStartViewEnd - dx / pxPerSec);
    scheduleRender();
  };
  const onUp = () => {
    if (dragStartX == null) return;
    dragStartX = null;
    wrap.style.cursor = "";
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

// ── Build / rebuild all uPlot instances ───────────────────────────────────────
function buildPlots() {
  if (isBuilding) return;
  isBuilding = true;

  plots.forEach(p => p.destroy());
  pwmPlot?.destroy();
  plots = [];
  pwmPlot = null;
  chLegendItems = [];
  elPlotArea.innerHTML = "";

  const w = Math.max(400, elPlotArea.clientWidth);
  const h = plotHeight();

  const maxPts = Math.max(600, w * 2);
  const xScale = plots[0]?.scales?.x;
  const xMin = xScale?.min ?? null;
  const xMax = xScale?.max ?? null;
  const { xs, ys } = decimateAndProject(maxPts, xMin, xMax);

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
      dash: CHANNELS[ci].dash,
      show: visible[ci],
      value: (_u: uPlot) => CHANNELS[ci].unit,
    }));

    const yLabel = chIdx.map(ci => CHANNELS[ci].unit).find(Boolean) ?? "Y";

    attachPlotNavigation(wrap);
    wrap.addEventListener("mouseleave", () => { elTooltip.style.display = "none"; });

    const p = new uPlot(
      {
        width: w,
        height: h,
        pxAlign: 0,
        cursor: {
          show: true,
          drag: { x: false, y: false, setScale: false },
          sync: { key: cursorSync.key },
        },
        hooks: {
          setCursor: [showTooltip],
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
        // Internal legend is disabled — the side "PLOTS" panel already lists
        // every channel with its live numeric value and color dot. Keeping
        // the per-subplot legend stole height from the canvas (legend lives
        // BELOW the plot inside the wrap, not accounted for by plotHeight()),
        // which clipped the last subplot's x-axis when nSubplots=3+.
        legend: { show: false },
      },
      [xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData,
      wrap,
    );

    plots.push(p);

    // Clickable legend overlay (absolute, top-left over the canvas) — click a
    // chip to hide/show that wave. Stays in sync with the side-panel checkbox
    // via setChannelVisible. mousedown is swallowed so a chip click never
    // starts a pan-drag on the wrap.
    const legend = document.createElement("div");
    legend.className = "subplot-legend";
    legend.addEventListener("mousedown", e => e.stopPropagation());
    chIdx.forEach(ci => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "subplot-legend-item" + (visible[ci] ? "" : " legend-off");
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = CHANNELS[ci].color;
      const lbl = document.createElement("span");
      lbl.textContent = CHANNELS[ci].name;
      item.append(dot, lbl);
      item.addEventListener("click", e => {
        e.preventDefault();
        e.stopPropagation();
        setChannelVisible(ci, !visible[ci]);
      });
      chLegendItems[ci] = item;
      legend.appendChild(item);
    });
    wrap.appendChild(legend);
  }


  const pwmWrap = document.createElement("div");
  pwmWrap.className = "subplot-wrap pwm-subplot-wrap";
  attachPlotNavigation(pwmWrap);
  pwmWrap.addEventListener("mouseleave", () => { elTooltip.style.display = "none"; });
  // PWM is the first subplot: insert at the top of the plot area regardless of
  // creation order (DOM position, not uPlot instantiation order, drives layout).
  elPlotArea.prepend(pwmWrap);
  pwmPlot = new uPlot(
    {
      width: w,
      height: h,
      pxAlign: 0,
      cursor: { show: true, drag: { x: false, y: false, setScale: false }, sync: { key: cursorSync.key } },
      scales: { x: { time: false } },
      axes: [
        { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" } },
        { stroke: "#3a5575", grid: { stroke: "#0e1d30", width: 1 }, ticks: { stroke: "#0e1d30" }, label: "PWM state" },
      ],
      series: [
        { label: "t [s]" },
        { label: "PWM A", stroke: "#ffd54f", width: 1.5, points: { show: false }, show: pwmVisible[0] },
        { label: "PWM B", stroke: "#4fc3f7", width: 1.5, points: { show: false }, show: pwmVisible[1] },
        { label: "PWM C", stroke: "#ef9a9a", width: 1.5, points: { show: false }, show: pwmVisible[2] },
      ],
      legend: { show: false },
    },
    [[], [], [], []] as uPlot.AlignedData,
    pwmWrap,
  );

  // Clickable legend for the PWM phases — same UX as the telemetry subplots.
  const pwmMeta = [
    { name: "PWM A", color: "#ffd54f" },
    { name: "PWM B", color: "#4fc3f7" },
    { name: "PWM C", color: "#ef9a9a" },
  ];
  const pwmLegend = document.createElement("div");
  pwmLegend.className = "subplot-legend";
  pwmLegend.addEventListener("mousedown", e => e.stopPropagation());
  pwmMeta.forEach((m, k) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "subplot-legend-item" + (pwmVisible[k] ? "" : " legend-off");
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = m.color;
    const lbl = document.createElement("span");
    lbl.textContent = m.name;
    item.append(dot, lbl);
    item.addEventListener("click", e => {
      e.preventDefault();
      e.stopPropagation();
      pwmVisible[k] = !pwmVisible[k];
      item.classList.toggle("legend-off", !pwmVisible[k]);
      pwmPlot?.setSeries(k + 1, { show: pwmVisible[k] });
    });
    pwmLegend.appendChild(item);
  });
  pwmWrap.appendChild(pwmLegend);

  isBuilding = false;
}

// ── Resize observer ───────────────────────────────────────────────────────────
new ResizeObserver(() => {
  if (isBuilding || plots.length === 0) return;
  const w = Math.max(400, elPlotArea.clientWidth);
  const h = plotHeight();
  plots.forEach(p => p.setSize({ width: w, height: h }));
  pwmPlot?.setSize({ width: w, height: h });
}).observe(elPlotArea);

requestAnimationFrame(() => buildPlots());

function npcLevel(state: number): number | null {
  // NPC gate-state encoding from RTL. Dead-time states are plotted as half
  // levels, matching the solver-side gate-to-voltage approximation.
  if (state === 0b0011) return 1;
  if (state === 0b0010) return 0.5;
  if (state === 0b0110) return 0;
  if (state === 0b0100) return -0.5;
  if (state === 0b1100) return -1;
  return null;
}

function applyNpcLevel(state: number, prev: number): number {
  const decoded = npcLevel(state);
  return decoded == null ? prev : decoded;
}

function appendPwmOverviewUntil(t: number) {
  if (pwmOverviewNextT === null) pwmOverviewNextT = Math.floor(t / PWM_OVERVIEW_DT_SEC) * PWM_OVERVIEW_DT_SEC;
  while (pwmOverviewNextT <= t) {
    pwmOverviewT.push(pwmOverviewNextT);
    pwmOverviewA.push(pwmOverviewAState);
    pwmOverviewB.push(pwmOverviewBState);
    pwmOverviewC.push(pwmOverviewCState);
    pwmOverviewNextT += PWM_OVERVIEW_DT_SEC;
  }
  if (pwmOverviewT.length > MAX_PWM_OVERVIEW_SAMPLES) {
    const drop = pwmOverviewT.length - MAX_PWM_OVERVIEW_SAMPLES;
    pwmOverviewT.splice(0, drop);
    pwmOverviewA.splice(0, drop);
    pwmOverviewB.splice(0, drop);
    pwmOverviewC.splice(0, drop);
  }
}

function pwmOverviewData(viewStart: number, viewEnd: number, maxPts: number): [number[], number[], number[], number[]] {
  if (pwmOverviewT.length === 0) return [[], [], [], []];
  const start = Math.max(viewStart, pwmOverviewT[0]);
  const end = Math.min(viewEnd, pwmOverviewT[pwmOverviewT.length - 1]);
  if (end < start) return [[], [], [], []];
  const iStart = lowerBound(start, pwmOverviewT);
  const iEnd = lowerBound(end, pwmOverviewT);
  const n = Math.max(0, iEnd - iStart);
  if (n === 0) return [[], [], [], []];
  if (n <= maxPts) {
    return [
      pwmOverviewT.slice(iStart, iEnd),
      pwmOverviewA.slice(iStart, iEnd),
      pwmOverviewB.slice(iStart, iEnd),
      pwmOverviewC.slice(iStart, iEnd),
    ];
  }
  const xs: number[] = [];
  const ya: number[] = [];
  const yb: number[] = [];
  const yc: number[] = [];
  const buckets = Math.max(1, Math.floor(maxPts / 2));
  const bucketSize = n / buckets;
  for (let j = 0; j < buckets; j++) {
    const i0 = iStart + Math.floor(j * bucketSize);
    const i1 = Math.min(iStart + Math.floor((j + 1) * bucketSize), iEnd) - 1;
    if (i0 > i1) continue;
    let minA = pwmOverviewA[i0], maxA = pwmOverviewA[i0];
    let minB = pwmOverviewB[i0], maxB = pwmOverviewB[i0];
    let minC = pwmOverviewC[i0], maxC = pwmOverviewC[i0];
    for (let i = i0 + 1; i <= i1; i++) {
      const a = pwmOverviewA[i], b = pwmOverviewB[i], c = pwmOverviewC[i];
      if (a < minA) minA = a; if (a > maxA) maxA = a;
      if (b < minB) minB = b; if (b > maxB) maxB = b;
      if (c < minC) minC = c; if (c > maxC) maxC = c;
    }
    const t = (pwmOverviewT[i0] + pwmOverviewT[i1]) * 0.5;
    xs.push(t, t);
    ya.push(minA, maxA);
    yb.push(minB, maxB);
    yc.push(minC, maxC);
  }
  return [xs, ya, yb, yc];
}

function pwmTime(ev: PwmPlotEvent): number {
  return ev.t_sec;
}

function lowerBoundPwmTime(target: number): number {
  let lo = 0, hi = pwmEvents.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (pwmEvents[mid].t_sec < target) lo = mid + 1; else hi = mid;
  }
  return lo;
}

function upperBoundPwmTime(target: number): number {
  let lo = 0, hi = pwmEvents.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (pwmEvents[mid].t_sec <= target) lo = mid + 1; else hi = mid;
  }
  return lo;
}

function pwmStepData(viewStart: number, viewEnd: number): [number[], number[], number[], number[]] {
  // Draw real PWM edges while the window is reasonably sparse. If it is too
  // dense, fall back to a min/max envelope so we keep the -1/0/1 states without
  // inventing averaged duty-equivalent values.
  const maxTransitions = Math.max(2000, (elPlotArea.clientWidth || 800) * 4);
  if (pwmEvents.length === 0) return pwmOverviewData(viewStart, viewEnd, maxTransitions);

  const firstTime = pwmTime(pwmEvents[0]);
  const lastTime = pwmTime(pwmEvents[pwmEvents.length - 1]);
  if (viewEnd < firstTime) {
    const overview = pwmOverviewData(viewStart, viewEnd, maxTransitions);
    if (overview[0].length > 0) return overview;
  }
  const plotStart = Math.max(viewStart, firstTime);
  const plotEnd = pwmActive ? viewEnd : Math.min(viewEnd, lastTime);
  if (plotEnd < plotStart || viewEnd < firstTime || viewStart > lastTime) return [[], [], [], []];

  const xs: number[] = [];
  const ya: number[] = [];
  const yb: number[] = [];
  const yc: number[] = [];
  const firstIdx = lowerBoundPwmTime(plotStart);
  const prevIdx = Math.max(0, firstIdx - 1);
  const lastIdx = upperBoundPwmTime(plotEnd);
  const transitionCount = Math.max(0, lastIdx - firstIdx);
  if (transitionCount > maxTransitions) {
    let idx = prevIdx;
    let a = applyNpcLevel(pwmEvents[prevIdx].a, 0);
    let b = applyNpcLevel(pwmEvents[prevIdx].b, 0);
    let c = applyNpcLevel(pwmEvents[prevIdx].c, 0);
    const buckets = Math.max(1, Math.floor(maxTransitions / 2));
    for (let j = 0; j < buckets; j++) {
      const t0 = plotStart + (plotEnd - plotStart) * j / buckets;
      const t1 = plotStart + (plotEnd - plotStart) * (j + 1) / buckets;
      while (idx + 1 < pwmEvents.length && pwmTime(pwmEvents[idx + 1]) < t0) {
        idx++;
        const ev = pwmEvents[idx];
        a = applyNpcLevel(ev.a, a);
        b = applyNpcLevel(ev.b, b);
        c = applyNpcLevel(ev.c, c);
      }
      let minA = a, maxA = a, minB = b, maxB = b, minC = c, maxC = c;
      while (idx + 1 < pwmEvents.length && pwmTime(pwmEvents[idx + 1]) <= t1) {
        idx++;
        const ev = pwmEvents[idx];
        a = applyNpcLevel(ev.a, a);
        b = applyNpcLevel(ev.b, b);
        c = applyNpcLevel(ev.c, c);
        if (a < minA) minA = a; if (a > maxA) maxA = a;
        if (b < minB) minB = b; if (b > maxB) maxB = b;
        if (c < minC) minC = c; if (c > maxC) maxC = c;
      }
      const t = (t0 + t1) * 0.5;
      xs.push(t, t);
      ya.push(minA, maxA);
      yb.push(minB, maxB);
      yc.push(minC, maxC);
    }
    return [xs, ya, yb, yc];
  }
  let lastT = plotStart;
  let a = applyNpcLevel(pwmEvents[prevIdx].a, 0);
  let b = applyNpcLevel(pwmEvents[prevIdx].b, 0);
  let c = applyNpcLevel(pwmEvents[prevIdx].c, 0);
  xs.push(plotStart); ya.push(a); yb.push(b); yc.push(c);
  for (let i = firstIdx; i < lastIdx; i++) {
    const ev = pwmEvents[i];
    const t = pwmTime(ev);
    xs.push(t); ya.push(a); yb.push(b); yc.push(c);
    a = applyNpcLevel(ev.a, a); b = applyNpcLevel(ev.b, b); c = applyNpcLevel(ev.c, c);
    xs.push(t); ya.push(a); yb.push(b); yc.push(c);
    lastT = t;
  }
  if (lastT < plotEnd) {
    xs.push(plotEnd); ya.push(a); yb.push(b); yc.push(c);
  }
  return [xs, ya, yb, yc];
}

// ── Render ────────────────────────────────────────────────────────────────────
let renderPending = false;
let lastRenderAt = 0;
const RENDER_INTERVAL_MS = 50;

function resetOverviewBucket() {
  ovBucketMinV.fill(Infinity); ovBucketMaxV.fill(-Infinity);
  ovBucketMinT.fill(0); ovBucketMaxT.fill(0);
  ovBucketMinS.fill(null); ovBucketMaxS.fill(null);
}

function flushOverviewBucket() {
  const points: { t: number; s: Sample }[] = [];
  for (let i = 0; i < OVERVIEW_READERS.length; i++) {
    if (ovBucketMinS[i] !== null) points.push({ t: ovBucketMinT[i], s: ovBucketMinS[i]! });
    if (ovBucketMaxS[i] !== null) points.push({ t: ovBucketMaxT[i], s: ovBucketMaxS[i]! });
  }
  points.sort((a, b) => a.t - b.t);
  let lastT = -Infinity;
  for (const point of points) {
    if (point.t === lastT) continue;
    ovTBuf.push(point.t); ovSBuf.push(point.s);
    lastT = point.t;
  }
  if (ovTBuf.length > MAX_OVERVIEW_SAMPLES) {
    const trim = ovTBuf.length - MAX_OVERVIEW_SAMPLES;
    ovTBuf.splice(0, trim); ovSBuf.splice(0, trim);
  }
  resetOverviewBucket();
}

// Wipes only the telemetry data buffers — called when the FPGA epoch changes
// (new Run) so stale pre-run samples at the frozen counter value are removed
// before the fresh run's samples arrive at t≈0.
function clearTelemBuffers() {
  tBuf.length = 0;
  samplesBuf.length = 0;
  ovTBuf.length = 0;
  ovSBuf.length = 0;
  ovCounter = 0;
  resetOverviewBucket();
  lastTelemPlotTime = -Infinity;
  sampleCount = 0;
}

function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  const delay = Math.max(0, RENDER_INTERVAL_MS - (performance.now() - lastRenderAt));
  window.setTimeout(() => requestAnimationFrame(() => {
    renderPending = false;
    lastRenderAt = performance.now();

    // Resolve the visible window. While running live we keep the right edge
    // glued to the most recent sample; while paused viewEndSec is whatever
    // the pause/pan left behind.
    if (!paused && tBuf.length > 0) {
      viewEndSec = tBuf[tBuf.length - 1];
    }
    viewEndSec = clampViewEndToTimeZero();
    const viewEnd   = viewEndSec;
    const viewStart = Math.max(0, viewEnd - windowSec);

    const w = elPlotArea.clientWidth || 800;
    const maxPts = Math.max(600, w * 2);
    const hiResStart = tBuf.length > 0 ? tBuf[0] : Infinity;
    const needHistorical = paused && viewStart < hiResStart;
    const useTiles = needHistorical && tilesActive && displayMode === "abc" && latestTiles.length > 0;
    const { xs, ys } = useTiles
      ? tilesToProjected(latestTiles)
      : decimateAndProject(maxPts, viewStart, viewEnd);

    scaleSyncing = true;
    plots.forEach((p, s) => {
      const chIdx = getChIdx(s);
      p.setData([xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData);
      // Explicit, identical X scale on every plot — no auto-fit, no surprise
      // range shifts. uPlot's cursor.sync still keeps the crosshair aligned.
      p.setScale("x", { min: viewStart, max: viewEnd });
    });
    if (pwmPlot) {
      // Both telemetry and PWM events use the same FPGA run-local counter, so
      // the shared [viewStart, viewEnd] window applies to both without offset.
      const [px, pa, pb, pc] = pwmStepData(viewStart, viewEnd);
      pwmPlot.setData([px, pa, pb, pc] as uPlot.AlignedData);
      pwmPlot.setScale("x", { min: viewStart, max: viewEnd });
      pwmPlot.setScale("y", { min: -1.25, max: 1.25 });
    }
    scaleSyncing = false;

    updateTimelineBar();
    elSampleCount.textContent = `${sampleCount.toLocaleString()} samples`;
    elBtnPause.textContent = paused ? "▶ Resume" : "⏸ Pause";
    elBtnPause.classList.toggle("active", paused);
    elBtnLatest.disabled = !paused;
  }), delay);
}

// ── Telemetry events ──────────────────────────────────────────────────────────
function ingestTelemetry(samples: Sample[]) {
  if (!captureTelemetry || !Array.isArray(samples) || samples.length === 0) return;
  lastSampleAt = performance.now();

  // Sample-and-hold the commanded load so the TL trace shows the step history.
  const tlNow = Number(elTorque.value) || 0;

  for (const s of samples) {
    s.TL = tlNow;

    // ── Hardware-time alignment ──────────────────────────────────────────────
    // t_cycles comes from the same FPGA run-local counter as PWM events, so
    // telemetry and PWM share one timeline with no host-clock drift.
    const raw   = (s.t_cycles ?? 0) >>> 0;
    const epoch = s.epoch ?? 0;

    if (telemEpoch !== null && epoch !== telemEpoch) {
      // Epoch incremented → new run started. Clear stale samples so the
      // old frozen-counter data at end-of-previous-run doesn't linger.
      clearTelemBuffers();
      telemWrapOffsetCycles = 0;
      telemBaseAbsCycles = null;
      telemLastRawCycles = null;
    } else if (telemLastRawCycles !== null && raw < telemLastRawCycles
               && telemLastRawCycles - raw > 0x80000000) {
      telemWrapOffsetCycles += PWM_COUNTER_MOD;  // 32-bit wrap
    } else if (telemLastRawCycles !== null && raw <= telemLastRawCycles) {
      continue;
    }
    const absCycles = telemWrapOffsetCycles + raw;
    if (telemBaseAbsCycles === null) telemBaseAbsCycles = absCycles;
    telemEpoch          = epoch;
    telemLastRawCycles  = raw;

    let hwSec = (absCycles - telemBaseAbsCycles) / HW_CLOCK_HZ;

    if (hwSec < 0 || hwSec <= lastTelemPlotTime) continue;
    lastTelemPlotTime = hwSec;

    const sampleTime = hwSec;
    tBuf.push(sampleTime);
    samplesBuf.push(s);

    for (let i = 0; i < OVERVIEW_READERS.length; i++) {
      const value = OVERVIEW_READERS[i](s);
      if (value < ovBucketMinV[i]) {
        ovBucketMinV[i] = value; ovBucketMinT[i] = sampleTime; ovBucketMinS[i] = s;
      }
      if (value > ovBucketMaxV[i]) {
        ovBucketMaxV[i] = value; ovBucketMaxT[i] = sampleTime; ovBucketMaxS[i] = s;
      }
    }
    if (++ovCounter >= OVERVIEW_EVERY) {
      ovCounter = 0;
      flushOverviewBucket();
    }
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
}

let rawCursor = 0;
let rawTransportHealthy = true;
let rawEverWorked = false;
let reducedFallbackUsed = false;
let streamGeneration = 0;

api.onTelemetry((samples: Sample[]) => {
  if (!rawTransportHealthy && !rawEverWorked) {
    reducedFallbackUsed = true;
    ingestTelemetry(samples);
  }
});

async function pollRawTelemetry() {
  const generation = streamGeneration;
  try {
    const requestedCursor = rawCursor;
    let data: ArrayBuffer;
    if (isWails) {
      const encoded = await (window as any).go.main.App.GetRawTelemetry(rawCursor, 20_000) as string;
      const binary = atob(encoded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      data = bytes.buffer;
    } else {
      const response = await fetch(gatewayURL(`/api/raw?cursor=${rawCursor}&limit=20000`), { cache: "no-store" });
      if (!response.ok) throw new Error(`raw telemetry HTTP ${response.status}`);
      data = await response.arrayBuffer();
    }
    if (generation !== streamGeneration) return;
    const view = new DataView(data);
    if (data.byteLength < 12) throw new Error("truncated raw telemetry batch");
    if (generation !== streamGeneration) return;
    rawCursor = Number(view.getBigUint64(0, true));
    const count = view.getUint32(8, true);
    if (data.byteLength !== 12 + count * 26) throw new Error("invalid raw telemetry batch");
    const samples = new Array<Sample>(count);
    let off = 12;
    for (let i = 0; i < count; i++, off += 26) {
      samples[i] = {
        t_cycles: view.getUint32(off, true),
        epoch: view.getUint16(off + 4, true),
        Ia: view.getFloat32(off + 6, true),
        Ib: view.getFloat32(off + 10, true),
        FluxA: view.getFloat32(off + 14, true),
        FluxB: view.getFloat32(off + 18, true),
        Speed: view.getFloat32(off + 22, true),
      };
    }
    const batchStartCursor = rawCursor - samples.length;
    if (rawEverWorked && batchStartCursor !== requestedCursor) {
      clearTelemBuffers();
    }
    if (!rawEverWorked && reducedFallbackUsed) {
      clearTelemBuffers();
      reducedFallbackUsed = false;
    }
    rawEverWorked = true;
    rawTransportHealthy = true;
    if (samples.length > 0) ingestTelemetry(samples);
  } catch {
    rawTransportHealthy = rawEverWorked;
  } finally {
    window.setTimeout(pollRawTelemetry, rawTransportHealthy ? 20 : 500);
  }
}

void pollRawTelemetry();
void loadTierMeta();

api.onPwmEvents((batch: PwmEventBatch) => {
  if (!capturePwm || !batch || !Array.isArray(batch.events) || batch.events.length === 0) return;
  pwmClockHz = batch.clock_hz || pwmClockHz;
  pwmActive = (batch.status & 0x1) !== 0;
  for (const ev of batch.events) {
    const raw = ev.t_cycles >>> 0;
    if (pwmEpoch !== null && ev.epoch !== pwmEpoch) {
      pwmWrapOffsetCycles = 0;
      pwmLastRawCycles = null;
    } else if (pwmLastRawCycles !== null && raw < pwmLastRawCycles && pwmLastRawCycles - raw > 0x80000000) {
      pwmWrapOffsetCycles += PWM_COUNTER_MOD;
    }
    pwmEpoch = ev.epoch;
    pwmLastRawCycles = raw;
    // Absolute run-local hardware time — same origin (counter=0 at Run) as the
    // telemetry timeline, so PWM steps line up with the motor waveforms.
    const tSec = (pwmWrapOffsetCycles + raw) / pwmClockHz;
    appendPwmOverviewUntil(tSec);
    pwmOverviewAState = applyNpcLevel(ev.a, pwmOverviewAState);
    pwmOverviewBState = applyNpcLevel(ev.b, pwmOverviewBState);
    pwmOverviewCState = applyNpcLevel(ev.c, pwmOverviewCState);
    pwmEvents.push({ ...ev, t_sec: tSec });
  }

  if (pwmEvents.length > MAX_PWM_EVENTS) pwmEvents.splice(0, pwmEvents.length - MAX_PWM_EVENTS);
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
  if (state !== "running") pwmActive = false;
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
    motorRs:   Number(elMotorRs.value),
    motorRr:   Number(elMotorRr.value),
    motorLs:   Number(elMotorLs.value),
    motorLr:   Number(elMotorLr.value),
    motorLm:   Number(elMotorLm.value),
    motorJ:    Number(elMotorJ.value),
    npp,
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
  if (s.state !== "running" || s.enable !== 1) pwmActive = false;
  applyBoardIP(s.board_ip);
  // Hydrate form fields only when the board is actively running. A telemetry
  // attach can put the daemon in paused with freq=0, and copying that back into
  // the form makes the next Run command start with a zero-speed target.
  // After Stop the board reports zeroed safe-defaults — we don't want those
  // clobbering whatever the user typed in.
  const hydrate = opts.hydrate ?? (s.state === "running");
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
  streamGeneration++;
  paused = false;
  viewEndSec = 0;
  pwmViewEndSec = 0;
  pwmTelemOffset = 0;
  tBuf.length = 0;
  samplesBuf.length = 0;
  ovTBuf.length = 0;
  ovSBuf.length = 0;
  ovCounter = 0;
  resetOverviewBucket();
  sampleCount = 0;
  rawCursor = 0;
  rawEverWorked = false;
  rawTransportHealthy = true;
  reducedFallbackUsed = false;
  tileCache.clear();
  tierMeta = [];
  latestTiles = [];
  tilesActive = false;
  lastTelemPlotTime = -Infinity;
  telemLastRawCycles = null;
  telemWrapOffsetCycles = 0;
  telemBaseAbsCycles = null;
  telemEpoch = null;
  pwmEvents.length = 0;
  pwmOverviewT.length = 0;
  pwmOverviewA.length = 0;
  pwmOverviewB.length = 0;
  pwmOverviewC.length = 0;
  pwmOverviewNextT = null;
  pwmOverviewAState = 0;
  pwmOverviewBState = 0;
  pwmOverviewCState = 0;
  pwmEpoch = null;
  pwmActive = false;
  pwmLastRawCycles = null;
  pwmWrapOffsetCycles = 0;
  plots.forEach((p, s) => {
    const chIdx = getChIdx(s);
    p.setData([[], ...chIdx.map(() => [])] as uPlot.AlignedData);
  });
  pwmPlot?.setData([[], [], [], []] as uPlot.AlignedData);
  elSampleCount.textContent = "0 samples";
  scheduleRender();
}

// ── Save / Load (.hilbin) ─────────────────────────────────────────────────────
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

  "HILDATA".split('').forEach((c, i) => { u8[i] = c.charCodeAt(0); });
  u8[7] = 1;

  view.setUint32(8, jsonSize, true);
  u8.set(metaBytes, 12);

  let off = alignBase;
  view.setUint32(off, tBuf.length, true); off += 4;
  for (let i = 0; i < tBuf.length; i++) {
    const s = samplesBuf[i];
    view.setFloat32(off,      tBuf[i],    true);
    view.setFloat32(off +  4, s.Ia,       true);
    view.setFloat32(off +  8, s.Ib,       true);
    view.setFloat32(off + 12, s.FluxA,    true);
    view.setFloat32(off + 16, s.FluxB,    true);
    view.setFloat32(off + 20, s.Speed,    true);
    view.setFloat32(off + 24, s.TL ?? 0,  true);
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
  const filename = (name.endsWith(".hilbin") ? name : name + ".hilbin").replace(/[/\\]+/g, "_");
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

function hilbinToCsv(buf: ArrayBuffer): string {
  const u8   = new Uint8Array(buf);
  const view = new DataView(buf);
  const magic = String.fromCharCode(...u8.slice(0, 7));
  if (magic !== "HILDATA") throw new Error("Not a valid .hilbin file");
  const jsonSize  = view.getUint32(8, true);
  const metaStr   = new TextDecoder().decode(u8.slice(12, 12 + jsonSize));
  const meta      = JSON.parse(metaStr);
  const npp: number = meta.npp ?? 2;
  const lm: number  = meta.motor?.lm ?? motorLm;
  const lr: number  = (meta.motor?.lr ?? motorLr - motorLm) + lm;
  const k = 1.5 * npp * (lm / lr);
  const rawBase   = 12 + jsonSize;
  const alignBase = (rawBase + 7) & ~7;
  let off = alignBase;
  const telemCount = view.getUint32(off, true); off += 4;
  const rows: string[] = ["t_s,Ialpha_A,Ibeta_A,Ia_A,Ib_A,Ic_A,FluxAlpha_Wb,FluxBeta_Wb,Speed_rpm,Te_Nm,TL_Nm"];
  for (let i = 0; i < telemCount; i++) {
    const t     = view.getFloat32(off,      true);
    const Ia    = view.getFloat32(off +  4, true);
    const Ib    = view.getFloat32(off +  8, true);
    const FluxA = view.getFloat32(off + 12, true);
    const FluxB = view.getFloat32(off + 16, true);
    const Speed = view.getFloat32(off + 20, true);
    const TL    = view.getFloat32(off + 24, true);
    off += 28;
    const ia = xa(Ia, Ib), ib = xb(Ia, Ib), ic = xc(Ia, Ib);
    const rpm = Speed * 60 / (2 * Math.PI);
    const te  = k * (FluxA * Ib - FluxB * Ia);
    rows.push(`${t},${Ia},${Ib},${ia},${ib},${ic},${FluxA},${FluxB},${rpm},${te},${TL}`);
  }
  return rows.join("\n");
}

function exportToCsv() {
  if (tBuf.length === 0) { setStatus("No data to export", "error"); return; }
  const k = 1.5 * motorNpp * (motorLm / motorLr);
  const rows: string[] = [
    "t_s,Ialpha_A,Ibeta_A,Ia_A,Ib_A,Ic_A,FluxAlpha_Wb,FluxBeta_Wb,Speed_rpm,Te_Nm,TL_Nm"
  ];
  for (let i = 0; i < tBuf.length; i++) {
    const s = samplesBuf[i];
    const ia = xa(s.Ia, s.Ib), ib = xb(s.Ia, s.Ib), ic = xc(s.Ia, s.Ib);
    const rpm = s.Speed * 60 / (2 * Math.PI);
    const te  = k * (s.FluxA * s.Ib - s.FluxB * s.Ia);
    rows.push(`${tBuf[i]},${s.Ia},${s.Ib},${ia},${ib},${ic},${s.FluxA},${s.FluxB},${rpm},${te},${s.TL ?? 0}`);
  }
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  const name = `hil_run_${new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}.csv`;
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
  setStatus(`Exported ${tBuf.length.toLocaleString()} samples → ${name}`, "ok");
}

function showRunMetaBadge(meta: { name: string; date: string; sampleCount: number; pwmCount: number }) {
  const d = meta.date ? new Date(meta.date).toLocaleString() : "unknown date";
  elRunMetaBadge.textContent =
    `Loaded: "${meta.name}" · ${d} · ${meta.sampleCount.toLocaleString()} samples · ${meta.pwmCount.toLocaleString()} PWM events`;
  elRunMetaBadge.classList.remove("hidden");
}

// ── Batch runner ──────────────────────────────────────────────────────────────
function getSavedRecipeNames(): string[] {
  try {
    return Object.keys(JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}"));
  } catch { return []; }
}

function getRecipeByName(name: string): { events: RecipeEvent[]; endTime: number } | null {
  try {
    const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
    const raw = all[name] as RecipeData | undefined;
    if (!raw) return null;
    return parseRecipeData(raw);
  } catch { return null; }
}

function updateBatchEmptyHint() {
  const hasRows = elBatchTable.querySelectorAll(".batch-row").length > 0;
  elBatchEmptyHint.style.display = hasRows ? "none" : "";
}

function updateBatchSummary() {
  const count = elBatchTable.querySelectorAll(".batch-row").length;
  elBatchCount.textContent = `${count} queued`;
  if (!batchRunning) elBatchMeterFill.style.width = "0%";
}

function addBatchRow(preset?: BatchItem): HTMLElement {
  const names = getSavedRecipeNames();
  let opts: string;
  if (names.length === 0) {
    opts = `<option value="" disabled selected>— save a recipe first —</option>`;
  } else {
    const sel = preset?.recipeName ?? names[0];
    opts = names.map(n => `<option${n === sel ? " selected" : ""}>${n}</option>`).join("");
  }
  const row = document.createElement("div");
  row.className = "batch-row";
  row.innerHTML = `
    <select class="write-input">${opts}</select>
    <input type="number" value="${preset?.endDelaySec ?? 2}" min="0" step="0.5" class="write-input" />
    <span class="batch-status" data-status="pending">○</span>
    <button class="scenario-remove" type="button" title="Remove">×</button>`;
  row.querySelector<HTMLButtonElement>(".scenario-remove")
    ?.addEventListener("click", () => { if (!batchRunning) { row.remove(); updateBatchEmptyHint(); updateBatchSummary(); } });
  elBatchTable.appendChild(row);
  updateBatchEmptyHint();
  updateBatchSummary();
  return row;
}

function refreshBatchRecipeSelects() {
  const names = getSavedRecipeNames();
  elBatchTable.querySelectorAll<HTMLSelectElement>(".batch-row select").forEach(sel => {
    const cur = sel.value;
    if (names.length === 0) {
      sel.innerHTML = `<option value="" disabled selected>— save a recipe first —</option>`;
    } else {
      sel.innerHTML = names.map(n => `<option${n === cur ? " selected" : ""}>${n}</option>`).join("");
      if (!names.includes(cur) && names.length > 0) sel.value = names[0];
    }
  });
  updateBatchSummary();
}

function readBatchItems(): BatchItem[] {
  return Array.from(elBatchTable.querySelectorAll<HTMLElement>(".batch-row")).map(row => ({
    recipeName:  row.querySelector<HTMLSelectElement>("select")!.value,
    endDelaySec: Number(row.querySelector<HTMLInputElement>("input")!.value) || 2,
  }));
}

function setBatchItemStatus(rowIndex: number, status: "pending" | "running" | "done" | "error") {
  const rows = elBatchTable.querySelectorAll<HTMLElement>(".batch-row");
  const span = rows[rowIndex]?.querySelector<HTMLSpanElement>(".batch-status");
  if (!span) return;
  const icons: Record<string, string> = { pending: "○", running: "▶", done: "✓", error: "✗" };
  span.textContent = icons[status] ?? "○";
  span.dataset.status = status;
}

function stopBatch() {
  batchRunning = false;
  batchTimeouts.forEach(clearTimeout);
  batchTimeouts = [];
  batchSleepResolvers.splice(0).forEach(resolve => resolve());
  if (batchProgressTimer !== null) { clearInterval(batchProgressTimer); batchProgressTimer = null; }
  elBatchProgress.textContent = "";
  elBatchMeterFill.style.width = "0%";
  elBtnBatchRun.disabled     = false;
  elBtnBatchStop.disabled    = true;
  elBtnAddBatchItem.disabled = false;
  elBatchTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
    .forEach(b => { b.disabled = false; });
  updateBatchEmptyHint();
}

function batchSleep(ms: number): Promise<void> {
  return new Promise(resolve => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      batchTimeouts = batchTimeouts.filter(id => id !== tid);
      batchSleepResolvers = batchSleepResolvers.filter(fn => fn !== finish);
      resolve();
    };
    const tid = window.setTimeout(finish, Math.max(0, ms));
    batchTimeouts.push(tid);
    batchSleepResolvers.push(finish);
  });
}

async function runRecipeEventsSequentially(recipe: { events: RecipeEvent[]; endTime: number }): Promise<boolean> {
  const sorted = [...recipe.events].sort((a, b) => a.t - b.t);
  const lastT = sorted.length ? sorted[sorted.length - 1].t : 0;
  const endTime = Math.max(recipe.endTime, lastT + 0.5);
  let cursor = 0;

  batchCurrentStartedAt = performance.now();
  batchCurrentDuration = endTime;

  for (const ev of sorted) {
    await batchSleep((ev.t - cursor) * 1000);
    if (!batchRunning) return false;
    await dispatchScenarioEvent(ev);
    cursor = ev.t;
  }

  await batchSleep((endTime - cursor) * 1000);
  return batchRunning;
}

async function runBatchSequence() {
  let ip = elIp.value.trim();
  if (!ip) { setStatus("Missing board IP", "error"); stopBatch(); return; }

  try {
    const found = await api.DiscoverBoard(ip) as DiscoveryResponse;
    ip = found.ip || ip;
    applyBoardIP(ip);
    rememberBoardIP(ip);
  } catch { /* proceed with stored IP */ }

  const items = readBatchItems();
  let completed = 0;

  for (let i = 0; i < items.length; i++) {
    if (!batchRunning) break;
    batchIndex = i;
    setBatchItemStatus(i, "running");

    const item = items[i];
    const recipe = getRecipeByName(item.recipeName);
    if (!recipe) {
      setBatchItemStatus(i, "error");
      setStatus(`Recipe "${item.recipeName}" not found`, "error");
      break;
    }

    try {
      elBatchProgress.textContent = `Running ${i + 1}/${items.length}: ${item.recipeName}`;
      await api.StopController(ip);
      await api.ResetSolver(ip);
      captureTelemetry = false;
      capturePwm = false;
      resetPlotBuffer();

      const p = readParams();
      await api.SetParams(ip, p.freq, p.vdc, p.torque, p.baseFreq, p.maxVPu, p.accelTime, false, false, true);
      await api.Run(ip);
      resetPlotBuffer();
      captureTelemetry = true;
      capturePwm = true;

      const finishedRecipe = await runRecipeEventsSequentially(recipe);
      if (!finishedRecipe) break;

      await api.StopController(ip);
      await api.ResetSolver(ip);
      captureTelemetry = false;
      capturePwm = false;

      const ts = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
      const runName = `${safeRunStem(item.recipeName)}_${ts}`;
      await saveRunToServer(runName);

      completed++;
      setBatchItemStatus(i, "done");
      setStatus(`Saved: ${runName}.hilbin`, "ok");

      if (i < items.length - 1 && item.endDelaySec > 0) {
        elBatchProgress.textContent = `Cooling down ${formatScenarioSeconds(item.endDelaySec)} before next recipe`;
        batchCurrentStartedAt = performance.now();
        batchCurrentDuration = item.endDelaySec;
        await batchSleep(item.endDelaySec * 1000);
      }
    } catch (e) {
      setBatchItemStatus(i, "error");
      setStatus(`Batch item ${i + 1} failed: ${e}`, "error");
      break;
    }
  }

  const allDone = completed === items.length && items.length > 0;
  stopBatch();
  updateBatchSummary();
  if (allDone) setStatus("Batch complete", "ok");
}

async function startBatch() {
  if (batchRunning) return;
  const items = readBatchItems();
  if (items.length === 0) { elBatchProgress.textContent = "Add items first"; return; }

  batchRunning = true;
  batchT0      = performance.now();
  batchIndex   = 0;
  batchTimeouts = [];
  batchSleepResolvers.splice(0);
  updateBatchSummary();

  elBtnBatchRun.disabled     = true;
  elBtnBatchStop.disabled    = false;
  elBtnAddBatchItem.disabled = true;
  elBatchTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
    .forEach(b => { b.disabled = true; });
  elBatchTable.querySelectorAll<HTMLElement>(".batch-row")
    .forEach((_, i) => setBatchItemStatus(i, "pending"));

  batchCurrentStartedAt = performance.now();
  batchCurrentDuration = 0;
  batchProgressTimer = window.setInterval(() => {
    const elapsed = ((performance.now() - batchT0) / 1000).toFixed(1);
    const count = readBatchItems().length;
    const itemElapsed = (performance.now() - batchCurrentStartedAt) / 1000;
    const pct = batchCurrentDuration > 0 ? Math.min(100, Math.max(0, itemElapsed / batchCurrentDuration * 100)) : 0;
    elBatchMeterFill.style.width = `${pct}%`;
    elBatchProgress.textContent = `Batch ${batchIndex + 1}/${count} · t=${elapsed}s`;
  }, 200);

  runBatchSequence().finally(() => {
    if (batchProgressTimer !== null) { clearInterval(batchProgressTimer); batchProgressTimer = null; }
    elBtnBatchRun.disabled = false;
  });
}

// ── Run history ───────────────────────────────────────────────────────────────
function parseRunFilename(filename: string): { label: string; date: Date | null } {
  const base = filename.replace(/\.hilbin$/, "");
  const m = base.match(/^(.+)_(\d{14})$/);
  if (m) {
    const ts = m[2];
    const date = new Date(
      parseInt(ts.slice(0, 4)), parseInt(ts.slice(4, 6)) - 1, parseInt(ts.slice(6, 8)),
      parseInt(ts.slice(8, 10)), parseInt(ts.slice(10, 12)), parseInt(ts.slice(12, 14))
    );
    return { label: m[1].replace(/_/g, " "), date };
  }
  return { label: base.replace(/_/g, " "), date: null };
}

function formatRelTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)   return "just now";
  if (m < 60)  return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)  return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7)   return `${d}d ago`;
  return date.toLocaleDateString();
}

function formatBytes(n: number): string {
  if (n < 1024)        return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function safeRunStem(name: string): string {
  return (name || "run")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80) || "run";
}

async function saveRunToServer(name: string): Promise<void> {
  if (isWails) return; // Wails uses native file dialog
  const buf = serializeHilbin(name);
  const filename = (name.endsWith(".hilbin") ? name : name + ".hilbin").replace(/[/\\]+/g, "_");
  const res = await fetch(gatewayURL(`/api/runs?name=${encodeURIComponent(filename)}`), {
    method: "POST",
    headers: { "content-type": "application/octet-stream" },
    body: buf,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`server save failed: ${res.status}${text ? ` ${responseError(res, text)}` : ""}`);
  }
}

async function loadRunHistory(): Promise<void> {
  if (isWails) { elRunsEmpty.textContent = "History not available in Wails mode."; return; }
  try {
    const runs = await getJSON<RunMeta[]>("/api/runs");
    elRunsList.querySelectorAll(".run-card").forEach(c => c.remove());
    for (const run of runs) {
      elRunsList.appendChild(buildRunCard(run));
    }
    applyRunFilter();
  } catch {
    elRunsEmpty.textContent = "Could not load history.";
    elRunsEmpty.style.display = "";
  }
}

function buildRunCard(run: RunMeta): HTMLElement {
  const { label, date } = parseRunFilename(run.name);
  const relTime  = date ? formatRelTime(date) : "—";
  const absTime  = date ? date.toLocaleString() : run.modified;
  const size     = formatBytes(run.size);

  const card = document.createElement("div");
  card.className = "run-card";
  card.dataset.name = run.name.toLowerCase();
  card.dataset.label = label.toLowerCase();
  card.innerHTML = `
    <div class="run-card-body run-btn-load" title="Click to load and view" style="cursor:pointer">
      <div class="run-card-name">${label}</div>
      <div class="run-card-meta">
        <span class="run-card-time" title="${absTime}">${relTime}</span>
        <span class="run-card-size">${size}</span>
      </div>
    </div>
    <div class="run-card-actions">
      <button class="btn btn-xs run-btn-download" data-name="${run.name}" type="button" title="Download .hilbin">↓ .hilbin</button>
      <button class="btn btn-xs run-btn-csv" data-name="${run.name}" type="button" title="Export CSV">↓ CSV</button>
      <button class="btn btn-xs run-btn-delete" data-name="${run.name}" type="button" title="Delete run">✕</button>
    </div>`;

  card.querySelector<HTMLElement>(".run-btn-load")!.addEventListener("click", async () => {
    try {
      const res = await fetch(gatewayURL(`/api/runs/${encodeURIComponent(run.name)}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = await res.arrayBuffer();
      const meta = deserializeHilbin(buf);
      showRunMetaBadge(meta);
      setActiveTab("telemetry");
      elSidebar.classList.remove("sidebar-wide");
      setStatus(`Loaded: ${meta.name} (${meta.sampleCount.toLocaleString()} samples)`, "ok");
    } catch (e) {
      setStatus(`Load failed: ${e}`, "error");
    }
  });

  card.querySelector<HTMLButtonElement>(".run-btn-download")!.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = gatewayURL(`/api/runs/${encodeURIComponent(run.name)}`);
    a.download = run.name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  });

  card.querySelector<HTMLButtonElement>(".run-btn-csv")!.addEventListener("click", async () => {
    try {
      const res = await fetch(gatewayURL(`/api/runs/${encodeURIComponent(run.name)}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = await res.arrayBuffer();
      const csv = hilbinToCsv(buf);
      const blob = new Blob([csv], { type: "text/csv" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = run.name.replace(/\.hilbin$/, "") + ".csv";
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch (e) {
      setStatus(`CSV export failed: ${e}`, "error");
    }
  });

  card.querySelector<HTMLButtonElement>(".run-btn-delete")!.addEventListener("click", async () => {
    if (!confirm(`Delete "${run.name}"?`)) return;
    try {
      await fetch(gatewayURL(`/api/runs/${encodeURIComponent(run.name)}`), { method: "DELETE" });
      card.classList.add("run-card-deleting");
      card.addEventListener("transitionend", () => { card.remove(); updateRunsEmpty(); }, { once: true });
    } catch { /* ignore */ }
  });

  return card;
}

function applyRunFilter() {
  const q = elRunsSearch.value.trim().toLowerCase();
  const cards = Array.from(elRunsList.querySelectorAll<HTMLElement>(".run-card"));
  let visible = 0;
  cards.forEach(card => {
    const haystack = `${card.dataset.name ?? ""} ${card.dataset.label ?? ""}`;
    const show = !q || haystack.includes(q);
    card.style.display = show ? "" : "none";
    if (show) visible++;
  });
  elRunsSummary.textContent = q ? `${visible}/${cards.length} runs` : `${cards.length} runs`;
  elRunsEmpty.textContent = cards.length === 0 ? "No runs saved yet." : "No runs match the filter.";
  elRunsEmpty.style.display = visible ? "none" : "";
}

function updateRunsEmpty() {
  applyRunFilter();
}

// ── Scenario / batch config export-import ────────────────────────────────────
function exportConfig() {
  const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
  const batchItems = readBatchItems();
  const config = { version: 1, exported: new Date().toISOString(), recipes: all, batch: batchItems };
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = `hil-config-${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
}

function importConfig(file: File) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const config = JSON.parse(reader.result as string);
      // Merge recipes
      const existing = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
      const merged = { ...existing, ...(config.recipes ?? {}) };
      localStorage.setItem(RECIPE_KEY, JSON.stringify(merged));
      refreshBatchRecipeSelects();
      // Restore batch rows if present
      if (Array.isArray(config.batch) && config.batch.length > 0) {
        elBatchTable.querySelectorAll(".batch-row").forEach(r => r.remove());
        config.batch.forEach((item: BatchItem) => addBatchRow(item));
      }
      const count = Object.keys(config.recipes ?? {}).length;
      setStatus(`Imported ${count} recipe(s)`, "ok");
    } catch (e) {
      setStatus(`Import failed: ${e}`, "error");
    }
    elConfigImportInput.value = "";
  };
  reader.readAsText(file);
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
  captureTelemetry = false;
  capturePwm = false;
  resetPlotBuffer();
  // single hello → attaches telemetry to this PC and pulls current state
  const s = await api.AttachTelemetry(ip) as HilStatus;
  const boardIP = s.board_ip || ip;
  applyBoardIP(boardIP);
  rememberBoardIP(boardIP);
  showConnStatus(`Connected to ${boardIP} — daemon ${s.state}`, true);
  setStatus(`Connected to ${boardIP}`, "ok");
  applyResponse(s, { hydrate: false });
}));

elBtnApplyMotor.addEventListener("click", () => withButton(elBtnApplyMotor, async () => {
  const { ip, motorRs, motorRr, motorLs, motorLr, motorLm, motorJ, npp } = readParams();
  const s = await api.ProgramMotor(ip, motorRs, motorRr, motorLs, motorLr, motorLm, motorJ, npp) as HilStatus;
  applyBoardIP(s.board_ip);
  rememberBoardIP(s.board_ip || ip);
  setStatus("Motor model applied atomically", "ok");
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
  captureTelemetry = false;
  capturePwm = false;
  resetPlotBuffer();
  await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, accelTime, false, false, true);
  const s = await api.Run(ip) as HilStatus;
  resetPlotBuffer();
  captureTelemetry = true;
  capturePwm = true;
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
  paused = true;
  viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
  setStatus("Stopped (daemon alive — can Run again)", "ok");
  applyResponse(s);
  scheduleRender();
}));

// Smoothing (10-sample boxcar ≈ 1 ms ≈ 1 PWM period at 10 kHz) is always on
// — it cancels residual PWM ripple in min/max envelope rendering. Live mode
// (auto-follow tail) is also always on; user panning/zooming disables it
// automatically via the setScale hook.

function detachOnExit() {
  const ip = elIp.value.trim();
  if (!ip || isWails) return;
  const payload = JSON.stringify({ ip });
  if (navigator.sendBeacon) {
    navigator.sendBeacon(gatewayURL("/api/detach"), new Blob([payload], { type: "application/json" }));
    return;
  }
  fetch(gatewayURL("/api/detach"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

window.addEventListener("pagehide", detachOnExit);

// ── Scope-style view controls ────────────────────────────────────────────────
function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v;
}

function updateWindowButtons() {
  const session = getSessionSec();
  document.querySelectorAll<HTMLButtonElement>("#window-group button[data-win-ms]")
    .forEach(b => {
      const ms = Number(b.dataset.winMs);
      if (ms === 0) {
        // "All" is active when the window covers (nearly) the full session.
        b.classList.toggle("active", session > 0 && windowSec >= session - 0.5);
      } else {
        b.classList.toggle("active", Math.abs(ms / 1000 - windowSec) < 1e-6);
      }
    });
}

document.querySelectorAll<HTMLButtonElement>("#window-group button[data-win-ms]")
  .forEach(b => {
    b.addEventListener("click", () => {
      const ms = Number(b.dataset.winMs);
      if (ms === 0) {
        // "All" — zoom out to cover the complete session and pause the view.
        const session = getSessionSec();
        windowSec = session > 0 ? Math.max(session, WINDOW_MIN_SEC) : WINDOW_MAX_SEC;
        paused = true;
        viewEndSec = ovTBuf.length > 0
          ? ovTBuf[ovTBuf.length - 1]
          : (tBuf.length > 0 ? tBuf[tBuf.length - 1] : 0);
      } else {
        const maxSec = Math.max(WINDOW_MAX_SEC, getSessionSec() + 10);
        windowSec = clamp(ms / 1000, WINDOW_MIN_SEC, maxSec);
      }
      viewEndSec = clampViewEndToTimeZero();
      updateWindowButtons();
      scheduleRender();
    });
  });
updateWindowButtons();
attachTimelineNavigation();
updateTimelineBar();

elBtnPause.addEventListener("click", () => {
  if (paused) {
    // Resuming → snap to latest so we don't show a stale freeze with
    // newer samples lurking off-screen on the right.
    paused = false;
  } else {
    paused = true;
    viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
  }
  scheduleRender();
});

elBtnLatest.addEventListener("click", () => {
  paused = false;
  scheduleRender();
});

elBtnLive.onclick = () => {
  paused = false;
  if (tBuf.length) viewEndSec = tBuf[tBuf.length - 1];
  tilesActive = false;
  latestTiles = [];
  scheduleRender();
};

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

// ── About modal ───────────────────────────────────────────────────────────────
type AboutSection = { title: string; text: string; images: { src: string; alt: string; small?: boolean; medium?: boolean }[] };
const ABOUT_SECTIONS: AboutSection[] = [
  {
    title: "Sobre o Projeto",
    text: "O HIL Monitor é uma interface de monitoramento e controle para simulação Hardware-in-the-Loop (HIL) de motores de indução. Desenvolvido no Laboratório de Sistemas Embarcados (LSE-PPGESE), o sistema emula o comportamento eletromecânico do motor em tempo real utilizando FPGA.",
    images: [],
  },
  {
    title: "Arquitetura do Sistema",
    text: "O sistema integra um solver de equações diferenciais implementado em FPGA, um daemon de controle em Go e esta interface web. A telemetria é transmitida via UDP e renderizada em tempo real.",
    images: [{ src: "/HIL_Diagram.png", alt: "Diagrama do Sistema HIL", medium: true }],
  },
  {
    title: "Como Usar",
    text: "1. Informe o IP do board e clique em Find/Connect.\n2. Configure os parâmetros do motor na aba Plant.\n3. Defina os setpoints de velocidade e torque na aba Control.\n4. Clique em Run para iniciar a simulação.\n5. Acompanhe os sinais na aba Telemetry.",
    images: [],
  },
  {
    title: "Equipe & Instituição",
    text: "Projeto desenvolvido no Laboratório de Sistemas Embarcados (LSE) da Universidade Federal de Santa Catarina (UFSC).",
    images: [{ src: "/LSE_LOGO.png", alt: "LSE", small: true }],
  },
];

function buildAboutModal(): HTMLElement {
  const overlay = document.createElement("div");
  overlay.id = "about-overlay";
  overlay.className = "modal-overlay";

  const sectionsHtml = ABOUT_SECTIONS.map(s => {
    const textHtml = s.text.split("\n").map(line => `<p>${line}</p>`).join("");
    const imgsHtml = s.images.length
      ? `<div class="about-imgs">${s.images.map(img =>
          `<img src="${img.src}" alt="${img.alt}" class="about-img${img.small ? " about-img-small" : img.medium ? " about-img-medium" : ""}" />`
        ).join("")}</div>`
      : "";
    return `
      <div class="about-section">
        <div class="about-section-title">${s.title}</div>
        <div class="about-section-body">${textHtml}${imgsHtml}</div>
      </div>`;
  }).join("");

  overlay.innerHTML = `
    <div class="modal-box about-modal-box">
      <div class="modal-header">
        <span>HIL Monitor — Sobre o Projeto</span>
        <button id="btn-about-close" class="icon-btn" style="font-size:18px">×</button>
      </div>
      <div class="about-modal-body">${sectionsHtml}</div>
    </div>`;

  document.body.appendChild(overlay);

  function closeAbout() { overlay.classList.add("hidden"); }
  overlay.addEventListener("click", e => { if (e.target === overlay) closeAbout(); });
  overlay.querySelector("#btn-about-close")!.addEventListener("click", closeAbout);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) closeAbout();
  });

  return overlay;
}

const aboutOverlay = buildAboutModal();

const elBtnAbout = document.createElement("button");
elBtnAbout.className = "icon-btn btn-about";
elBtnAbout.title = "Sobre o projeto";
elBtnAbout.textContent = "ⓘ";
document.querySelector(".sidebar-badges")!.appendChild(elBtnAbout);
elBtnAbout.addEventListener("click", () => aboutOverlay.classList.remove("hidden"));
