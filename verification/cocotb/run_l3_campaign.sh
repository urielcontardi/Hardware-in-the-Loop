#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run python scripts/run_campaign.py --config campaigns/l3_pwm_replay.json "$@"
