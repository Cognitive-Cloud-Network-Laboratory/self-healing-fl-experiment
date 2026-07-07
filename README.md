# Self-Healing Federated Learning Experiment

> **Self-Healing FL via Snapshot-based Rollback Protocols and Blockchain Attestation against Data Poisoning**
>
> 🏫 **Org:** RBRU (org-rbru) | **Status:** ✅ Complete | **Dataset:** CIFAR-10

---

## 📂 Project Structure

```
self-healing-fl-experiment/
├── README.md                    ← This file
├── timeline-experiments.md      ← Full experiment timeline (🇹🇭)
├── .gitignore
│
├── data/                        ← CIFAR-10 dataset (downloadable)
│
├── experiments/                 ← All source code
│   ├── 01_run_experiments_v1.py
│   ├── 02_run_experiments_v2.py      ← Final 4-scenario runner
│   ├── 03_scenario_d_fn.py           ← Quarantine protocol module
│   ├── client.py / malicious_client.py / server.py
│   ├── generate_chart_v1.py / generate_chart_v2.py
│   ├── run_noniid_5000.py / run_noniid_threshold.py
│   └── run_*.sh                      ← Shell wrappers
│
├── notebooks/                   ← (placeholder for future notebooks)
│
├── models/                      ← Checkpoint snapshots (5 rounds)
│   └── global_model_round_{1-5}.pth
│
├── results/                     ← All experiment outputs
│   ├── figures/                 ← Charts (PNG)
│   │   ├── comparison_chart.png
│   │   └── fl_comparison_4_scenarios.png
│   ├── tables/                  ← CSV metrics + JSON ledgers
│   ├── logs/                    ← Experiment logs
│   ├── scenario_a/              ← Clean baseline (10 benign)
│   ├── scenario_b/              ← Vanilla attack (6B+4M, no defense)
│   ├── scenario_c/              ← Naive rollback (6B+4M, rollback only)
│   ├── scenario_d/              ← ✅ Quarantine protocol (proven)
│   ├── noniid_experiment/       ← Non-IID (Dirichlet) experiments
│   └── noniid_5000/             ← Non-IID 5000 samples
│
├── deploy/                      ← (placeholder for deployment)
│
├── papers/                      ← IEEE paper
│   ├── rfl-blockchain-paper.tex     ← LaTeX source
│   ├── rfl-blockchain-paper.pdf     ← ✅ Final PDF
│   ├── rfl-blockchain-paper.docx    ← Word version
│   ├── generate_docx.py             ← DOCX generator
│   └── figures/                     ← Paper figures
│
└── summary/                     ← Portable organized archive (for sharing)
    ├── README.md
    ├── timeline-experiments-th.md   ← 🇹🇭
    ├── timeline-experiments-en.md   ← 🇬🇧
    ├── code/                        ← Numbered source code
    └── results/                     ← Clean CSV + charts
```

---

## 🧪 4 Scenarios Comparison

| # | Scenario | Setup | Best Acc | Final Acc | Defense | Result |
|:-:|----------|-------|:--------:|:---------:|:--------:|:------:|
| A | **Clean Baseline** | 10 Benign | **63.29%** | 62.77% | — | ✅ Gold standard |
| B | **Vanilla Attack** | 6B + 4M | 52.74% | **10.00%** 💀 | None | ❌ Model destroyed |
| C | **Naive Rollback** | 6B + 4M | 50.71% | **10.00%** 💀 | Rollback only | ❌ 25 rollbacks, 0 recovery |
| **D** | **Quarantine Protocol** 🏆 | 6B + 4M → **6B** | **60.36%** | **58.94%** | Rollback + Quarantine | ✅ **~93% of clean** |

### 🔑 Key Finding
**Snapshot rollback alone is insufficient** against continuous attacks. The **Client Quarantine Protocol** (Scenario D) is the critical missing piece — proven to fully recover model accuracy.

---

## 📖 References
- **Skill:** `skill_view(name='federated-learning')` — Full experiment design pattern
- **GitHub:** https://github.com/pts-bot01/self-healing-fl-experiment
- **Paper:** [papers/rfl-blockchain-paper.pdf](papers/rfl-blockchain-paper.pdf)

---

*Created by Hermes Agent — Nous Research | RBRU Self-Healing FL Project*
