#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, subprocess, tempfile
from pathlib import Path

RUNNER_C = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "IM_Model.h"

typedef struct { float t, ia, ib, fa, fb, speed, tl; } Telem;
static uint32_t rd_u32(const unsigned char *p) { return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24); }
static double rms(double s2, uint64_t n) { return n ? sqrt(s2/(double)n) : 0.0; }

typedef struct { double valpha, vbeta, v0; } IM_InternalInputs_t;
typedef struct { double is_alpha,is_beta,ir_alpha,ir_beta,fluxR_alpha,fluxR_beta,wr,wm,Te,isd,isq,fluxRd,angleR; } IM_States_t;
typedef struct { IM_InternalInputs_t inp; IM_States_t out; } IM_PrivateData_t;

typedef struct {
    int carrier;
    int dir;
    int va_ref, vb_ref, vc_ref;
    int va_lat, vb_lat, vc_lat;
    int phase_cycles;
} MockPWM;

static int abs_sat(int x, int maxv) {
    long v = x < 0 ? -(long)x : (long)x;
    return v > maxv ? maxv : (int)v;
}
static int npc_state(int ref, int carrier, int cmax) {
    int mag = abs_sat(ref, cmax);
    if (mag > carrier) return ref < 0 ? -1 : 1;
    return 0;
}
enum { G_OFF=0, G_POS=1, G_POS_DEAD=2, G_ZERO=3, G_NEG=4, G_NEG_DEAD=5, G_WAIT=6 };
#define VEC_OFF 0x0
#define VEC_POS 0x3
#define VEC_ZERO_P 0x2
#define VEC_ZERO 0x6
#define VEC_ZERO_N 0x4
#define VEC_NEG 0xC

typedef struct {
    int state;
    int pwm;
    int ctr;
    int ctr_wait;
    int minw_ok;
    int dt_ok;
    int dt_ok_reg;
    int fault;
    int en_sync;
} GateDriver;

static double gate_to_v(int g, double vdc) {
    if (g == VEC_POS) return 0.5 * vdc;
    if (g == VEC_NEG) return -0.5 * vdc;
    if (g == VEC_ZERO_P) return 0.25 * vdc;
    if (g == VEC_ZERO_N) return -0.25 * vdc;
    return 0.0;
}
static double state_to_v(int s, double vdc) {
    if (s > 0) return 0.5 * vdc;
    if (s < 0) return -0.5 * vdc;
    return 0.0;
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
    int state_next = g->state;
    int pwm_next = g->pwm;
    int ctr_next = g->ctr;
    int wait_next = g->ctr_wait;
    int minw_next = g->minw_ok;
    int dt_next = g->dt_ok;
    int en_next = g->en_sync;

    if (sync) en_next = en;

    switch (g->state) {
    case G_OFF:
        pwm_next = VEC_OFF;
        if (g->en_sync && !g->fault && cmd == 0) state_next = G_ZERO;
        break;
    case G_POS:
        pwm_next = VEC_POS;
        if (g->minw_ok) {
            if (cmd == 1) state_next = G_POS;
            else state_next = G_POS_DEAD;
        }
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
        if (g->minw_ok) {
            if (cmd == -1) state_next = G_NEG;
            else state_next = G_NEG_DEAD;
        }
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
        ctr_next = 0;
        minw_next = 0;
        dt_next = 0;
    } else {
        int limit = min_pulse > dead_time ? min_pulse : dead_time;
        if (old_ctr < limit) ctr_next = old_ctr + 1;
        if (old_ctr >= min_pulse - 1) minw_next = 1;
        if (old_ctr >= dead_time - 1) dt_next = 1;
    }

    g->state = state_next;
    g->pwm = pwm_next;
    g->ctr = ctr_next;
    g->ctr_wait = wait_next;
    g->minw_ok = minw_next;
    g->dt_ok = dt_next;
    g->dt_ok_reg = old_dt_ok;
    g->en_sync = en_next;
    return g->pwm;
}
static void pwm_init(MockPWM *p, int phase, int cmax) {
    memset(p, 0, sizeof(*p));
    p->dir = 1;
    p->phase_cycles = phase;
    for (int i=0; i<phase; i++) {
        if (p->dir) { if (p->carrier >= cmax - 1) p->dir = 0; else p->carrier++; }
        else { if (p->carrier == 0) p->dir = 1; else p->carrier--; }
    }
}
static int pwm_step(MockPWM *p, int cmax) {
    int valley = 0;
    if (p->dir) {
        if (p->carrier >= cmax - 1) p->dir = 0;
        else p->carrier++;
    } else {
        if (p->carrier == 0) { p->dir = 1; valley = 1; }
        else p->carrier--;
    }
    if (valley) { p->va_lat = p->va_ref; p->vb_lat = p->vb_ref; p->vc_lat = p->vc_ref; }
    return valley;
}

