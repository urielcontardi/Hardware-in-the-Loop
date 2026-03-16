import "uplot/dist/uPlot.min.css";
import "./styles.css";

import uPlot from "uplot";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type TelemetrySample = {
  t_ms: number;
  regs: number[];
};

type StreamConfig = {
  portName: string;
  baudRate: number;
  sampleHz: number;
  flushMs: number;
  chunkSamples: number;
  dataWidth: number;
};

const REG_NAMES = [
  "VDC_BUS",
  "TORQUE_LOAD",
  "VA_MOTOR",
  "VB_MOTOR",
  "VC_MOTOR",
  "I_ALPHA",
  "I_BETA",
  "FLUX_ALPHA",
  "FLUX_BETA",
  "SPEED_MECH",
];

const app = document.querySelector("#app");
if (!app) {
  throw new Error("App root not found");
}

app.innerHTML = `
  <h1>HIL Real-Time Monitor</h1>
  <div class="layout">
    <aside class="card controls">
      <div class="field">
        <label for="port">Serial Port</label>
        <div class="row">
          <select id="port"></select>
          <button id="refreshPorts">Refresh</button>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="baud">Baud</label>
          <input id="baud" type="number" value="115200" min="9600" step="100" />
        </div>
        <div class="field">
          <label for="sampleHz">Sample Hz</label>
          <input id="sampleHz" type="number" value="80" min="1" max="2000" />
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="flushMs">Flush ms</label>
          <input id="flushMs" type="number" value="50" min="10" max="500" />
        </div>
        <div class="field">
          <label for="chunkSamples">Chunk size</label>
          <input id="chunkSamples" type="number" value="32" min="2" max="1024" />
        </div>
      </div>

      <div class="row">
        <button class="primary" id="startStream">Start Stream</button>
        <button class="danger" id="stopStream">Stop Stream</button>
      </div>

      <div class="field">
        <label for="channel">Plot channel</label>
        <select id="channel"></select>
      </div>

      <hr style="border: 0; border-top: 1px solid #31465f;" />

      <div class="row">
        <div class="field">
          <label for="vdc">VDC_BUS write</label>
          <input id="vdc" type="number" value="320000" step="1" />
        </div>
        <div class="field" style="align-self: end;">
          <button id="writeVdc">Write VDC</button>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="torque">TORQUE_LOAD write</label>
          <input id="torque" type="number" value="0" step="1" />
        </div>
        <div class="field" style="align-self: end;">
          <button id="writeTorque">Write Torque</button>
        </div>
      </div>

      <p id="status" class="status">Idle</p>
    </aside>

    <section class="card plot-box">
      <div id="plot"></div>
      <div id="metrics" class="metrics"></div>
    </section>
  </div>
`;

const elements = {
  port: document.querySelector("#port") as HTMLSelectElement,
  refreshPorts: document.querySelector("#refreshPorts") as HTMLButtonElement,
  baud: document.querySelector("#baud") as HTMLInputElement,
  sampleHz: document.querySelector("#sampleHz") as HTMLInputElement,
  flushMs: document.querySelector("#flushMs") as HTMLInputElement,
  chunkSamples: document.querySelector("#chunkSamples") as HTMLInputElement,
  startStream: document.querySelector("#startStream") as HTMLButtonElement,
  stopStream: document.querySelector("#stopStream") as HTMLButtonElement,
  writeVdc: document.querySelector("#writeVdc") as HTMLButtonElement,
  writeTorque: document.querySelector("#writeTorque") as HTMLButtonElement,
  vdc: document.querySelector("#vdc") as HTMLInputElement,
  torque: document.querySelector("#torque") as HTMLInputElement,
  channel: document.querySelector("#channel") as HTMLSelectElement,
  status: document.querySelector("#status") as HTMLParagraphElement,
  plot: document.querySelector("#plot") as HTMLDivElement,
  metrics: document.querySelector("#metrics") as HTMLDivElement,
};

REG_NAMES.forEach((name, index) => {
  const option = document.createElement("option");
  option.value = String(index);
  option.textContent = `${index.toString(16).padStart(2, "0")} - ${name}`;
  elements.channel.append(option);
});
elements.channel.value = "9";

const samples: TelemetrySample[] = [];
const maxBufferSamples = 60_000;
let renderPending = false;
let latestRegs = new Array<number>(10).fill(0);

const initWidth = Math.max(640, elements.plot.clientWidth - 2);
const plot = new uPlot(
  {
    width: initWidth,
    height: 360,
    pxAlign: 0,
    scales: {
      x: { time: false },
    },
    axes: [
      {
        grid: { stroke: "#243850", width: 1 },
        stroke: "#8ea3c0",
      },
      {
        grid: { stroke: "#243850", width: 1 },
        stroke: "#8ea3c0",
      },
    ],
    series: [
      { label: "t [s]" },
      {
        label: "signal",
        stroke: "#3ec7a6",
        width: 1.3,
      },
    ],
  },
  [[], []],
  elements.plot,
);

function setStatus(text: string, kind: "ok" | "error" | "idle" = "idle"): void {
  elements.status.textContent = text;
  elements.status.className = "status";
  if (kind === "ok") {
    elements.status.classList.add("ok");
  }
  if (kind === "error") {
    elements.status.classList.add("error");
  }
}

function renderMetrics(): void {
  elements.metrics.innerHTML = "";
  for (let i = 0; i < REG_NAMES.length; i++) {
    const card = document.createElement("div");
    card.className = "metric";

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = `${i.toString(16).padStart(2, "0")} ${REG_NAMES[i]}`;

    const value = document.createElement("div");
    value.className = "value";
    value.textContent = String(latestRegs[i] ?? 0);

    card.append(name, value);
    elements.metrics.append(card);
  }
}

