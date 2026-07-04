#!/usr/bin/env python3
"""Offline L3 full-stack mock against a Top_HIL simulation CSV.

This is intentionally separate from the cocotb testbench: it reuses a CSV
already exported by `test_top_hil_pwm_replay_l3` and runs an independent C mock
that generates V/F, carrier PWM, gate-driver states and the motor model.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


RUNNER_C = r'''
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "IM_Model.h"

typedef struct { double t, ia, ib, fa, fb, speed; } Row;
typedef struct { double valpha, vbeta, v0; } IM_InternalInputs_t;
typedef struct { double is_alpha,is_beta,ir_alpha,ir_beta,fluxR_alpha,fluxR_beta,wr,wm,Te,isd,isq,fluxRd,angleR; } IM_States_t;
typedef struct { IM_InternalInputs_t inp; IM_States_t out; } IM_PrivateData_t;
typedef struct { int carrier, dir, va_ref, vb_ref, vc_ref, va_lat, vb_lat, vc_lat; } MockPWM;
typedef struct { int state,pwm,ctr,ctr_wait,minw_ok,dt_ok,dt_ok_reg,fault,en_sync; } GateDriver;

enum { G_OFF=0, G_POS=1, G_POS_DEAD=2, G_ZERO=3, G_NEG=4, G_NEG_DEAD=5, G_WAIT=6 };
#define VEC_OFF 0x0
#define VEC_POS 0x3
#define VEC_ZERO_P 0x2
#define VEC_ZERO 0x6
#define VEC_ZERO_N 0x4
#define VEC_NEG 0xC

static double gate_to_v(int g, double vdc) {
    if (g == VEC_POS) return 0.5 * vdc;
    if (g == VEC_NEG) return -0.5 * vdc;
    return 0.0;
}

static int abs_sat(int x, int maxv) {
    long v = x < 0 ? -(long)x : (long)x;
    return v > maxv ? maxv : (int)v;
}

static int npc_state(int ref, int carrier, int cmax) {
    int mag = abs_sat(ref, cmax);
    if (mag > carrier) return ref < 0 ? -1 : 1;
    return 0;
}

static void pwm_init(MockPWM *p, int phase, int cmax) {
    memset(p, 0, sizeof(*p));
    p->dir = 1;
    for (int i = 0; i < phase; i++) {
        if (p->dir) {
            if (p->carrier >= cmax - 1) p->dir = 0;
            else p->carrier++;
        } else {
            if (p->carrier == 0) p->dir = 1;
            else p->carrier--;
        }
    }
}

static int pwm_step(MockPWM *p, int cmax) {
    int valley = 0, ref_edge = 0;
    if (p->dir) {
        if (p->carrier >= cmax - 1) { p->dir = 0; ref_edge = 1; }  /* pico */
        else p->carrier++;
    } else {
        if (p->carrier == 0) { p->dir = 1; valley = 1; ref_edge = 1; }  /* vale */
        else p->carrier--;
    }
    /* LOAD_BOTH_EDGES: trava a referencia em pico E vale (2x/periodo), como
       o NPCManager/vf_irq_driver real faz desde o sincronismo por IRQ real.
       "valley" continua so-no-vale e sem mudanca, pois e o sinal de sync
       usado por gate_step() para o enable do gate driver, que e uma
       preocupacao separada do carregamento da referencia. */
    if (ref_edge) {
        p->va_lat = p->va_ref;
        p->vb_lat = p->vb_ref;
        p->vc_lat = p->vc_ref;
    }
    return valley;
}

static void gate_init(GateDriver *g) {
    memset(g, 0, sizeof(*g));
    g->state = G_OFF;
    g->pwm = VEC_OFF;
}

static int gate_step(GateDriver *g, int cmd, int en, int sync, int min_pulse, int dead_time, int wait_cnt) {
    int old_state = g->state;
    int old_ctr = g->ctr;
    int old_dt_ok = g->dt_ok;
    int dt_ok_redge = old_dt_ok && !g->dt_ok_reg;
    int state_next = g->state, pwm_next = g->pwm, ctr_next = g->ctr;
    int wait_next = g->ctr_wait, minw_next = g->minw_ok, dt_next = g->dt_ok;
    int en_next = g->en_sync;
    if (sync) en_next = en;
    switch (g->state) {
    case G_OFF:
        pwm_next = VEC_OFF;
        if (g->en_sync && !g->fault && cmd == 0) state_next = G_ZERO;
        break;
    case G_POS:
        pwm_next = VEC_POS;
        if (g->minw_ok) state_next = (cmd == 1) ? G_POS : G_POS_DEAD;
        break;
    case G_POS_DEAD:
        pwm_next = VEC_ZERO_P;
        if (dt_ok_redge) state_next = (cmd == 1) ? G_POS : G_ZERO;
        break;
    case G_ZERO:
        pwm_next = VEC_ZERO;
        if (g->minw_ok) {
            if (cmd == 1) state_next = G_POS_DEAD;
            else if (cmd == -1) state_next = G_NEG_DEAD;
            else state_next = G_ZERO;
        }
        break;
    case G_NEG_DEAD:
        pwm_next = VEC_ZERO_N;
        if (dt_ok_redge) state_next = (cmd == -1) ? G_NEG : G_ZERO;
        break;
    case G_NEG:
        pwm_next = VEC_NEG;
        if (g->minw_ok) state_next = (cmd == -1) ? G_NEG : G_NEG_DEAD;
        break;
    case G_WAIT:
        pwm_next = VEC_OFF;
        if (!en) {
            if (g->ctr_wait < wait_cnt - 1) wait_next = g->ctr_wait + 1;
            else { wait_next = 0; state_next = G_OFF; }
        }
        break;
    }
    if (!en && g->state != G_OFF && g->state != G_WAIT) state_next = G_WAIT;
    if (state_next != old_state) {
        ctr_next = 0; minw_next = 0; dt_next = 0;
    } else {
        int limit = min_pulse > dead_time ? min_pulse : dead_time;
        if (old_ctr < limit) ctr_next = old_ctr + 1;
        if (old_ctr >= min_pulse - 1) minw_next = 1;
        if (old_ctr >= dead_time - 1) dt_next = 1;
    }
    g->state = state_next; g->pwm = pwm_next; g->ctr = ctr_next;
    g->ctr_wait = wait_next; g->minw_ok = minw_next; g->dt_ok = dt_next;
    g->dt_ok_reg = old_dt_ok; g->en_sync = en_next;
    return g->pwm;
}

static int read_rows(const char *path, Row **out) {
    FILE *f = fopen(path, "r");
    if (!f) { perror("csv"); return -1; }
    char line[4096];
    if (!fgets(line, sizeof(line), f)) { fclose(f); return -1; }
    int cap = 1024, n = 0;
    Row *rows = (Row*)malloc(sizeof(Row) * cap);
    while (fgets(line, sizeof(line), f)) {
        double v[18];
        char *s = line;
        int k = 0;
        while (k < 18 && s) {
            v[k++] = strtod(s, &s);
            if (*s == ',') s++;
        }
        if (k < 18) continue;
        if (n >= cap) { cap *= 2; rows = (Row*)realloc(rows, sizeof(Row) * cap); }
        rows[n].t = v[1]; rows[n].ia = v[8]; rows[n].ib = v[9];
        rows[n].fa = v[10]; rows[n].fb = v[11]; rows[n].speed = v[12];
        n++;
    }
    fclose(f);
    *out = rows;
    return n;
}

static double rms(double s2, long n) { return n ? sqrt(s2 / (double)n) : 0.0; }

int main(int argc, char **argv) {
    if (argc < 24) return 2;
    const char *inpath = argv[1], *outpath = argv[2], *metpath = argv[3];
    int clock = atoi(argv[4]), pwmfreq = atoi(argv[5]), step_cycles = atoi(argv[6]);
    int carrier_phase = atoi(argv[7]);
    double vdc = atof(argv[8]), ts = atof(argv[9]);
    double rs = atof(argv[10]), rr = atof(argv[11]), lm = atof(argv[12]);
    double ls = atof(argv[13]), lr = atof(argv[14]), J = atof(argv[15]), npp = atof(argv[16]);
    double vf_base = atof(argv[17]), vf_acc = atof(argv[18]), modulation = atof(argv[19]);
    double theta0 = atof(argv[20]), warmup_s = atof(argv[21]);
    int rec_int = atoi(argv[22]);
    double skip_s = atof(argv[23]);

    Row *rows = NULL;
    int nrows = read_rows(inpath, &rows);
    if (nrows <= 0) return 1;
    int cmax = (clock / pwmfreq) / 2;
    MockPWM pwm; pwm_init(&pwm, carrier_phase, cmax);
    GateDriver ga, gb, gc; gate_init(&ga); gate_init(&gb); gate_init(&gc);

    long warm_cycles = (long)(warmup_s * (double)clock);
    for (long i = 0; i < warm_cycles; i++) {
        int valley = pwm_step(&pwm, cmax);
        int sa = npc_state(pwm.va_lat, pwm.carrier, cmax);
        int sb = npc_state(pwm.vb_lat, pwm.carrier, cmax);
        int sc = npc_state(pwm.vc_lat, pwm.carrier, cmax);
        gate_step(&ga, sa, 1, valley, 100, 50, clock / 1000);
        gate_step(&gb, sb, 1, valley, 100, 50, clock / 1000);
        gate_step(&gc, sc, 1, valley, 100, 50, clock / 1000);
    }

    IM_Model_t m; IM_Init(&m);
    IMParams p = {0};
    p.Rs = rs; p.Rr = rr; p.Lm = lm; p.Ls = ls; p.Lr = lr; p.J = J; p.npp = npp; p.Ts = ts;
    IM_SetParams(&m, &p); IM_TypeModel(&m, MODEL_B2);

    FILE *out = fopen(outpath, "w");
    if (!out) return 1;
    fprintf(out, "t_s,vhdl_i_alpha,vhdl_i_beta,vhdl_flux_alpha,vhdl_flux_beta,vhdl_speed,c_i_alpha,c_i_beta,c_flux_alpha,c_flux_beta,c_speed,va,vb,vc,pwm_a,pwm_b,pwm_c\n");

    long rowi = 0, outn = 0, cnt = 0;
    double se[5] = {0}, sae[5] = {0}, ref2[2] = {0};
    double t_end = rows[nrows - 1].t;
    for (long step = 0; ; step++) {
        double t = step * ts;
        if (t > t_end + ts * 0.5) break;
        double t_acc = vf_acc > 0 ? vf_base / vf_acc : 0.0;
        double f_now, theta;
        if (t_acc > 0 && t < t_acc) {
            f_now = vf_acc * t;
            theta = theta0 + 2.0 * M_PI * 0.5 * vf_acc * t * t;
        } else {
            f_now = vf_base;
            double theta_acc = t_acc > 0 ? 2.0 * M_PI * 0.5 * vf_acc * t_acc * t_acc : 0.0;
            theta = theta0 + theta_acc + 2.0 * M_PI * vf_base * fmax(0.0, t - t_acc);
        }
        double amp = vf_base > 0 ? modulation * fmin(fmax(f_now / vf_base, 0.0), 1.0) : 0.0;
        pwm.va_ref = (int)(cmax * amp * sin(theta));
        pwm.vb_ref = (int)(cmax * amp * sin(theta - 2.0 * M_PI / 3.0));
        pwm.vc_ref = (int)(cmax * amp * sin(theta + 2.0 * M_PI / 3.0));
        int pa = VEC_OFF, pb = VEC_OFF, pc = VEC_OFF;
        for (int k = 0; k < step_cycles; k++) {
            int valley = pwm_step(&pwm, cmax);
            int sa = npc_state(pwm.va_lat, pwm.carrier, cmax);
            int sb = npc_state(pwm.vb_lat, pwm.carrier, cmax);
            int sc = npc_state(pwm.vc_lat, pwm.carrier, cmax);
            pa = gate_step(&ga, sa, 1, valley, 100, 50, clock / 1000);
            pb = gate_step(&gb, sb, 1, valley, 100, 50, clock / 1000);
            pc = gate_step(&gc, sc, 1, valley, 100, 50, clock / 1000);
        }
        double va = gate_to_v(pa, vdc), vb = gate_to_v(pb, vdc), vc = gate_to_v(pc, vdc);
        IMInputs in = {va, vb, vc, 0.0};
        IM_SetInputs(&m, &in); IM_SimulateStep(&m);
        IM_PrivateData_t *priv = (IM_PrivateData_t*)m.priv;
        while (rowi < nrows && rows[rowi].t <= t + ts * 0.5) {
            double c[5] = {priv->out.is_alpha, priv->out.is_beta, priv->out.fluxR_alpha, priv->out.fluxR_beta, priv->out.wm};
            double y[5] = {rows[rowi].ia, rows[rowi].ib, rows[rowi].fa, rows[rowi].fb, rows[rowi].speed};
            if (rows[rowi].t >= skip_s) {
                for (int q = 0; q < 5; q++) { double e = y[q] - c[q]; se[q] += e * e; sae[q] += fabs(e); }
                ref2[0] += c[0] * c[0]; ref2[1] += c[1] * c[1]; cnt++;
            }
            if (outn % rec_int == 0) {
                fprintf(out, "%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%d\n",
                    rows[rowi].t, y[0], y[1], y[2], y[3], y[4], c[0], c[1], c[2], c[3], c[4], va, vb, vc, pa, pb, pc);
            }
            outn++; rowi++;
        }
    }
    fclose(out);

    FILE *mf = fopen(metpath, "w");
    if (!mf) return 1;
    fprintf(mf, "{\n  \"level\": \"L3\",\n  \"test\": \"top_fullstack_mock\",\n  \"status\": \"diagnostic\",\n");
    fprintf(mf, "  \"method_note\": \"C mock generates V/F, carrier, gate driver and motor independently; compared against decimated Top_HIL simulation CSV.\",\n");
    fprintf(mf, "  \"carrier_phase_cycles\": %d,\n  \"warmup_s\": %.9g,\n  \"input_rows\": %d,\n  \"metrics_samples\": %ld,\n", carrier_phase, warmup_s, nrows, cnt);
    fprintf(mf, "  \"metrics\": {\n");
    fprintf(mf, "    \"nrmse_i_alpha\": %.12g,\n", rms(se[0], cnt) / fmax(sqrt(ref2[0] / fmax(cnt, 1)), 1e-12));
    fprintf(mf, "    \"nrmse_i_beta\": %.12g,\n", rms(se[1], cnt) / fmax(sqrt(ref2[1] / fmax(cnt, 1)), 1e-12));
    fprintf(mf, "    \"mae_flux_alpha_wb\": %.12g,\n", sae[2] / fmax(cnt, 1));
    fprintf(mf, "    \"mae_flux_beta_wb\": %.12g,\n", sae[3] / fmax(cnt, 1));
    fprintf(mf, "    \"mae_speed_rad_s\": %.12g\n  }\n}\n", sae[4] / fmax(cnt, 1));
    fclose(mf);
    free(rows);
    return 0;
}
'''


def _read_output_rows(csv_path: Path) -> list[dict[str, float]]:
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        return [{k: float(v) for k, v in row.items()} for row in reader]


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def _window_metrics(rows: list[dict[str, float]], windows: list[tuple[float, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for start, end in windows:
        subset = [r for r in rows if start <= r["t_s"] < end]
        key = f"{start:.3f}_{end:.3f}s"
        if not subset:
            out[key] = {"samples": 0}
            continue
        eia = [r["vhdl_i_alpha"] - r["c_i_alpha"] for r in subset]
        eib = [r["vhdl_i_beta"] - r["c_i_beta"] for r in subset]
        ref_ia = [r["c_i_alpha"] for r in subset]
        ref_ib = [r["c_i_beta"] for r in subset]
        out[key] = {
            "samples": len(subset),
            "nrmse_i_alpha": _rms(eia) / max(_rms(ref_ia), 1e-12),
            "nrmse_i_beta": _rms(eib) / max(_rms(ref_ib), 1e-12),
            "mae_flux_alpha_wb": sum(abs(r["vhdl_flux_alpha"] - r["c_flux_alpha"]) for r in subset) / len(subset),
            "mae_flux_beta_wb": sum(abs(r["vhdl_flux_beta"] - r["c_flux_beta"]) for r in subset) / len(subset),
            "mae_speed_rad_s": sum(abs(r["vhdl_speed"] - r["c_speed"]) for r in subset) / len(subset),
        }
    return out


def _generate_overlay(csv_path: Path, out_path: Path, title: str, max_points: int = 22000) -> Path | None:
    rows = _read_output_rows(csv_path)
    if not rows:
        return None
    stride = max(1, len(rows) // max_points)
    rows = rows[::stride]

    def col(name: str) -> list[float]:
        return [r[name] for r in rows]

    payload = {
        "title": title,
        "t": col("t_s"),
        "series": [
            {"name": "Mock C i_alpha", "y": col("c_i_alpha"), "axis": "y", "color": "#2f80ed"},
            {"name": "Top_HIL i_alpha", "y": col("vhdl_i_alpha"), "axis": "y", "color": "#ff6b35", "dash": "dot"},
            {"name": "Mock C i_beta", "y": col("c_i_beta"), "axis": "y2", "color": "#2f80ed"},
            {"name": "Top_HIL i_beta", "y": col("vhdl_i_beta"), "axis": "y2", "color": "#ff6b35", "dash": "dot"},
            {"name": "Mock C flux alpha", "y": col("c_flux_alpha"), "axis": "y3", "color": "#2f80ed"},
            {"name": "Top_HIL flux alpha", "y": col("vhdl_flux_alpha"), "axis": "y3", "color": "#ff6b35", "dash": "dot"},
            {"name": "Mock C flux beta", "y": col("c_flux_beta"), "axis": "y4", "color": "#2f80ed"},
            {"name": "Top_HIL flux beta", "y": col("vhdl_flux_beta"), "axis": "y4", "color": "#ff6b35", "dash": "dot"},
            {"name": "Mock C speed", "y": col("c_speed"), "axis": "y5", "color": "#2f80ed"},
            {"name": "Top_HIL speed", "y": col("vhdl_speed"), "axis": "y5", "color": "#ff6b35", "dash": "dot"},
            {"name": "va", "y": col("va"), "axis": "y6", "color": "#2f80ed"},
            {"name": "vb", "y": col("vb"), "axis": "y6", "color": "#27ae60"},
            {"name": "vc", "y": col("vc"), "axis": "y6", "color": "#9b51e0"},
        ],
    }
    html = f"""<!doctype html>
