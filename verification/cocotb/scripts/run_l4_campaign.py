#!/usr/bin/env python3
"""Acquisition orchestrator for L4 (FPGA real) — drives the hil-go gateway
(http://127.0.0.1:5177) through the same set/run/stop sequence as the GUI,
replaying the exact V/f + load parameters already validated in L2/L3
(campaign_03) so the resulting .hilbin captures are directly comparable.

Usage (from verification/cocotb/):
    python3 scripts/run_l4_campaign.py [--case ID ...] [--out DIR]

Each scenario: POST /api/set (params, attach_udp) -> POST /api/run -> sleep
duration (mid-run POST /api/set for load-step cases) -> POST /api/stop ->
locate the newly sealed .hilbin in apps/hil-go/runs -> copy into
verification/results/<campaign>/<case>/raw/capture.hilbin with metadata.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import requests

GATEWAY = "http://127.0.0.1:5177"
REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = REPO_ROOT / "apps" / "hil-go" / "runs"

VDC_V = 1240.0
BASE_FREQ_HZ = 60.0
MAX_V_PU = 1.0
FREQ_HZ = 60.0

# Same parameters as verification/results/2026-07-04_campaign_03 (manifest.json
# + metrics.json), so L4 is directly comparable to the existing L2/L3 numbers.
SCENARIOS = {
    "S0": dict(group="sanity", t_acc_s=1.0, tload_nm=0.0, duration_s=2.0),
    "A1": dict(group="partida_aceleracao", t_acc_s=0.5, tload_nm=0.0, duration_s=0.5),
    "A3": dict(group="partida_aceleracao", t_acc_s=1.0, tload_nm=58.3568124670283, duration_s=1.0),
    "A5": dict(group="partida_aceleracao", t_acc_s=5.0, tload_nm=0.0, duration_s=5.0),
    "B1": dict(group="perturbacao_carga", t_acc_s=0.5, tload_nm=29.17840623351415,
               tload_post_nm=87.53521870054244, t_step_s=0.6, duration_s=1.0),
    "B2": dict(group="perturbacao_carga", t_acc_s=0.5, tload_nm=58.3568124670283,
               tload_post_nm=116.7136249340566, t_step_s=0.6, duration_s=1.0),
}

TAIL_BUFFER_S = 0.15   # extra capture time past nominal duration
SETTLE_S = 2.0         # pause between scenarios


def post(path: str, payload: dict | None = None) -> dict:
    r = requests.post(f"{GATEWAY}{path}", json=payload or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def get_status() -> dict:
    r = requests.get(f"{GATEWAY}/api/status", timeout=5)
    r.raise_for_status()
    return r.json()


def wait_idle(timeout_s: float = 10.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = get_status()
        if st.get("state") == "stopped":
            return
        time.sleep(0.2)
    print(f"  [aviso] board nao voltou a 'stopped' em {timeout_s}s (state={st.get('state')})")


def newest_hilbin(after_ts: float) -> Path | None:
    candidates = [p for p in RUNS_DIR.glob("*.hilbin") if p.stat().st_mtime >= after_ts - 1.0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_scenario(case_id: str, params: dict, out_root: Path) -> dict:
    print(f"\n== {case_id} ==  {params}")
    st0 = get_status()
    if st0.get("state") != "stopped":
        print(f"  [aviso] board nao esta 'stopped' antes de iniciar ({st0.get('state')}) — abortando caso")
        return {"case": case_id, "error": f"board busy: {st0.get('state')}"}

    set_payload = {
        "freq_hz": FREQ_HZ,
        "vdc_v": VDC_V,
        "torque_nm": params["tload_nm"],
        "base_freq_hz": BASE_FREQ_HZ,
        "max_v_pu": MAX_V_PU,
        "accel_time_s": params["t_acc_s"],
        "decim": 0,
        "attach_udp": True,
    }
    post("/api/set", set_payload)
    time.sleep(0.3)

    t_mark = time.time()
    post("/api/run", {})
    t_run_start = time.time()

    if "t_step_s" in params:
        time.sleep(max(0.0, params["t_step_s"] - (time.time() - t_run_start)))
        post("/api/set", {"torque_nm": params["tload_post_nm"]})
        print(f"  degrau de carga aplicado: {params['tload_nm']} -> {params['tload_post_nm']} Nm @ t={params['t_step_s']}s")

    remaining = params["duration_s"] + TAIL_BUFFER_S - (time.time() - t_run_start)
    time.sleep(max(0.0, remaining))

    stop_status = post("/api/stop", {})
    time.sleep(1.0)  # let the recorder seal the capture file to disk

    hilbin = newest_hilbin(t_mark)
    if hilbin is None:
        print("  [erro] nenhum .hilbin novo encontrado apos o stop")
        return {"case": case_id, "error": "no capture found"}

    case_dir = out_root / f"{case_id}_l4" / "raw"
    case_dir.mkdir(parents=True, exist_ok=True)
    dest = case_dir / "capture.hilbin"
    shutil.copy2(hilbin, dest)

    meta = {
        "case": case_id,
        "source_capture": hilbin.name,
        "params": params,
        "vdc_v": VDC_V,
        "base_freq_hz": BASE_FREQ_HZ,
        "max_v_pu": MAX_V_PU,
        "freq_hz": FREQ_HZ,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "final_status": stop_status,
    }
    (case_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"  ok -> {dest}  ({hilbin.stat().st_size / 1e6:.1f} MB)")

    wait_idle()
    time.sleep(SETTLE_S)
    return {"case": case_id, "capture": str(dest), "error": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", dest="cases", choices=list(SCENARIOS),
                     help="run only this case (repeatable); default: all")
    ap.add_argument("--out", default=str(REPO_ROOT / "verification" / "results" / "2026-07-14_campaign_l4"))
    args = ap.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    try:
        st = get_status()
    except Exception as e:
        print(f"gateway inacessivel em {GATEWAY}: {e}")
        return 1
    print(f"gateway ok — board {st.get('board_ip')}  state={st.get('state')}  fpga_version={st.get('fpga_version')}")

    cases = args.cases or list(SCENARIOS)
    results = []
    for case_id in cases:
        results.append(run_scenario(case_id, SCENARIOS[case_id], out_root))

    (out_root / "acquisition_log.json").write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if not r.get("error"))
    print(f"\n{ok}/{len(results)} capturas ok. Log: {out_root / 'acquisition_log.json'}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