function decimateMinMax(data: TelemetrySample[], channelIdx: number, maxPoints: number): [number[], number[]] {
  if (data.length === 0) {
    return [[], []];
  }

  if (data.length <= maxPoints) {
    const x = data.map((d) => d.t_ms * 0.001);
    const y = data.map((d) => d.regs[channelIdx] ?? 0);
    return [x, y];
  }

  const bucketCount = Math.max(2, Math.floor(maxPoints / 2));
  const bucketSize = data.length / bucketCount;

  const x: number[] = [];
  const y: number[] = [];

  for (let bucket = 0; bucket < bucketCount; bucket++) {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.min(data.length, Math.floor((bucket + 1) * bucketSize));

    if (end <= start) {
      continue;
    }

    let minIdx = start;
    let maxIdx = start;
    let minVal = data[start].regs[channelIdx] ?? 0;
    let maxVal = minVal;

    for (let i = start + 1; i < end; i++) {
      const value = data[i].regs[channelIdx] ?? 0;
      if (value < minVal) {
        minVal = value;
        minIdx = i;
      }
      if (value > maxVal) {
        maxVal = value;
        maxIdx = i;
      }
    }

    if (minIdx <= maxIdx) {
      x.push(data[minIdx].t_ms * 0.001, data[maxIdx].t_ms * 0.001);
      y.push(minVal, maxVal);
    } else {
      x.push(data[maxIdx].t_ms * 0.001, data[minIdx].t_ms * 0.001);
      y.push(maxVal, minVal);
    }
  }

  return [x, y];
}

function scheduleRender(): void {
  if (renderPending) {
    return;
  }
  renderPending = true;

  requestAnimationFrame(() => {
    renderPending = false;
    const selected = Number(elements.channel.value);
    const width = Math.max(640, elements.plot.clientWidth - 2);
    const maxPlotPoints = Math.max(240, width);

    const [x, y] = decimateMinMax(samples, selected, maxPlotPoints);
    plot.setData([x, y]);

    renderMetrics();
  });
}

async function refreshPorts(): Promise<void> {
  try {
    const ports = await invoke<string[]>("list_serial_ports");
    elements.port.innerHTML = "";
    if (ports.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No ports found";
      elements.port.append(option);
      setStatus("No serial ports found", "error");
      return;
    }

    ports.forEach((port: string) => {
      const option = document.createElement("option");
      option.value = port;
      option.textContent = port;
      elements.port.append(option);
    });

    setStatus(`Found ${ports.length} ports`, "ok");
  } catch (error) {
    setStatus(`Failed to list ports: ${String(error)}`, "error");
  }
}

function getStreamConfig(): StreamConfig {
  return {
    portName: elements.port.value,
    baudRate: Number(elements.baud.value),
    sampleHz: Number(elements.sampleHz.value),
    flushMs: Number(elements.flushMs.value),
    chunkSamples: Number(elements.chunkSamples.value),
    dataWidth: 42,
  };
}

elements.refreshPorts.addEventListener("click", () => {
  void refreshPorts();
});

elements.channel.addEventListener("change", () => {
  scheduleRender();
});

elements.startStream.addEventListener("click", async () => {
  const config = getStreamConfig();
  if (!config.portName) {
    setStatus("Select a serial port before starting", "error");
    return;
  }

  try {
    await invoke("start_stream", { config });
    setStatus("Streaming started", "ok");
  } catch (error) {
    setStatus(`Could not start stream: ${String(error)}`, "error");
  }
});

elements.stopStream.addEventListener("click", async () => {
  try {
    await invoke("stop_stream");
    setStatus("Streaming stopped", "ok");
  } catch (error) {
    setStatus(`Could not stop stream: ${String(error)}`, "error");
  }
});

elements.writeVdc.addEventListener("click", async () => {
  try {
    await invoke("write_vdc_bus", {
      port_name: elements.port.value,
      baud_rate: Number(elements.baud.value),
      value: Number(elements.vdc.value),
      data_width: 42,
    });
    setStatus("VDC_BUS updated", "ok");
  } catch (error) {
    setStatus(`Write VDC failed: ${String(error)}`, "error");
  }
});

elements.writeTorque.addEventListener("click", async () => {
  try {
    await invoke("write_torque_load", {
      port_name: elements.port.value,
      baud_rate: Number(elements.baud.value),
      value: Number(elements.torque.value),
      data_width: 42,
    });
    setStatus("TORQUE_LOAD updated", "ok");
  } catch (error) {
    setStatus(`Write torque failed: ${String(error)}`, "error");
  }
});

window.addEventListener("resize", () => {
  const width = Math.max(640, elements.plot.clientWidth - 2);
  plot.setSize({ width, height: 360 });
  scheduleRender();
});

void listen<TelemetrySample[]>("telemetry-chunk", (event: { payload: TelemetrySample[] }) => {
  if (!Array.isArray(event.payload)) {
    return;
  }

  for (const sample of event.payload) {
    if (!sample || !Array.isArray(sample.regs) || sample.regs.length < 10) {
      continue;
    }
    samples.push(sample);
    latestRegs = sample.regs.slice(0, 10);
  }

  if (samples.length > maxBufferSamples) {
    samples.splice(0, samples.length - maxBufferSamples);
  }

  scheduleRender();
});

void listen<string>("stream-error", (event: { payload: string }) => {
  setStatus(event.payload, "error");
});

void refreshPorts();
renderMetrics();
