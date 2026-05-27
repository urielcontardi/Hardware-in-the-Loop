import "uplot/dist/uPlot.min.css";
import "./styles.css";
import uPlot from "uplot";
import * as WailsRuntime from "../wailsjs/runtime/runtime";
import * as WailsApp from "../wailsjs/go/main/App";

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

let sharedEvents: EventSource | null = null;
function getSharedEvents(): EventSource {
  if (!sharedEvents) sharedEvents = new EventSource("/events");
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
const MAX_SAMPLES = 600_000;
// Overview buffer: stores min+max of channel-0 (Iα) per 1000-sample bucket.
// At 10 kHz / 1000 = 10 Hz decimation rate; each 100 ms bucket captures ~6
// full electrical cycles of a 60 Hz motor, so the min/max pair preserves the
// signal envelope accurately at any zoom level without aliasing.
// 2 pts/bucket × 10 Hz × 7200 s ≈ 144 000 pts → ~2 h of session history.
const OVERVIEW_EVERY = 1_000;
const MAX_OVERVIEW_SAMPLES = 144_000;
// Both telemetry samples and PWM events are timestamped by the SAME run-local
// FPGA counter (hil_time <= pwm_cap_time in RTL). Using hardware time for both
// gives exact alignment. Two edge-cases are handled:
//   • Counter frozen when solver is idle → duplicate t_cycles → enforce
//     strict monotonicity by nudging forward by a nominal period.
//   • Counter resets to 0 on each run (epoch++) → clear telemetry buffers
//     on epoch change so old samples never bleed into the new run's view.
const HW_CLOCK_HZ             = 100_000_000;
const TELEM_NOMINAL_PERIOD_S  = 1 / 9_876;   // ≈ 100 µs at transportDecim=375

// ── App state ─────────────────────────────────────────────────────────────────
const tBuf: number[]      = [];
const samplesBuf: Sample[] = [];   // raw αβ samples paralelos a tBuf
// Overview buffers — min+max envelope pairs per OVERVIEW_EVERY raw samples.
// Used for rendering when the view extends further back than the high-res buffer.
const ovTBuf: number[]    = [];
const ovSBuf:  Sample[]   = [];
let   ovCounter            = 0;
// Per-bucket accumulators (reset each time ovCounter reaches OVERVIEW_EVERY).
let ovBucketMinV = Infinity,  ovBucketMaxV = -Infinity;
let ovBucketMinT = 0,         ovBucketMaxT = 0;
let ovBucketMinS: Sample | null = null, ovBucketMaxS: Sample | null = null;
let sampleCount = 0;
let lastBoardState: string = "idle";
let lastSampleAt = 0;             // ms — for stream stalled detection
let telemLastRawCycles: number | null = null;
let telemWrapOffsetCycles = 0;
let telemEpoch: number | null = null;
let lastTelemPlotTime = 0;        // enforces strict monotonicity in tBuf
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
const WINDOW_MAX_SEC = 60.0;     //  60 s  — full buffer width (= MAX_SAMPLES/fs)

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

      <div class="sidebar-tabs" role="tablist" aria-label="HIL panels">
        <button class="tab-btn active" data-tab="plant" type="button">Plant</button>
        <button class="tab-btn" data-tab="control" type="button">Control</button>
        <button class="tab-btn" data-tab="scenario" type="button">Scenarios</button>
        <button class="tab-btn" data-tab="telemetry" type="button">Telemetry</button>
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
            <label title="Torque de carga mecânica aplicado ao rotor">Torque (N·m)</label>
            <input id="torque" type="number" value="0" min="-200" max="200" step="1" class="write-input" />
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
          <div class="field-inline">
            <label>Name</label>
            <input id="scenario-name" type="text" value="motor_fault_step" class="write-input" />
          </div>
          <div class="scenario-toolbar">
            <button id="btn-recipe-load" class="btn btn-sm" type="button">Load</button>
            <button id="btn-recipe-save" class="btn btn-sm" type="button">Save</button>
            <button id="btn-recipe-run"  class="btn btn-sm" type="button">Run recipe</button>
            <span   id="scenario-progress" class="scenario-progress"></span>
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
                <option>torque_nm</option>
                <option>rs</option>
                <option>rr</option>
                <option>vdc_v</option>
              </select>
              <input type="number" value="1800" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
            <div class="scenario-row">
              <input type="number" value="2.0" min="0" step="0.001" class="write-input" />
              <select class="write-input">
                <option>motor</option>
                <option>control</option>
                <option>load</option>
              </select>
              <select class="write-input">
                <option>rs</option>
                <option>rr</option>
                <option>lm</option>
                <option>torque_nm</option>
                <option>speed_rpm</option>
              </select>
              <input type="number" value="0.9" step="0.001" class="write-input" />
              <button class="scenario-remove" type="button" title="Remove event">x</button>
            </div>
          </div>
          <button id="btn-add-scenario-event" class="btn btn-sm scenario-add" type="button">Add event</button>
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
            <span class="subplot-layout-label">Subplots</span>
            <div class="subplot-n-group">
              <button class="subplot-n-btn" data-n="1">1</button>
              <button class="subplot-n-btn" data-n="2">2</button>
              <button class="subplot-n-btn" data-n="3">3</button>
              <button class="subplot-n-btn active" data-n="4">4</button>
            </div>
          </div>

          <div class="subplot-layout-row">
            <span class="subplot-layout-label">Window</span>
            <div class="subplot-n-group" id="window-group">
              <button class="subplot-n-btn" data-win-ms="20">20ms</button>
              <button class="subplot-n-btn" data-win-ms="100">100ms</button>
              <button class="subplot-n-btn" data-win-ms="500">500ms</button>
              <button class="subplot-n-btn active" data-win-ms="1000">1s</button>
              <button class="subplot-n-btn" data-win-ms="5000">5s</button>
              <button class="subplot-n-btn" data-win-ms="30000">30s</button>
              <button class="subplot-n-btn" data-win-ms="0">All</button>
            </div>
          </div>

          <div class="btn-row" style="margin-top:6px">
            <button id="btn-pause" class="btn btn-sm" title="Pause the live view (or use mouse wheel on plot)">Pause</button>
            <button id="btn-latest" class="btn btn-sm" title="Snap to the latest sample and resume live follow">Latest</button>
          </div>

          <div id="ch-list" class="channel-list"></div>

          <div class="btn-row" style="margin-top:8px">
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
      </div>

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
const elPsStatus    = document.querySelector<HTMLDivElement>("#ps-status")!;
const elConnStatus  = document.querySelector<HTMLDivElement>("#conn-status")!;
const elStateBadge  = document.querySelector<HTMLDivElement>("#state-badge")!;
const elWsBadge     = document.querySelector<HTMLDivElement>("#ws-badge")!;
const elStatus      = document.querySelector<HTMLDivElement>("#status")!;
const elSampleCount = document.querySelector<HTMLSpanElement>("#sample-count")!;
const elChList      = document.querySelector<HTMLDivElement>("#ch-list")!;
const elPlotArea    = document.querySelector<HTMLElement>("#plot-area")!;
const elScenarioTable    = document.querySelector<HTMLDivElement>("#scenario-table")!;
const elBtnAddScenarioEvent = document.querySelector<HTMLButtonElement>("#btn-add-scenario-event")!;
const elBtnRecipeLoad    = document.querySelector<HTMLButtonElement>("#btn-recipe-load")!;
const elBtnRecipeSave    = document.querySelector<HTMLButtonElement>("#btn-recipe-save")!;
const elBtnRecipeRun     = document.querySelector<HTMLButtonElement>("#btn-recipe-run")!;
const elScenarioName     = document.querySelector<HTMLInputElement>("#scenario-name")!;
const elScenarioProgress = document.querySelector<HTMLSpanElement>("#scenario-progress")!;

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
  btn.addEventListener("click", () => setActiveTab(btn.dataset.tab || "plant"));
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
  elScenarioTable.appendChild(row);
  bindScenarioRow(row);
  return row;
}