<html lang=\"pt-BR\">
<head>
<meta charset=\"utf-8\" />
<title>{title}</title>
<script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
<style>
body {{ margin: 0; background: #11161c; color: #d9e2ec; font-family: Arial, sans-serif; }}
#chart {{ width: 100vw; height: 1450px; }}
.note {{ padding: 14px 18px 0; color: #9fb1c1; }}
</style>
</head>
<body>
<div class=\"note\"><strong>{title}</strong><br>Fonte: {csv_path.name} | pontos exibidos: {len(payload['t'])} | zoom/pan/box select habilitados</div>
<div id=\"chart\"></div>
<script>
const payload = {json.dumps(payload)};
const data = payload.series.map(s => ({{
  x: payload.t,
  y: s.y,
  name: s.name,
  yaxis: s.axis,
  type: 'scattergl',
  mode: 'lines',
  line: {{color: s.color, width: 1.25, dash: s.dash || 'solid'}}
}}));
const layout = {{
  title: {{text: payload.title, font: {{color: '#d9e2ec'}}}},
  paper_bgcolor: '#11161c',
  plot_bgcolor: '#11161c',
  font: {{color: '#d9e2ec'}},
  legend: {{orientation: 'h', x: 0.02, y: 1.04}},
  margin: {{l: 70, r: 35, t: 95, b: 55}},
  hovermode: 'x unified',
  xaxis: {{domain: [0, 1], anchor: 'y6', title: 'tempo [s]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis: {{domain: [0.84, 1.00], title: 'iα [A]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis2: {{domain: [0.67, 0.81], title: 'iβ [A]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis3: {{domain: [0.50, 0.64], title: 'ψα [Wb]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis4: {{domain: [0.33, 0.47], title: 'ψβ [Wb]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis5: {{domain: [0.17, 0.30], title: 'ωm [rad/s]', gridcolor: '#233142', zerolinecolor: '#3a4652'}},
  yaxis6: {{domain: [0.00, 0.13], title: 'vabc [V]', gridcolor: '#233142', zerolinecolor: '#3a4652'}}
}};
Plotly.newPlot('chart', data, layout, {{responsive: true, scrollZoom: true}});
</script>
</body>
</html>
"""
    out_path.write_text(html)
    return out_path


def _write_readme(out_dir: Path, top_csv: Path, metrics: dict[str, Any], windows: dict[str, Any], overlay: Path | None) -> None:
    m = metrics.get("metrics", {})
    lines = [
        "# L3 full-stack mock",
        "",
        "Comparacao diagnostica entre `Top_HIL` em simulacao e um mock C/C++ independente que gera V/F, portadora triangular, estados do gate driver e modelo do motor.",
        "",
        "## Entradas",
        "",
        f"- CSV Top_HIL: `{top_csv}`.",
        "- Parametros de motor, Vdc, PWM, clock e passo do solver mantidos iguais aos da campanha L2/L3.",
        "- As metricas deste diretorio usam os pontos presentes no CSV de entrada. Para o caso de 2 s, esse CSV ja estava decimado pela simulacao longa.",
        "",
        "## Metricas globais",
        "",
        f"- `i_alpha` NRMSE: `{m.get('nrmse_i_alpha', 'n/a')}`.",
        f"- `i_beta` NRMSE: `{m.get('nrmse_i_beta', 'n/a')}`.",
        f"- `flux_alpha` MAE: `{m.get('mae_flux_alpha_wb', 'n/a')}` Wb.",
        f"- `flux_beta` MAE: `{m.get('mae_flux_beta_wb', 'n/a')}` Wb.",
        f"- velocidade MAE: `{m.get('mae_speed_rad_s', 'n/a')}` rad/s.",
        "",
        "## Janelas",
        "",
    ]
    for name, wm in windows.items():
        if not wm.get("samples"):
            continue
        lines.append(
            f"- `{name}`: ia `{wm['nrmse_i_alpha']:.6g}`, ib `{wm['nrmse_i_beta']:.6g}`, "
            f"flux MAE `{wm['mae_flux_alpha_wb']:.6g}`/`{wm['mae_flux_beta_wb']:.6g}` Wb, "
            f"speed MAE `{wm['mae_speed_rad_s']:.6g}` rad/s, samples `{wm['samples']}`."
        )
    lines.extend([
        "",
        "## Arquivos",
        "",
        "- `fullstack_vs_top.csv`: comparacao ponto a ponto.",
        "- `metrics.json`: metricas globais.",
        "- `window_metrics.json`: metricas por trecho.",
        "- `overlay.html`: grafico interativo com zoom/pan." if overlay else "- `overlay.html`: nao gerado.",
        "",
        "## Interpretacao",
        "",
        "Este ensaio e mais rigoroso que o L3 PWM replay porque o C/C++ nao recebe `va/vb/vc` do VHDL; ele tenta reproduzir a cadeia de modulacao. Se o erro ficar proximo ao replay, a divergencia observada vem principalmente da dinamica numerica/modelo sob transitorio, nao da reconstrucao basica do PWM.",
        "",
    ])
    (out_dir / "README.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("top_csv", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--carrier-phase-cycles", type=int, default=0)
    ap.add_argument("--warmup-s", type=float, default=0.001)
    ap.add_argument("--record-interval", type=int, default=1)
    ap.add_argument("--skip-s", type=float, default=0.0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[3]
    src_dir = root / "extras" / "induction-motor-model" / "src"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "fullstack_vs_top.csv"
    metrics = args.out_dir / "metrics.json"

    with tempfile.TemporaryDirectory(prefix="top_fullstack_") as td:
        td_path = Path(td)
        cpath = td_path / "runner.c"
        exe = td_path / "runner"
        cpath.write_text(RUNNER_C)
        subprocess.run(
            [os.environ.get("CC", "gcc"), "-O3", "-I", str(src_dir), str(cpath), str(src_dir / "IM_Model.c"), "-lm", "-o", str(exe)],
            check=True,
        )
        cmd = [
            str(exe), str(args.top_csv), str(out_csv), str(metrics),
            "200000000", "1000", "26", str(args.carrier_phase_cycles),
            "1240", str(26 / 200_000_000),
            "0.4396", "0.2826", str(109.9442e-3), str(3.1364e-3), str(6.3264e-3), "0.4", "2.0",
            "60.0", "60.0", "1.0", str(math.pi / 4), str(args.warmup_s), str(args.record_interval), str(args.skip_s),
        ]
        subprocess.run(cmd, check=True)

    print(metrics)
    print(out_csv)
    rows = _read_output_rows(out_csv)
    windows = _window_metrics(rows, [(0.0, 0.05), (0.05, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0)])
    window_path = args.out_dir / "window_metrics.json"
    window_path.write_text(json.dumps(windows, indent=2))
    overlay = _generate_overlay(out_csv, args.out_dir / "overlay.html", f"L3 full-stack mock vs Top_HIL - {args.top_csv.parent.name}")
    with metrics.open() as f:
        metrics_data = json.load(f)
    _write_readme(args.out_dir, args.top_csv, metrics_data, windows, overlay)
    print(window_path)
    if overlay:
        print(overlay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
