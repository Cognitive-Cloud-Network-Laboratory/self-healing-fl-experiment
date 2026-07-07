#!/bin/bash
# Wrapper script to run all 3 scenarios with output to log file
cd /root/fl-project
source .venv/bin/activate

export PYTHONUNBUFFERED=1

echo "[$(date)] เริ่ม Scenario A: Clean FL (10 Benign Clients)"
python -u run_experiments.py --scenario a 2>&1 | tee /tmp/scenario_a.log
echo "[$(date)] ✅ Scenario A เสร็จสิ้น"

echo "[$(date)] เริ่ม Scenario B: Vanilla FL under Attack"
python -u run_experiments.py --scenario b 2>&1 | tee /tmp/scenario_b.log
echo "[$(date)] ✅ Scenario B เสร็จสิ้น"

echo "[$(date)] เริ่ม Scenario C: Proposed Self-Healing"
python -u run_experiments.py --scenario c 2>&1 | tee /tmp/scenario_c.log
echo "[$(date)] ✅ Scenario C เสร็จสิ้น"

echo "[$(date)] 🎉 ทั้งหมดเสร็จสมบูรณ์!"
