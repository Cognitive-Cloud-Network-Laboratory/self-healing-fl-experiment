# Self-Healing Federated Learning — Experiment Summary

> 📂 รวบรวมผลการทดลองทั้งหมด | Complete experiment archive

---

## 📋 ไฟล์สรุป

| ไฟล์ | ภาษา | คำอธิบาย |
|------|:----:|----------|
| [`timeline-experiments-th.md`](timeline-experiments-th.md) | 🇹🇭 ไทย | Timeline + ผลลัพธ์ + ข้อค้นพบ (ภาษาไทย) |
| [`timeline-experiments-en.md`](timeline-experiments-en.md) | 🇬🇧 ENG | Timeline + Results + Findings (English) |

## 💻 Source Code

| # | ไฟล์ | คำอธิบาย |
|:-:|------|----------|
| 01 | [`code/01_run_experiments_v1.py`](code/01_run_experiments_v1.py) | v1 — 3 Scenarios (A, B, C), Flower-style manual FedAvg |
| 02 | [`code/02_run_experiments_v2.py`](code/02_run_experiments_v2.py) | v2 — 4 Scenarios (A, B, C, D), CPU-optimized |
| 03 | [`code/03_scenario_d_fn.py`](code/03_scenario_d_fn.py) | Scenario D standalone — Client Quarantine Protocol |
| 04 | [`code/04_client.py`](code/04_client.py) | Flower-based Benign Client (v1) |
| 05 | [`code/05_malicious_client.py`](code/05_malicious_client.py) | Flower-based Malicious Client (v1) |
| 06 | [`code/06_server.py`](code/06_server.py) | Flower-based Server + Self-Healing (v1) |
| 07 | [`code/07_run_simulation.py`](code/07_run_simulation.py) | Flower simulation runner (v1) |
| 08 | [`code/08_generate_chart_v1.py`](code/08_generate_chart_v1.py) | Chart generator v1 |
| 09 | [`code/09_generate_chart_v2.py`](code/09_generate_chart_v2.py) | Chart generator v2 (final) |
| 10 | [`code/10_run_pipeline.sh`](code/10_run_pipeline.sh) | Bash pipeline runner |
| 11 | [`code/11_start_clients.sh`](code/11_start_clients.sh) | Client startup script |
| 12 | [`code/12_run_all.sh`](code/12_run_all.sh) | All-scenario wrapper |

## 📊 Results

| ไฟล์ | คำอธิบาย |
|------|----------|
| [`results/comparison_chart.png`](results/comparison_chart.png) | 📈 กราฟเปรียบเทียบ v1 |
| [`results/fl_comparison_4_scenarios.png`](results/fl_comparison_4_scenarios.png) | 📈 **กราฟเปรียบเทียบ v2 (final)** |
| [`results/scenario_a.csv`](results/scenario_a.csv) | ✅ Clean FL — 30 rounds |
| [`results/scenario_b.csv`](results/scenario_b.csv) | ✅ Vanilla Attack — 30 rounds |
| [`results/scenario_c.csv`](results/scenario_c.csv) | ✅ Naive Rollback — 30 rounds |
| [`results/scenario_d.csv`](results/scenario_d.csv) | ✅ **Quarantine Protocol — 30 rounds** |
| [`results/scenario_c_ledger.json`](results/scenario_c_ledger.json) | 🔗 Ledger C (Rounds 1-5) |
| [`results/scenario_d_ledger.json`](results/scenario_d_ledger.json) | 🔗 Ledger D (Rounds 1-5) |

---

**สร้างโดย Hermes Agent — Nous Research** | **อัปเดตล่าสุด: 30 มิถุนายน 2026**