document.querySelectorAll<HTMLElement>(".scenario-row").forEach(bindScenarioRow);
elBtnAddScenarioEvent.addEventListener("click", () => { if (!scenarioRunning) addScenarioRow(); });

// ── Scenario execution state ──────────────────────────────────────────────────
let scenarioRunning = false;
let scenarioTimeouts: number[] = [];
let scenarioProgressTimer: number | null = null;
let scenarioT0 = 0;

function readScenarioEvents() {
  return Array.from(elScenarioTable.querySelectorAll<HTMLElement>(".scenario-row"))
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

async function dispatchScenarioEvent(ev: { target: string; param: string; value: number }) {
  const ip = elIp.value.trim();
  if (!ip) return;
  try {
    const p = readParams();
    if (ev.target === "control" || ev.target === "load") {
      let freq = p.freq, vdc = p.vdc, torque = p.torque;
      let baseFreq = p.baseFreq, maxVPu = p.maxVPu, accelTime = p.accelTime;
      switch (ev.param) {
        case "speed_rpm":    freq      = ev.value * p.npp / 60; break;
        case "torque_nm":    torque    = ev.value;              break;
        case "vdc_v":        vdc       = ev.value;              break;
        case "accel_time_s": accelTime = ev.value;              break;
        case "max_v_pu":     maxVPu    = ev.value;              break;
        case "base_freq_hz": baseFreq  = ev.value;              break;
      }
      await api.SetParams(ip, freq, vdc, torque, baseFreq, maxVPu, accelTime, false, false, false);
    } else if (ev.target === "motor") {
      const m: Record<string, number> = {
        rs: p.motorRs, rr: p.motorRr, ls: p.motorLs,
        lr: p.motorLr, lm: p.motorLm, j:  p.motorJ,  npp: p.npp,
      };
      m[ev.param] = ev.value;
      await api.ProgramMotor(ip, m.rs, m.rr, m.ls, m.lr, m.lm, m.j, m.npp);
    }
  } catch { /* scenario continues on transient errors */ }
}

function stopScenario() {
  scenarioRunning = false;
  scenarioTimeouts.forEach(clearTimeout);
  scenarioTimeouts = [];
  if (scenarioProgressTimer !== null) { clearInterval(scenarioProgressTimer); scenarioProgressTimer = null; }
  elScenarioTable.querySelectorAll(".scenario-row").forEach(r =>
    r.classList.remove("sc-active", "sc-done"));
  elScenarioProgress.textContent = "";
  elBtnRecipeRun.textContent = "Run recipe";
  elBtnRecipeRun.classList.remove("btn-danger");
  elBtnRecipeLoad.disabled = false;
  elBtnRecipeSave.disabled = false;
  elBtnAddScenarioEvent.disabled = false;
  elScenarioTable.querySelectorAll<HTMLButtonElement>(".scenario-remove")
    .forEach(b => { b.disabled = false; });
}

function startScenario() {
  if (scenarioRunning) { stopScenario(); return; }
  const events = readScenarioEvents();
  if (events.length === 0) return;

  scenarioRunning = true;
  scenarioT0 = performance.now();
  scenarioTimeouts = [];

  elBtnRecipeRun.textContent = "■ Stop";
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

  // Auto-stop half a second after the last event fires
  const lastT = events[events.length - 1].t;
  scenarioTimeouts.push(window.setTimeout(() => {
    const last = events[events.length - 1];
    last.row.classList.remove("sc-active");
    last.row.classList.add("sc-done");
    stopScenario();
  }, (lastT + 0.5) * 1000));

  scenarioProgressTimer = window.setInterval(() => {
    const elapsed = (performance.now() - scenarioT0) / 1000;
    elScenarioProgress.textContent = `t = ${elapsed.toFixed(1)} s`;
  }, 100);
}

// ── Recipe persistence (localStorage) ────────────────────────────────────────
const RECIPE_KEY = "hil-scenario-recipes";

function saveRecipe() {
  const name   = elScenarioName.value.trim() || "default";
  const events = readScenarioEvents().map(({ t, target, param, value }) => ({ t, target, param, value }));
  try {
    const all = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
    all[name] = events;
    localStorage.setItem(RECIPE_KEY, JSON.stringify(all));
    const orig = elBtnRecipeSave.textContent!;
    elBtnRecipeSave.textContent = "Saved ✓";
    window.setTimeout(() => { elBtnRecipeSave.textContent = orig; }, 1500);
  } catch { /* storage not available */ }
}

function loadRecipe() {
  const name = elScenarioName.value.trim() || "default";
  try {
    const all    = JSON.parse(localStorage.getItem(RECIPE_KEY) || "{}");
    const events = all[name] as { t: number; target: string; param: string; value: number }[] | undefined;
    if (!events?.length) {
      const orig = elBtnRecipeLoad.textContent!;
      elBtnRecipeLoad.textContent = "Not found";
      window.setTimeout(() => { elBtnRecipeLoad.textContent = orig; }, 1500);
      return;
    }
    elScenarioTable.querySelectorAll(".scenario-row").forEach(r => r.remove());
    events.forEach(ev => addScenarioRow(ev));
  } catch { /* storage not available */ }
}

elBtnRecipeLoad.addEventListener("click", loadRecipe);
elBtnRecipeSave.addEventListener("click", saveRecipe);
elBtnRecipeRun.addEventListener("click", startScenario);

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
// smoothWin > 1 activates a moving-average pre-filter that removes PWM
// switching ripple. Win=10 ≈ one 1 kHz PWM period at 10 kHz sample rate.
let smoothWin = 10;  // default: remove 1 kHz PWM ripple (10 samples = 1 PWM period)

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

// Decimate an arbitrary time/sample buffer pair to ~maxPts points in [xMin, xMax].
// xMin/xMax === null means "use the entire buffer".
// Decimation works on the VISIBLE slice so zooming in always gives full resolution.
function decimateFrom(
  tbuf: number[], sbuf: Sample[],
  maxPts: number, xMin: number | null, xMax: number | null,
): { xs: number[]; ys: number[][] } {
  const total = tbuf.length;
  if (total === 0) return { xs: [], ys: Array.from({ length: N_CH }, () => []) };

  const iStart = xMin == null ? 0     : lowerBound(xMin, tbuf);
  const iEnd   = xMax == null ? total : lowerBound(xMax, tbuf);
  const n = Math.max(0, iEnd - iStart);
  if (n === 0) return { xs: [], ys: Array.from({ length: N_CH }, () => []) };

  const smoothed = smoothWin <= 1
    ? (c: number, i: number) => CHANNELS[c].read(sbuf[i])
    : (c: number, i: number) => {
        const half = Math.floor(smoothWin / 2);
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

  const buckets = Math.max(1, Math.floor(maxPts / 2));
  const bucketSize = n / buckets;
  const xs: number[] = [];
  const ys: number[][] = Array.from({ length: N_CH }, () => []);

  for (let b = 0; b < buckets; b++) {
    const i0 = iStart + Math.floor(b * bucketSize);
    const i1 = Math.min(iStart + Math.floor((b + 1) * bucketSize), iEnd) - 1;
    if (i0 > i1) continue;

    let minIdx = i0, maxIdx = i0;
    let minV = smoothed(0, i0);
    let maxV = minV;
    for (let i = i0 + 1; i <= i1; i++) {
      const v = smoothed(0, i);
      if (v < minV) { minV = v; minIdx = i; }
      if (v > maxV) { maxV = v; maxIdx = i; }
    }

    const [first, second] = minIdx <= maxIdx ? [minIdx, maxIdx] : [maxIdx, minIdx];
    xs.push(tbuf[first]);
    for (let c = 0; c < N_CH; c++) ys[c].push(smoothed(c, first));
    if (first !== second) {
      xs.push(tbuf[second]);
      for (let c = 0; c < N_CH; c++) ys[c].push(smoothed(c, second));
    }
  }

  return { xs, ys };
}

// Route to the overview (downsampled) buffer only when the high-res buffer has
// actually rolled (tBuf filled to capacity and started dropping old samples) AND
// the view extends before the surviving high-res window. While the session is
// younger than MAX_SAMPLES/fs (60 s), tBuf still holds every sample since t=0
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

    // ── Wheel: zoom the time window. Window (zoom) and pause (scroll-or-not)
    // are intentionally orthogonal — wheeling never touches pause state. If
    // you're live and zoom out, you see more recent history including the
    // present; if you're paused, the right edge stays where you left it.
    wrap.addEventListener("wheel", (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.25 : 0.8;
      const maxSec = Math.max(WINDOW_MAX_SEC, getSessionSec() + 10);
      const next = clamp(windowSec * factor, WINDOW_MIN_SEC, maxSec);
      if (next === windowSec) return;

      // Freeze live follow so viewEndSec is stable during zoom
      if (!paused) {
        paused = true;
        viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
      }

      // Keep the time value under the cursor at the same screen position.
      // mouseRatio: 0 = left edge, 1 = right edge of the plot.
      const rect = wrap.getBoundingClientRect();
      const mouseRatio = (e.clientX - rect.left) / rect.width;
      const timeCursor = (viewEndSec - windowSec) + mouseRatio * windowSec;

      // After zoom: newViewEnd so timeCursor stays at mouseRatio.
      viewEndSec = timeCursor + (1 - mouseRatio) * next;

      windowSec = next;
      updateWindowButtons();
      scheduleRender();
    }, { passive: false });

    // ── Drag horizontal: pan in time. Active only while paused (in live
    // mode a pan would fight the auto-scroll, so we ignore drags there).
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
      const pxPerSec = wrap.clientWidth / windowSec;
      viewEndSec = dragStartViewEnd - dx / pxPerSec;
      scheduleRender();
    };
    const onUp = () => {
      if (dragStartX == null) return;
      dragStartX = null;
      wrap.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
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
  // NPC gate-state encoding from RTL: 0011=+Vdc/2, 0110=0, 1100=-Vdc/2.
  // Other short-lived codes are deadtime/transient gate combinations; plotting
  // them as zero creates false PWM pulses, so the renderer holds last valid.
  if (state === 0b0011) return 1;
  if (state === 0b0110) return 0;
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

function pwmStepData(viewStart: number, viewEnd: number): [number[], number[], number[], number[]] {
  const maxTransitions = Math.max(2000, (elPlotArea.clientWidth || 800) * 8);
  if (pwmEvents.length === 0) return pwmOverviewData(viewStart, viewEnd, maxTransitions);

  const firstTime = pwmTime(pwmEvents[0]);
  const lastTime = pwmTime(pwmEvents[pwmEvents.length - 1]);
  if (viewStart < firstTime || viewEnd - viewStart > 10.0) {
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
  let prevIdx = 0;
  for (let i = 0; i < pwmEvents.length; i++) {
    const t = pwmTime(pwmEvents[i]);
    if (t <= plotStart) prevIdx = i;
    if (t > plotEnd) break;
  }
  let firstIdx = prevIdx;
  while (firstIdx < pwmEvents.length && pwmTime(pwmEvents[firstIdx]) < plotStart) firstIdx++;
  let lastIdx = firstIdx;
  while (lastIdx < pwmEvents.length && pwmTime(pwmEvents[lastIdx]) <= plotEnd) lastIdx++;
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

// Wipes only the telemetry data buffers — called when the FPGA epoch changes
// (new Run) so stale pre-run samples at the frozen counter value are removed
// before the fresh run's samples arrive at t≈0.
function clearTelemBuffers() {
  tBuf.length = 0;
  samplesBuf.length = 0;
  ovTBuf.length = 0;
  ovSBuf.length = 0;
  ovCounter = 0;
  ovBucketMinV = Infinity; ovBucketMaxV = -Infinity;
  ovBucketMinS = null;     ovBucketMaxS = null;
  lastTelemPlotTime = 0;
  sampleCount = 0;
}

function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => {
    renderPending = false;

    // Resolve the visible window. While running live we keep the right edge
    // glued to the most recent sample; while paused viewEndSec is whatever
    // the pause/pan left behind.
    if (!paused && tBuf.length > 0) {
      viewEndSec = tBuf[tBuf.length - 1];
    }
    const viewEnd   = viewEndSec;
    const viewStart = viewEnd - windowSec;

    const w = elPlotArea.clientWidth || 800;
    const maxPts = Math.max(600, w * 2);
    const { xs, ys } = decimateAndProject(maxPts, viewStart, viewEnd);

    scaleSyncing = true;
    plots.forEach((p, s) => {
      const chIdx = getChIdx(s);
      p.setData([xs, ...chIdx.map(ci => ys[ci])] as uPlot.AlignedData);
      // Explicit, identical X scale on every plot — no auto-fit, no surprise
      // range shifts. uPlot's cursor.sync still keeps the crosshair aligned.
      p.setScale("x", { min: viewStart, max: viewEnd });
    });
    if (pwmPlot) {
      // PWM window in hardware time (see pwmViewEndSec note). Live: glue to the
      // newest PWM event and remember its offset from the telemetry edge.
      // Paused: ride that offset so panning/zooming the telemetry view carries
      // the PWM view along by the same amount.
      if (!paused && pwmEvents.length > 0) {
        pwmViewEndSec = pwmEvents[pwmEvents.length - 1].t_sec;
        pwmTelemOffset = pwmViewEndSec - viewEnd;
      } else {
        pwmViewEndSec = viewEnd + pwmTelemOffset;
      }
      const pwmStart = pwmViewEndSec - windowSec;
      const [px, pa, pb, pc] = pwmStepData(pwmStart, pwmViewEndSec);
      pwmPlot.setData([px, pa, pb, pc] as uPlot.AlignedData);
      pwmPlot.setScale("x", { min: pwmStart, max: pwmViewEndSec });
      pwmPlot.setScale("y", { min: -1.25, max: 1.25 });
    }
    scaleSyncing = false;

    elSampleCount.textContent = `${sampleCount.toLocaleString()} samples`;
    elBtnPause.textContent = paused ? "▶ Resume" : "⏸ Pause";
    elBtnPause.classList.toggle("active", paused);
    elBtnLatest.disabled = !paused;
  });
}

// ── Telemetry events ──────────────────────────────────────────────────────────
api.onTelemetry((samples: Sample[]) => {
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
      telemLastRawCycles = null;
    } else if (telemLastRawCycles !== null && raw < telemLastRawCycles
               && telemLastRawCycles - raw > 0x80000000) {
      telemWrapOffsetCycles += PWM_COUNTER_MOD;  // 32-bit wrap
    }
    telemEpoch          = epoch;
    telemLastRawCycles  = raw;

    let hwSec = (telemWrapOffsetCycles + raw) / HW_CLOCK_HZ;

    // Enforce strict monotonicity: when the solver is idle the counter
    // freezes, producing duplicate t_cycles. Nudge forward by one nominal
    // period so the min/max decimator always gets ordered, even buckets.
    if (hwSec <= lastTelemPlotTime) hwSec = lastTelemPlotTime + TELEM_NOMINAL_PERIOD_S;
    lastTelemPlotTime = hwSec;

    const sampleTime = hwSec;
    tBuf.push(sampleTime);
    samplesBuf.push(s);

    // Track min+max of Iα within the current overview bucket (s.Ia = Iα).
    const v0 = s.Ia;
    if (v0 < ovBucketMinV) { ovBucketMinV = v0; ovBucketMinT = sampleTime; ovBucketMinS = s; }
    if (v0 > ovBucketMaxV) { ovBucketMaxV = v0; ovBucketMaxT = sampleTime; ovBucketMaxS = s; }
    if (++ovCounter >= OVERVIEW_EVERY) {
      ovCounter = 0;
      if (ovBucketMinS !== null) {
        const [fT, fS, sT, sS] = ovBucketMinT <= ovBucketMaxT
          ? [ovBucketMinT, ovBucketMinS, ovBucketMaxT, ovBucketMaxS!]
          : [ovBucketMaxT, ovBucketMaxS!, ovBucketMinT, ovBucketMinS];
        ovTBuf.push(fT); ovSBuf.push(fS);
        if (fT !== sT) { ovTBuf.push(sT); ovSBuf.push(sS); }
        if (ovTBuf.length > MAX_OVERVIEW_SAMPLES) {
          const trim = ovTBuf.length - MAX_OVERVIEW_SAMPLES;
          ovTBuf.splice(0, trim); ovSBuf.splice(0, trim);
        }
      }
      ovBucketMinV = Infinity; ovBucketMaxV = -Infinity;
      ovBucketMinS = null;     ovBucketMaxS = null;
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
});

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
  paused = false;
  viewEndSec = 0;
  pwmViewEndSec = 0;
  pwmTelemOffset = 0;
  tBuf.length = 0;
  samplesBuf.length = 0;
  ovTBuf.length = 0;
  ovSBuf.length = 0;
  ovCounter = 0;
  ovBucketMinV = Infinity; ovBucketMaxV = -Infinity;
  ovBucketMinS = null;     ovBucketMaxS = null;
  sampleCount = 0;
  lastTelemPlotTime = 0;
  telemLastRawCycles = null;
  telemWrapOffsetCycles = 0;
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
  captureTelemetry = false;
  capturePwm = false;
  applyBoardIP(s.board_ip);
  paused = true;
  viewEndSec = tBuf.length ? tBuf[tBuf.length - 1] : viewEndSec;
  setTelemBadge(false, false);
  setStatus("Stopped (daemon alive — can Run again)", "ok");
  applyResponse(s);
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
      updateWindowButtons();
      scheduleRender();
    });
  });
updateWindowButtons();

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
