#!/usr/bin/env python3
"""Validate HIL FPGA telemetry against the induction-motor C model using captured PWM.

The script parses a .hilbin capture, compiles a small temporary C runner against
extras/induction-motor-model/src/IM_Model.c, replays the captured NPC PWM states
at the solver time step, and reports error metrics at telemetry timestamps.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUNNER_C = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "IM_Model.h"

typedef struct { float t, ia, ib, fa, fb, speed, tl; } Telem;
typedef struct { float t; int8_t a, b, c; uint8_t pad; } Pwm;
typedef struct { double valpha, vbeta, v0; } IM_InternalInputs_t;
typedef struct {
    double is_alpha, is_beta, ir_alpha, ir_beta;
    double fluxR_alpha, fluxR_beta;
    double wr, wm, Te, isd, isq, fluxRd, angleR;
} IM_States_t;
typedef struct { IM_InternalInputs_t inp; IM_States_t out; } IM_PrivateData_t;

static uint32_t rd_u32(const unsigned char *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static double rms(double s2, uint64_t n) { return n ? sqrt(s2 / (double)n) : 0.0; }
static double level_rtl(int8_t s, double prev, int mode) {
    (void)prev;
    if (s == 3 || s == 1) return 1.0;
    if (s == 12 || s == -1) return -1.0;
    if (mode == 2) {
        if (s == 2) return 0.5;   // dead-time from POS -> +Vdc/4
        if (s == 4) return -0.5;  // dead-time from NEG -> -Vdc/4
    }
    return 0.0;
}
static double level_hold_invalid(int8_t s, double prev) { if (s == 3 || s == 1) return 1.0; if (s == 12 || s == -1) return -1.0; if (s == 6 || s == 0) return 0.0; return prev; }

int main(int argc, char **argv) {
    if (argc < 13) {
        fprintf(stderr, "usage: %s run.hilbin vdc skip_s ts rs rr lm ls lr j npp npc_mode\n", argv[0]);
        return 2;
    }
    const char *path = argv[1];
    double vdc = atof(argv[2]);
    double skip_s = atof(argv[3]);
    double ts = atof(argv[4]);
    int npc_mode = atoi(argv[12]);

    FILE *f = fopen(path, "rb"); if (!f) { perror("open"); return 1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); rewind(f);
    unsigned char *buf = malloc((size_t)sz); if (!buf) { fprintf(stderr, "oom\n"); return 1; }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) { perror("read"); return 1; } fclose(f);
    if (sz < 16 || memcmp(buf, "HILDATA", 7) != 0) { fprintf(stderr, "bad hilbin\n"); return 1; }

    uint32_t json_len = rd_u32(buf + 8); size_t off = (12u + json_len + 7u) & ~7u;
    if (off + 4 > (size_t)sz) { fprintf(stderr, "truncated telem count\n"); return 1; }
    uint32_t tn = rd_u32(buf + off); off += 4;
    if (off + (size_t)tn * sizeof(Telem) + 4 > (size_t)sz) { fprintf(stderr, "truncated telem\n"); return 1; }
    Telem *telem = (Telem *)(buf + off); off += (size_t)tn * sizeof(Telem);
    uint32_t pn = rd_u32(buf + off); off += 4;
    if (off + (size_t)pn * sizeof(Pwm) > (size_t)sz) { fprintf(stderr, "truncated pwm\n"); return 1; }
    Pwm *pwm = (Pwm *)(buf + off);
    if (tn == 0 || pn == 0) { fprintf(stderr, "empty telem/pwm\n"); return 1; }

    IM_Model_t m; IM_Init(&m);
    IMParams p = {0};
    p.Rs = atof(argv[5]); p.Rr = atof(argv[6]); p.Lm = atof(argv[7]); p.Ls = atof(argv[8]);
    p.Lr = atof(argv[9]); p.J = atof(argv[10]); p.npp = atof(argv[11]); p.Ts = ts;
    IM_SetParams(&m, &p); IM_TypeModel(&m, MODEL_B2);

    uint32_t pi = 0, ti = 0; double t = 0.0, tl = telem[0].tl;
    int8_t a = pwm[0].a, b = pwm[0].b, c = pwm[0].c;
    double la = 0.0, lb = 0.0, lc = 0.0;
    double se[5] = {0}, sae[5] = {0}, sy[5] = {0}, sy2[5] = {0};
    uint64_t cnt = 0, steps = 0; double last_ref[5] = {0}; double svf_lp[5] = {0}, svf_bp[5] = {0};
    double t_end = telem[tn - 1].t;

    while (t <= t_end + ts && ti < tn) {
        while (pi + 1 < pn && pwm[pi + 1].t <= t) { pi++; a = pwm[pi].a; b = pwm[pi].b; c = pwm[pi].c; }
        while (ti + 1 < tn && telem[ti + 1].t <= t) { ti++; tl = telem[ti].tl; }
        if (npc_mode == 1) {
            la = level_hold_invalid(a, la); lb = level_hold_invalid(b, lb); lc = level_hold_invalid(c, lc);
        } else {
            la = level_rtl(a, la, npc_mode); lb = level_rtl(b, lb, npc_mode); lc = level_rtl(c, lc, npc_mode);
        }
        IMInputs in = { la * vdc * 0.5, lb * vdc * 0.5, lc * vdc * 0.5, tl };
        IM_SetInputs(&m, &in); IM_SimulateStep(&m);
        IM_PrivateData_t *priv = (IM_PrivateData_t *)m.priv;
        double raw_ref[5] = {priv->out.is_alpha, priv->out.is_beta, priv->out.fluxR_alpha, priv->out.fluxR_beta, priv->out.wm};
        for (int fk = 0; fk < 5; fk++) {
            double lp_old = svf_lp[fk], bp_old = svf_bp[fk];
            svf_lp[fk] = lp_old + bp_old / 32.0;
            svf_bp[fk] = bp_old + raw_ref[fk] / 32.0 - lp_old / 32.0 - (1.4375 * bp_old) / 32.0;
            last_ref[fk] = svf_lp[fk];
        }
        while (ti < tn && telem[ti].t <= t) {
            double y[5] = { telem[ti].ia, telem[ti].ib, telem[ti].fa, telem[ti].fb, telem[ti].speed };
            if (telem[ti].t >= skip_s) {
                for (int k = 0; k < 5; k++) { double e = y[k] - last_ref[k]; se[k] += e * e; sae[k] += fabs(e); sy[k] += y[k]; sy2[k] += y[k] * y[k]; }
                cnt++;
            }
            ti++;
        }
        t += ts; steps++;
    }

    const char *names[5] = {"ia", "ib", "fa", "fb", "speed"};
    printf("hilbin=%s\n", path);
    printf("telem=%u pwm=%u steps=%llu ts=%.12g vdc=%.6g skip=%.6g model=B2 npc_mode=%s\n", tn, pn, (unsigned long long)steps, ts, vdc, skip_s, npc_mode == 1 ? "hold" : (npc_mode == 2 ? "dead-mid" : "zero"));
    for (int k = 0; k < 5; k++) {
        double mean = sy[k] / (double)cnt; double var = sy2[k] / (double)cnt - mean * mean; if (var < 0) var = 0;
        double nrmse = rms(se[k], cnt) / fmax(sqrt(var), 1e-12);
        printf("%-5s mae=%.9g rmse=%.9g nrmse=%.9g mean=%.9g\n", names[k], sae[k]/(double)cnt, rms(se[k], cnt), nrmse, mean);
    }
    printf("last_ref ia=%.9g ib=%.9g fa=%.9g fb=%.9g speed=%.9g\n", last_ref[0], last_ref[1], last_ref[2], last_ref[3], last_ref[4]);
    printf("last_fpga ia=%.9g ib=%.9g fa=%.9g fb=%.9g speed=%.9g\n", telem[tn-1].ia, telem[tn-1].ib, telem[tn-1].fa, telem[tn-1].fb, telem[tn-1].speed);
    free(buf); return 0;
}
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hilbin", type=Path)
    ap.add_argument("--vdc", type=float, default=1240.0)
    ap.add_argument("--skip", type=float, default=0.2)
    ap.add_argument("--ts", type=float, default=26.0 / 200_000_000.0)
    ap.add_argument("--rs", type=float, default=0.4396)
    ap.add_argument("--rr", type=float, default=0.2826)
    ap.add_argument("--lm", type=float, default=109.9442e-3)
    ap.add_argument("--ls", type=float, default=3.1364e-3)
    ap.add_argument("--lr", type=float, default=6.3264e-3)
    ap.add_argument("--j", type=float, default=0.4)
    ap.add_argument("--npp", type=float, default=2.0)
    ap.add_argument("--npc-mode", choices=["dead-mid", "zero", "hold"], default="dead-mid", help="NPC gate-state voltage mapping used for replay")
    ap.add_argument("--hold-invalid-npc", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    src_dir = root / "extras" / "induction-motor-model" / "src"
    model_c = src_dir / "IM_Model.c"
    if not model_c.exists():
        raise SystemExit(f"missing {model_c}")

    with tempfile.TemporaryDirectory(prefix="hil_pwm_validate_") as td:
        td_path = Path(td)
        c_path = td_path / "runner.c"
        exe = td_path / "runner"
        c_path.write_text(RUNNER_C)
        cmd = [
            os.environ.get("CC", "gcc"), "-O3", "-I", str(src_dir),
            str(c_path), str(model_c), "-lm", "-o", str(exe),
        ]
        subprocess.run(cmd, check=True)
        run = [
            str(exe), str(args.hilbin), str(args.vdc), str(args.skip), str(args.ts),
            str(args.rs), str(args.rr), str(args.lm), str(args.ls), str(args.lr),
            str(args.j), str(args.npp), "1" if args.hold_invalid_npc or args.npc_mode == "hold" else ("2" if args.npc_mode == "dead-mid" else "0"),
        ]
        subprocess.run(run, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
