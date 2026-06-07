"""L4 validation — C reference model vs the real FPGA.

Drives the EBAZ4205 over UDP with a V/F profile, captures the live telemetry
stream (the DMA/UDP path), then runs the C reference model with the *same*
stimulus and overlays both trajectories.

Conceptual note
---------------
The FPGA solver is fed PWM-switched NPC voltages (0, ±Vdc/2) while the C model
is fed the ideal V/F sinusoid. So the FPGA current carries real PWM ripple that
the ideal C trajectory does not. This is expected, not solver error. We therefore
validate at the *macroscopic* level: the fundamental current (amplitude / phase /
frequency), the flux build-up and the speed ramp. Metrics are computed both on the
raw signal and on a low-pass-filtered copy (ripple removed) so the numbers reflect
the solver, not the carrier.

A bit-exact, step-by-step comparison is only possible in the cocotb VHDL sim
(which sees every 130 ns solver step); on real hardware the telemetry is decimated
to ~10 kHz, so per-step equivalence cannot be observed here.

Usage (from verification/cocotb/):
    # capture 3 s, analyse both the startup ramp and the steady state
    uv run python scripts/fpga_vs_c.py --board-ip 192.168.15.8 --freq 60 --duration 3.0

    # fixed low modulation index, 2 s
    uv run python scripts/fpga_vs_c.py --freq 30 --duration 2.0

The gateway (hil-gateway) must be stopped first — it holds UDP port 5006.
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel

# ── Protocol constants (mirror telemetry.h / main.c) ────────────────────────
CMD_PORT   = 5005
TELEM_PORT = 5006
TELEM_SYNC = bytes((0x48, 0x49, 0x4C, 0x5A))  # "HILZ"
TELEM_BURST = 32
SAMPLE_BYTES = 26                              # u32 t_cycles + u16 epoch + 5×f32
HDR_SIZE = 10
HW_CLOCK_HZ = 100_000_000.0                    # pwm_cap_time runs at 100 MHz
SOLVER_TS = 26.0 / 200_000_000.0               # 130 ns — matches TIM_Solver
VF_TICK_TS = 0.001                             # vf_tick runs at 1 kHz (ZOH on refs)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


# ── CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) ───────────────────────────
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


# ── Stimulus: exact replica of vf_ctrl.c::vf_tick ───────────────────────────
class VFStimulus:
    """Reproduces the board's open-loop V/F law bit-for-bit (sin, ramp to target,
    voltage scaled by base_freq, peak = v_pu·Vdc/2). Reference updated at 1 kHz
    with zero-order hold between ticks, exactly like the FPGA carrier update."""

    def __init__(self, freq, base_freq, vdc, max_v_pu, accel_time):
        self.f_target = max(0.0, freq)
        self.base_freq = base_freq if base_freq > 0 else 60.0
        self.vpk = vdc / 2.0  # phase peak at v_pu = 1.0
        self.max_v_pu = min(max(max_v_pu, 0.0), 1.0)
        self.accel = (self.base_freq / accel_time) if accel_time > 0 else 1e6
        self.f_current = 0.0
        self.theta = 0.0

    def tick(self):
        """Advance one 1 kHz tick, return (va, vb, vc) held for the next ms."""
        step = self.accel * VF_TICK_TS
        if self.f_current < self.f_target:
            self.f_current = min(self.f_current + step, self.f_target)
        elif self.f_current > self.f_target:
            self.f_current = max(self.f_current - step, self.f_target)

        v_pu = self.max_v_pu * (self.f_current / self.base_freq)
        v_pu = min(v_pu, self.max_v_pu)
        v_amp = v_pu * self.vpk

        self.theta += 2.0 * math.pi * self.f_current * VF_TICK_TS
        if self.theta > 2.0 * math.pi:
            self.theta -= 2.0 * math.pi

        va = v_amp * math.sin(self.theta)
        vb = v_amp * math.sin(self.theta - 2.0 * math.pi / 3.0)
        vc = v_amp * math.sin(self.theta + 2.0 * math.pi / 3.0)
        return va, vb, vc


# ── Board control ───────────────────────────────────────────────────────────
def detect_my_ip(board_ip: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((board_ip, CMD_PORT))
    ip = s.getsockname()[0]
    s.close()
    return ip


def send_cmd(board_ip: str, obj: str, wait=0.3) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)
    s.sendto(obj.encode(), (board_ip, CMD_PORT))
    try:
        s.recvfrom(2048)
    except socket.timeout:
        pass
    s.close()
    time.sleep(wait)


# ── Live telemetry capture ──────────────────────────────────────────────────
def capture_fpga(board_ip, my_ip, freq, base_freq, vdc, max_v_pu, accel, duration):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rx.bind(("", TELEM_PORT))
    except OSError as e:
        raise SystemExit(
            f"Cannot bind UDP {TELEM_PORT} ({e}). Stop the hil-gateway first "
            f"(it holds this port): kill it in its terminal, then re-run."
        )
    rx.settimeout(0.5)

    # Punch a hole so stateful firewalls/NAT allow the reverse telemetry stream:
    # send from our :5006 socket to board:5006, exactly like the gateway does
    # (receiver.go Punch). Without this the board's sendto succeeds but the host
    # firewall drops the inbound datagrams.
    def punch():
        rx.sendto(b"HIL_TELEM_PUNCH", (board_ip, TELEM_PORT))

    # Fresh run: stop → configure → run (epoch increments, counter resets to 0)
    punch()
    send_cmd(board_ip, '{"cmd":"stop"}', wait=0.5)
    cfg = (
        '{"cmd":"set","freq_hz":%g,"base_freq_hz":%g,"vdc_v":%g,'
        '"max_v_pu":%g,"accel_time_s":%g,"telem_dst":"%s"}'
        % (freq, base_freq, vdc, max_v_pu, accel, my_ip)
    )
    send_cmd(board_ip, cfg, wait=0.3)
    punch()
    send_cmd(board_ip, '{"cmd":"run"}', wait=0.0)

    t0 = time.time()
    last_punch = t0
    last_rx = t0
    recs = []  # (t_cycles_raw, epoch, ia, ib, flux_a, flux_b, speed)
    bad_crc = 0
    while time.time() - t0 < duration + 0.5:
        now = time.time()
        if now - last_punch > 0.5:        # keep the conntrack hole open
            punch()
            last_punch = now
        try:
            data, _ = rx.recvfrom(2048)
            last_rx = now
        except socket.timeout:
            if now - last_rx > 2.0:       # give up only after a real stall
                break
            continue
        if len(data) < HDR_SIZE + 2 or data[:4] != TELEM_SYNC:
            continue
        n = data[9]
        need = HDR_SIZE + n * SAMPLE_BYTES + 2
        if len(data) < need:
            continue
        crc_rx = data[need - 2] | (data[need - 1] << 8)
        if crc16(data[: need - 2]) != crc_rx:
            bad_crc += 1
            continue
        pos = HDR_SIZE
        for _ in range(n):
            tc, ep = struct.unpack_from("<IH", data, pos)
            ia, ib, fa, fb, sp = struct.unpack_from("<fffff", data, pos + 6)
            recs.append((tc, ep, ia, ib, fa, fb, sp))
            pos += SAMPLE_BYTES

    send_cmd(board_ip, '{"cmd":"stop"}', wait=0.0)
    rx.close()
    if not recs:
        raise SystemExit("No telemetry received. Is the board running and reachable?")

    arr = np.array(recs, dtype=np.float64)
    epoch = arr[:, 1].astype(np.int64)
    # Keep only the dominant (latest) epoch = this run
    run_epoch = np.bincount(epoch - epoch.min()).argmax() + epoch.min()
    m = epoch == run_epoch
    arr = arr[m]

    # Reconstruct absolute time from the 32-bit run-local counter (handle wrap)
    raw = arr[:, 0].astype(np.uint32).astype(np.int64)
    t = np.empty(len(raw))
    off = 0
    prev = None
    for i, r in enumerate(raw):
        if prev is not None and r < prev and prev - r > (1 << 31):
            off += 1 << 32
        prev = r
        t[i] = (off + r) / HW_CLOCK_HZ
    t -= t[0]

    order = np.argsort(t, kind="stable")
    t = t[order]
    out = {
        "t": t,
        "ia": arr[order, 2], "ib": arr[order, 3],
        "flux_a": arr[order, 4], "flux_b": arr[order, 5],
        "speed": arr[order, 6],
        "bad_crc": bad_crc,
    }
    return out


# ── C reference model with the identical stimulus ───────────────────────────
def run_c_model(freq, base_freq, vdc, max_v_pu, accel, duration, params):
    model = InductionMotorReferenceModel(params=params, backend="auto")
    vf = VFStimulus(freq, base_freq, vdc, max_v_pu, accel)

    sub = max(1, round(VF_TICK_TS / SOLVER_TS))     # solver steps per 1 kHz tick
    store_every = max(1, round((1.0 / 10_000.0) / SOLVER_TS))  # decimate → ~10 kHz
    n_ticks = int(round(duration / VF_TICK_TS))

    T, IA, IB, FA, FB, SP = [], [], [], [], [], []
    t = 0.0
    k = 0
    for _ in range(n_ticks):
        va, vb, vc = vf.tick()
        for _ in range(sub):
            st = model.step(va, vb, vc, 0.0)
            if k % store_every == 0:
                T.append(t); IA.append(st.i_alpha); IB.append(st.i_beta)
                FA.append(st.flux_alpha); FB.append(st.flux_beta); SP.append(st.speed_mech)
            t += SOLVER_TS
            k += 1
    return {
        "t": np.array(T), "ia": np.array(IA), "ib": np.array(IB),
        "flux_a": np.array(FA), "flux_b": np.array(FB), "speed": np.array(SP),
        "backend": model.backend_name,
    }


# ── Metrics ─────────────────────────────────────────────────────────────────
def lowpass(x, t, fc=300.0):
    """Simple one-pole IIR low-pass to strip PWM ripple before comparing."""
    if len(t) < 2:
        return x.copy()
    dt = np.median(np.diff(t))
    a = dt / (dt + 1.0 / (2.0 * math.pi * fc))
    y = np.empty_like(x)
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = y[i - 1] + a * (x[i] - y[i - 1])
    return y


def nrmse(ref, dut):
    rng = ref.max() - ref.min()
    if rng <= 1e-12:
        return float("nan")
    return float(np.sqrt(np.mean((dut - ref) ** 2)) / rng) * 100.0


def mae(ref, dut):
    return float(np.mean(np.abs(dut - ref)))


def fundamental_amp(x):
    """Peak of the fundamental ≈ sqrt(2)·RMS of the AC component."""
    ac = x - np.mean(x)
    return float(np.sqrt(2.0) * np.sqrt(np.mean(ac ** 2)))


def compare(fpga, cmod, label, t_lo, t_hi):
    mf = (fpga["t"] >= t_lo) & (fpga["t"] <= t_hi)
    tf = fpga["t"][mf]
    if tf.size < 8:
        print(f"  [{label}] janela vazia ({t_lo:.3f}–{t_hi:.3f}s)")
        return
    print(f"\n  ── {label}  ({t_lo:.3f}–{t_hi:.3f}s, {tf.size} amostras FPGA) ──")
    for key, name, metric, unit in (
        ("ia", "iα", "nrmse", "%"), ("ib", "iβ", "nrmse", "%"),
        ("flux_a", "ψα", "mae", "Wb"), ("flux_b", "ψβ", "mae", "Wb"),
        ("speed", "ωm", "mae", "rad/s"),
    ):
        c = np.interp(tf, cmod["t"], cmod[key])
        f_raw = fpga[key][mf]
        f_filt = lowpass(f_raw, tf)
        if metric == "nrmse":
            v_raw, v_filt = nrmse(c, f_raw), nrmse(c, f_filt)
            print(f"    {name:3s} NRMSE: raw={v_raw:6.2f}{unit}  filtrado={v_filt:6.2f}{unit}")
        else:
            v_raw, v_filt = mae(c, f_raw), mae(c, f_filt)
            print(f"    {name:3s} MAE:   raw={v_raw:.4g}{unit}  filtrado={v_filt:.4g}{unit}")
    # Steady-state fundamental amplitude (ia) + mean speed
    a_f = fundamental_amp(fpga["ia"][mf])
    a_c = fundamental_amp(np.interp(tf, cmod["t"], cmod["ia"]))
    print(f"    |iα| fundamental: FPGA={a_f:.3f} A  C={a_c:.3f} A  "
          f"(Δ={100*(a_f-a_c)/max(a_c,1e-9):+.1f}%)")
    print(f"    ωm média:        FPGA={np.mean(fpga['speed'][mf]):.2f}  "
          f"C={np.mean(np.interp(tf, cmod['t'], cmod['speed'])):.2f} rad/s")


# ── Plot (optional, Plotly) ─────────────────────────────────────────────────
def make_report(fpga, cmod, out_html):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  (plotly não instalado — pulando HTML; métricas acima bastam)")
        return
    sig = [("ia", "iα [A]"), ("ib", "iβ [A]"),
           ("flux_a", "ψα [Wb]"), ("speed", "ωm [rad/s]")]
    fig = make_subplots(rows=len(sig), cols=1, shared_xaxes=True,
                        subplot_titles=[s[1] for s in sig])
    for r, (k, _) in enumerate(sig, 1):
        fig.add_trace(go.Scatter(x=cmod["t"], y=cmod[k], name=f"C {k}",
                                 line=dict(width=1.5)), row=r, col=1)
        fig.add_trace(go.Scatter(x=fpga["t"], y=fpga[k], name=f"FPGA {k}",
                                 mode="markers", marker=dict(size=2, opacity=0.5)),
                      row=r, col=1)
    fig.update_layout(height=240 * len(sig), title="C reference (linha) vs FPGA (pontos)",
                      template="plotly_dark")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_html))
    print(f"\n  Relatório: {out_html}")


def main():
    ap = argparse.ArgumentParser(description="Validate the FPGA against the C reference model.")
    ap.add_argument("--board-ip", default="192.168.15.8")
    ap.add_argument("--my-ip", default=None, help="auto-detected if omitted")
    ap.add_argument("--freq", type=float, default=60.0, help="target electrical freq [Hz]")
    ap.add_argument("--base-freq", type=float, default=60.0)
    ap.add_argument("--vdc", type=float, default=1240.0)
    ap.add_argument("--max-v-pu", type=float, default=1.0)
    ap.add_argument("--accel", type=float, default=1.0, help="accel_time_s")
    ap.add_argument("--duration", type=float, default=3.0)
    ap.add_argument("--scenario", choices=["steady", "ramp", "both"], default="both")
    ap.add_argument("--out", default=str(REPORTS_DIR / "fpga_vs_c.html"))
    args = ap.parse_args()

    my_ip = args.my_ip or detect_my_ip(args.board_ip)
    print(f"Board {args.board_ip} → telemetria para {my_ip}:{TELEM_PORT}")
    print(f"V/F: freq={args.freq} base={args.base_freq} vdc={args.vdc} "
          f"max_v_pu={args.max_v_pu} accel={args.accel}s  dur={args.duration}s")

    print("\nCapturando FPGA ao vivo...")
    fpga = capture_fpga(args.board_ip, my_ip, args.freq, args.base_freq,
                        args.vdc, args.max_v_pu, args.accel, args.duration)
    print(f"  {fpga['ia'].size} amostras, span {fpga['t'][-1]:.3f}s, "
          f"CRC inválidos={fpga['bad_crc']}")

    print("Rodando modelo C (mesmo estímulo, Ts=130ns)...")
    params = IMPhysicalParams.defaults()
    cmod = run_c_model(args.freq, args.base_freq, args.vdc, args.max_v_pu,
                       args.accel, args.duration, params)
    print(f"  backend={cmod['backend']}, {cmod['ia'].size} amostras")
    if cmod["backend"] != "c":
        print("  AVISO: usando fallback Python (modelo C não compilou) — "
              "ainda válido, mas não é o IM_Model.c.")

    tend = min(fpga["t"][-1], cmod["t"][-1])
    ramp_end = min(args.accel * (args.freq / args.base_freq) + 0.3, tend)
    if args.scenario in ("ramp", "both"):
        compare(fpga, cmod, "PARTIDA / RAMPA", 0.0, ramp_end)
    if args.scenario in ("steady", "both"):
        compare(fpga, cmod, "REGIME PERMANENTE", max(0.0, tend - 0.2), tend)

    make_report(fpga, cmod, Path(args.out))


if __name__ == "__main__":
    main()