int main(int argc, char **argv) {
    if (argc < 20) {
        fprintf(stderr, "usage: %s hilbin out.csv freq_hz vdc skip ts rs rr lm ls lr j npp base_freq max_v_pu accel carrier_phase_cycles vf_phase_s theta0_rad gate_mode\n", argv[0]);
        return 2;
    }
    const char *path=argv[1], *csvpath=argv[2];
    double freq=atof(argv[3]), vdc=atof(argv[4]), skip=atof(argv[5]), ts=atof(argv[6]);
    double rs=atof(argv[7]), rr=atof(argv[8]), lm=atof(argv[9]), ls=atof(argv[10]), lr=atof(argv[11]), J=atof(argv[12]), npp=atof(argv[13]);
    double base_freq=atof(argv[14]), max_v_pu=atof(argv[15]), accel_time=atof(argv[16]);
    int carrier_phase=atoi(argv[17]);
    double vf_phase_s=atof(argv[18]);
    double theta0=atof(argv[19]);
    int gate_mode=argc > 20 ? atoi(argv[20]) : 0;
    const int cmax = 50000;
    const double vf_tick = 0.001;

    FILE *f=fopen(path,"rb"); if(!f){perror("open");return 1;} fseek(f,0,SEEK_END); long sz=ftell(f); rewind(f);
    unsigned char *buf=malloc((size_t)sz); if(!buf){return 1;} if(fread(buf,1,(size_t)sz,f)!=(size_t)sz){perror("read");return 1;} fclose(f);
    if(sz<16 || memcmp(buf,"HILDATA",7)!=0){fprintf(stderr,"bad hilbin\n");return 1;}
    uint32_t json_len=rd_u32(buf+8); size_t off=(12u+json_len+7u)&~7u;
    uint32_t tn=rd_u32(buf+off); off+=4;
    if(off+(size_t)tn*sizeof(Telem)+4>(size_t)sz){fprintf(stderr,"truncated telem\n");return 1;}
    Telem *telem=(Telem*)(buf+off);
    if(tn<2){fprintf(stderr,"empty telem\n");return 1;}
    double t_end=telem[tn-1].t;

    IM_Model_t m; IM_Init(&m); IMParams p={0};
    p.Rs=rs; p.Rr=rr; p.Lm=lm; p.Ls=ls; p.Lr=lr; p.J=J; p.npp=npp; p.Ts=ts;
    IM_SetParams(&m,&p); IM_TypeModel(&m, MODEL_B2);
    MockPWM pwm; pwm_init(&pwm, carrier_phase, cmax);
    GateDriver ga, gb, gc; gate_init(&ga); gate_init(&gb); gate_init(&gc);

    FILE *csv=fopen(csvpath,"w"); if(!csv){perror("csv");return 1;}
    fprintf(csv,"t,fpga_ia,fpga_ib,fpga_fa,fpga_fb,fpga_speed,c_ia,c_ib,c_fa,c_fb,c_speed,va,vb,vc,freq_actual\n");

    double theta=theta0, fcur=0.0, next_vf=vf_phase_s;
    uint32_t ti=0; double se[5]={0}, sae[5]={0}, sy[5]={0}, sy2[5]={0}; uint64_t cnt=0, steps=0;
    double svf_lp[5]={0}, svf_bp[5]={0}, last[5]={0};
    double va=0,vb=0,vc=0;
    for(double t=0.0; t<=t_end+ts; t+=ts, steps++) {
        while(t + 1e-15 >= next_vf) {
            double target = freq < 0 ? 0 : freq;
            double accel = accel_time > 0 ? base_freq / accel_time : 1e9;
            double step = accel * vf_tick;
            if(fcur < target) fcur = fcur + step > target ? target : fcur + step;
            else if(fcur > target) fcur = fcur - step < target ? target : fcur - step;
            double vpu = max_v_pu * (fcur / base_freq); if(vpu > max_v_pu) vpu = max_v_pu;
            theta += 2.0*M_PI*fcur*vf_tick; while(theta > 2.0*M_PI) theta -= 2.0*M_PI;
            double scale = vpu * (double)cmax;
            pwm.va_ref = (int)(scale * sin(theta));
            pwm.vb_ref = (int)(scale * sin(theta - 2.0*M_PI/3.0));
            pwm.vc_ref = (int)(scale * sin(theta + 2.0*M_PI/3.0));
            next_vf += vf_tick;
        }
        int valley = 0;
        for(int k=0;k<13;k++) valley |= pwm_step(&pwm, cmax);
        int sa=npc_state(pwm.va_lat, pwm.carrier, cmax), sb=npc_state(pwm.vb_lat, pwm.carrier, cmax), sc=npc_state(pwm.vc_lat, pwm.carrier, cmax);
        if (gate_mode) {
            int pa=gate_step(&ga, sa, 1, valley, 100, 50, 100000);
            int pb=gate_step(&gb, sb, 1, valley, 100, 50, 100000);
            int pc=gate_step(&gc, sc, 1, valley, 100, 50, 100000);
            va=gate_to_v(pa,vdc); vb=gate_to_v(pb,vdc); vc=gate_to_v(pc,vdc);
        } else {
            va=state_to_v(sa,vdc); vb=state_to_v(sb,vdc); vc=state_to_v(sc,vdc);
        }
        IMInputs in={va,vb,vc,0.0}; IM_SetInputs(&m,&in); IM_SimulateStep(&m);
        IM_PrivateData_t *priv=(IM_PrivateData_t*)m.priv;
        double raw[5]={priv->out.is_alpha,priv->out.is_beta,priv->out.fluxR_alpha,priv->out.fluxR_beta,priv->out.wm};
        for(int k=0;k<5;k++){ double lp=svf_lp[k], bp=svf_bp[k]; svf_lp[k]=lp+bp/32.0; svf_bp[k]=bp+raw[k]/32.0-lp/32.0-(1.4375*bp)/32.0; last[k]=svf_lp[k]; }
        while(ti < tn && telem[ti].t <= t) {
            double y[5]={telem[ti].ia,telem[ti].ib,telem[ti].fa,telem[ti].fb,telem[ti].speed};
            if(telem[ti].t >= skip) { for(int k=0;k<5;k++){ double e=y[k]-last[k]; se[k]+=e*e; sae[k]+=fabs(e); sy[k]+=y[k]; sy2[k]+=y[k]*y[k]; } cnt++; }
            fprintf(csv,"%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n", telem[ti].t,y[0],y[1],y[2],y[3],y[4],last[0],last[1],last[2],last[3],last[4],va,vb,vc,fcur);
            ti++;
        }
    }
    fclose(csv);
    const char *names[5]={"ia","ib","fa","fb","speed"};
    printf("mode=%s hilbin=%s csv=%s\n", gate_mode ? "fullstack_mock_gated" : "fullstack_mock_ideal", path, csvpath);
    printf("steps=%llu telem=%u freq=%.6g vdc=%.6g carrier_phase=%d vf_phase=%.9g theta0=%.9g gate_mode=%d skip=%.6g\n", (unsigned long long)steps, tn, freq, vdc, carrier_phase, vf_phase_s, theta0, gate_mode, skip);
    for(int k=0;k<5;k++){ double mean=sy[k]/(double)cnt; double var=sy2[k]/(double)cnt-mean*mean; if(var<0)var=0; double nrmse=rms(se[k],cnt)/fmax(sqrt(var),1e-12); printf("%-5s mae=%.9g rmse=%.9g nrmse=%.9g mean=%.9g\n", names[k], sae[k]/(double)cnt, rms(se[k],cnt), nrmse, mean); }
    free(buf); return 0;
}
'''

def main():
    ap=argparse.ArgumentParser(description="Native C full-stack mock: V/F + ideal NPC PWM + IM_Model vs .hilbin")
    ap.add_argument('hilbin', type=Path)
    ap.add_argument('--freq-hz', type=float, default=60.0)
    ap.add_argument('--vdc', type=float, default=1240.0)
    ap.add_argument('--skip', type=float, default=0.2)
    ap.add_argument('--ts', type=float, default=26/200_000_000)
    ap.add_argument('--rs', type=float, default=0.4396)
    ap.add_argument('--rr', type=float, default=0.2826)
    ap.add_argument('--lm', type=float, default=109.9442e-3)
    ap.add_argument('--ls', type=float, default=3.1364e-3)
    ap.add_argument('--lr', type=float, default=6.3264e-3)
    ap.add_argument('--j', type=float, default=0.4)
    ap.add_argument('--npp', type=float, default=2.0)
    ap.add_argument('--base-freq-hz', type=float, default=60.0)
    ap.add_argument('--max-v-pu', type=float, default=1.0)
    ap.add_argument('--accel-time-s', type=float, default=1.0)
    ap.add_argument('--carrier-phase-cycles', type=int, default=0)
    ap.add_argument('--vf-phase-s', type=float, default=0.0)
    ap.add_argument('--theta0-deg', type=float, default=0.0)
    ap.add_argument('--gate-mode', choices=['ideal', 'gated'], default='ideal')
    ap.add_argument('--out', type=Path, default=Path('verification/cocotb/reports/fullstack_mock/mock.csv'))
    ap.add_argument('--png', type=Path, default=None)
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    src_dir=root/'extras/induction-motor-model/src'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hil_fullstack_mock_') as td:
        td=Path(td); cpath=td/'runner.c'; exe=td/'runner'
        cpath.write_text(RUNNER_C)
        subprocess.run([os.environ.get('CC','gcc'), '-O3', '-I', str(src_dir), str(cpath), str(src_dir/'IM_Model.c'), '-lm', '-o', str(exe)], check=True)
        theta0=args.theta0_deg*3.141592653589793/180.0
        gate_mode='1' if args.gate_mode == 'gated' else '0'
        cmd=[str(exe), str(args.hilbin), str(args.out), str(args.freq_hz), str(args.vdc), str(args.skip), str(args.ts), str(args.rs), str(args.rr), str(args.lm), str(args.ls), str(args.lr), str(args.j), str(args.npp), str(args.base_freq_hz), str(args.max_v_pu), str(args.accel_time_s), str(args.carrier_phase_cycles), str(args.vf_phase_s), str(theta0), gate_mode]
        subprocess.run(cmd, check=True)
    if args.png:
        import numpy as np
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        data=np.genfromtxt(args.out, delimiter=',', names=True)
        fig,ax=plt.subplots(4,1,figsize=(11,9),sharex=True)
        fig.suptitle(f'Full-stack mock ({args.gate_mode}) theta0={args.theta0_deg:g} deg')
        for a,k,ck,lbl in zip(ax,['fpga_ia','fpga_ib','fpga_fa','fpga_speed'],['c_ia','c_ib','c_fa','c_speed'],['iα [A]','iβ [A]','ψα [Wb]','ωm [rad/s]']):
            a.plot(data['t'], data[ck], lw=1.2, label='Mock C')
            a.plot(data['t'], data[k], '.', ms=1.5, alpha=0.5, label='FPGA')
            a.set_ylabel(lbl); a.grid(alpha=.25); a.legend(fontsize=8)
        ax[-1].set_xlabel('Tempo [s]'); fig.tight_layout(); args.png.parent.mkdir(parents=True, exist_ok=True); fig.savefig(args.png, dpi=110)
        print(f'png={args.png}')
if __name__=='__main__': main()
