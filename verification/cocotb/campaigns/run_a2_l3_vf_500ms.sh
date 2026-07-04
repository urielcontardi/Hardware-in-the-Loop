#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 IM_RS=0.4396 IM_RR=0.2826 IM_LS=0.0031364 IM_LR=0.0063264 IM_LM=0.1099442 IM_J=0.4 IM_NPP=2.0 HIL_PWM_FREQUENCY=1000 HIL_L3_STEPS=3846154 HIL_L3_WARMUP_STEPS=400 HIL_L3_RECORD_INTERVAL=800 HIL_L3_VDC=1240 HIL_L3_MODULATION=1.0 HIL_L3_REF_MODE=vf HIL_L3_REF_FREQ_HZ=60 HIL_L3_VF_BASE_HZ=60 HIL_L3_VF_ACC_HZ_S=120 HIL_L3_INITIAL_THETA_RAD=0.7853981633974483 HIL_L3_TLOAD_NM=116.7136249340566 HIL_L3_OUT_DIR=/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_02/A2_tacc0p5s_load100/l3_top_pwm_replay_vf_500ms uv run python run.py --sim nvc --top top_hil --test top_hil -k test_top_hil_pwm_replay_l3
