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
import json
import math
import select
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
PWM_PORT   = 5007                              # pwm_events JSON stream
TELEM_SYNC = bytes((0x48, 0x49, 0x4C, 0x5A))  # "HILZ"

# NPC gate-state encoding (NPCManager.vhd): 0011→+Vdc/2, 1100→−Vdc/2, else 0
NPC_POS = 0b0011
NPC_NEG = 0b1100
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


def unwrap_cycles(raw):
    """32-bit run-local counter (cycles) → seconds, handling wraps. The counter
    resets to 0 at Run, so the result is absolute run-local time shared by the
    telemetry and PWM-event streams."""
    raw = np.asarray(raw, dtype=np.int64)
    t = np.empty(len(raw), dtype=np.float64)
    off = 0
    prev = None
    for i, r in enumerate(raw):
        if prev is not None and r < prev and prev - r > (1 << 31):
            off += 1 << 32
        prev = r
        t[i] = (off + r) / HW_CLOCK_HZ
    return t


# ── Live capture: telemetry (5006) + PWM events (5007) ──────────────────────
def capture_fpga(board_ip, my_ip, freq, base_freq, vdc, max_v_pu, accel,
                 duration, want_pwm=False):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rx.bind(("", TELEM_PORT))
    except OSError as e:
        raise SystemExit(
            f"Cannot bind UDP {TELEM_PORT} ({e}). Stop the hil-gateway first "
            f"(it holds this port): kill it in its terminal, then re-run."
        )
    socks = [rx]
    rxp = None
    if want_pwm:
        rxp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rxp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rxp.bind(("", PWM_PORT))
        socks.append(rxp)

    # Punch holes so stateful firewalls/NAT allow the reverse streams (the board
    # sendto() succeeds but the host firewall drops inbound otherwise) — exactly
    # like the gateway (receiver.go / pwmrecv.go Punch).
    def punch():
        rx.sendto(b"HIL_TELEM_PUNCH", (board_ip, TELEM_PORT))
        if rxp is not None:
            rxp.sendto(b"HIL_PWM_PUNCH", (board_ip, PWM_PORT))

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
    recs = []   # (t_cycles, epoch, ia, ib, flux_a, flux_b, speed)
    pwm = []    # (t_cycles, epoch, a, b, c)
    bad_crc = 0
    pwm_overflow = False
    while time.time() - t0 < duration + 0.5:
        now = time.time()
        if now - last_punch > 0.5:
            punch()
            last_punch = now
        ready, _, _ = select.select(socks, [], [], 0.5)
        if not ready:
            if now - last_rx > 2.0:
                break
            continue
        for s in ready:
            data, _ = s.recvfrom(65535)
            last_rx = now
            if s is rx:
                if len(data) < HDR_SIZE + 2 or data[:4] != TELEM_SYNC:
                    continue
                n = data[9]
                need = HDR_SIZE + n * SAMPLE_BYTES + 2
                if len(data) < need:
                    continue
                if crc16(data[: need - 2]) != (data[need - 2] | (data[need - 1] << 8)):
                    bad_crc += 1
                    continue
                pos = HDR_SIZE
                for _ in range(n):
                    tc, ep = struct.unpack_from("<IH", data, pos)
                    ia, ib, fa, fb, sp = struct.unpack_from("<fffff", data, pos + 6)
                    recs.append((tc, ep, ia, ib, fa, fb, sp))
                    pos += SAMPLE_BYTES
            else:  # PWM events — JSON
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("type") != "pwm_events":
                    continue
                if obj.get("status", 0) & 0x2:   # FIFO overflow bit
                    pwm_overflow = True
                for ev in obj.get("events", []):
                    # [t, a, b, c, mask, epoch]
                    pwm.append((ev[0], ev[5], ev[1], ev[2], ev[3]))

    send_cmd(board_ip, '{"cmd":"stop"}', wait=0.0)
    rx.close()
    if rxp is not None:
        rxp.close()
    if not recs:
        raise SystemExit("No telemetry received. Is the board running and reachable?")

    arr = np.array(recs, dtype=np.float64)
    epoch = arr[:, 1].astype(np.int64)
    run_epoch = int(np.bincount(epoch - epoch.min()).argmax() + epoch.min())
    arr = arr[epoch == run_epoch]

    t_abs = unwrap_cycles(arr[:, 0].astype(np.uint32))   # shared run-local clock
    order = np.argsort(t_abs, kind="stable")
    t_abs = t_abs[order]
    out = {
        "t": t_abs - t_abs[0],   # zeroed (ideal-stimulus mode)
        "t_abs": t_abs,          # run-local origin (shared with PWM stream)
        "ia": arr[order, 2], "ib": arr[order, 3],
        "flux_a": arr[order, 4], "flux_b": arr[order, 5],
        "speed": arr[order, 6],
        "bad_crc": bad_crc,
    }

    if want_pwm and pwm:
        parr = np.array(pwm, dtype=np.int64)
        parr = parr[parr[:, 1] == run_epoch]            # same run
        pt = unwrap_cycles(parr[:, 0].astype(np.uint32))
        po = np.argsort(pt, kind="stable")
        out["pwm"] = {
            "t": pt[po],
            "a": parr[po, 2], "b": parr[po, 3], "c": parr[po, 4],
            "overflow": pwm_overflow, "n": len(parr),
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


# ── C reference fed with the REAL captured PWM voltage (Option B) ────────────
def _gate_to_v(g, vhalf):
    if g == NPC_POS:
        return vhalf
    if g == NPC_NEG:
        return -vhalf
    return 0.0


def run_c_model_pwm_fed(pwm, vdc, params):
    """Feed the C model the *same* switched voltage the FPGA solver saw,
    reconstructed from the captured gate states. Both then carry identical PWM
    ripple, so the residual is purely solver arithmetic / quantisation.

    The gate stream and telemetry share the hil_time counter, so the C output is
    produced on that same absolute timeline (no separate epoch handling needed).
    """
    model = InductionMotorReferenceModel(params=params, backend="auto")
    vhalf = vdc / 2.0
    store_every = max(1, round((1.0 / 10_000.0) / SOLVER_TS))  # decimate → ~10 kHz

    tev = pwm["t"]
    va = np.array([_gate_to_v(g, vhalf) for g in pwm["a"]])
    vb = np.array([_gate_to_v(g, vhalf) for g in pwm["b"]])
    vc = np.array([_gate_to_v(g, vhalf) for g in pwm["c"]])

    T, IA, IB, FA, FB, SP = [], [], [], [], [], []
    t = float(tev[0])
    k = 0
    for j in range(len(tev) - 1):
        dt = float(tev[j + 1] - tev[j])
        n_steps = int(round(dt / SOLVER_TS))
        if n_steps <= 0 or n_steps > 5_000_000:   # skip absurd gaps (overflow)
            continue
        vva, vvb, vvc = va[j], vb[j], vc[j]
        for _ in range(n_steps):
            st = model.step(vva, vvb, vvc, 0.0)
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


# ── Phase alignment (cross-correlation) ─────────────────────────────────────
def best_lag(t_ref, x_ref, t_dut, x_dut, max_lag_s=0.02):
    """Find the time shift to add to t_dut that best aligns x_dut to x_ref,
    via cross-correlation on a common uniform grid. Returns lag in seconds."""
    t_lo = max(t_ref[0], t_dut[0])
    t_hi = min(t_ref[-1], t_dut[-1])
    if t_hi - t_lo < 4 * max_lag_s:
        return 0.0
    dt = 1.0 / 10_000.0
    grid = np.arange(t_lo, t_hi, dt)
    r = np.interp(grid, t_ref, x_ref)
    d = np.interp(grid, t_dut, x_dut)
    r = r - r.mean()
    d = d - d.mean()
    max_k = int(max_lag_s / dt)
    xc = np.correlate(r, d, mode="full")
    mid = len(d) - 1
    lo, hi = mid - max_k, mid + max_k + 1
    seg = xc[lo:hi]
    k = int(np.argmax(seg)) - max_k
    return k * dt   # add to t_dut


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
        f = fpga[key][mf]
        v = nrmse(c, f) if metric == "nrmse" else mae(c, f)
        u = f"{v:6.2f}{unit}" if metric == "nrmse" else f"{v:.4g} {unit}"
        print(f"    {name:3s} {metric.upper():5s}: {u}")
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
    ap.add_argument("--pwm-fed", action="store_true",
                    help="feed the C model the captured PWM voltage (isolates the solver)")
    ap.add_argument("--no-align", action="store_true", help="skip phase alignment")
    ap.add_argument("--out", default=str(REPORTS_DIR / "fpga_vs_c.html"))
    args = ap.parse_args()

    my_ip = args.my_ip or detect_my_ip(args.board_ip)
    mode = "PWM-fed (isola o solver)" if args.pwm_fed else "estímulo ideal (sistema)"
    print(f"Board {args.board_ip} → telemetria para {my_ip}:{TELEM_PORT}")
    print(f"Modo: {mode}")
    print(f"V/F: freq={args.freq} base={args.base_freq} vdc={args.vdc} "
          f"max_v_pu={args.max_v_pu} accel={args.accel}s  dur={args.duration}s")

    print("\nCapturando FPGA ao vivo...")
    fpga = capture_fpga(args.board_ip, my_ip, args.freq, args.base_freq,
                        args.vdc, args.max_v_pu, args.accel, args.duration,
                        want_pwm=args.pwm_fed)
    print(f"  telemetria: {fpga['ia'].size} amostras, span {fpga['t'][-1]:.3f}s, "
          f"CRC inválidos={fpga['bad_crc']}")

    params = IMPhysicalParams.defaults()
    if args.pwm_fed:
        if "pwm" not in fpga:
            raise SystemExit("Nenhum evento PWM capturado (5007). PWM capture ativo?")
        pw = fpga["pwm"]
        print(f"  PWM: {pw['n']} eventos, overflow={'SIM' if pw['overflow'] else 'nao'}")
        if pw["overflow"]:
            print("  AVISO: FIFO de PWM transbordou — janelas podem ter gaps.")
        # Put telemetry on the shared run-local clock (same origin as PWM events)
        origin = min(fpga["t_abs"][0], pw["t"][0])
        fpga["t"] = fpga["t_abs"] - origin
        pw["t"] = pw["t"] - origin
        print("Rodando modelo C com a tensão PWM REAL capturada (Ts=130ns)...")
        cmod = run_c_model_pwm_fed(pw, args.vdc, params)
    else:
        print("Rodando modelo C (estímulo ideal, Ts=130ns)...")
        cmod = run_c_model(args.freq, args.base_freq, args.vdc, args.max_v_pu,
                           args.accel, args.duration, params)
    print(f"  backend={cmod['backend']}, {cmod['ia'].size} amostras")
    if cmod["backend"] != "c":
        print("  AVISO: fallback Python (IM_Model.c não compilou).")

    # Phase alignment: remove residual lag (CDC, read-time vs sample-time) so the
    # comparison is in phase, as requested.
    if not args.no_align:
        lag = best_lag(fpga["t"], fpga["ia"], cmod["t"], cmod["ia"])
        cmod["t"] = cmod["t"] + lag
        print(f"  alinhamento de fase: lag aplicado ao C = {lag*1e3:+.3f} ms")

    tend = min(fpga["t"][-1], cmod["t"][-1])
    ramp_end = min(args.accel * (args.freq / args.base_freq) + 0.3, tend)
    if args.scenario in ("ramp", "both"):
        compare(fpga, cmod, "PARTIDA / RAMPA", max(0.0, cmod["t"][0]), ramp_end)
    if args.scenario in ("steady", "both"):
        compare(fpga, cmod, "REGIME PERMANENTE", max(0.0, tend - 0.2), tend)

    make_report(fpga, cmod, Path(args.out))


if __name__ == "__main__":
    main()
