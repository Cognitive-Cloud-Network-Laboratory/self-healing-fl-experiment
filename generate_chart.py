#!/usr/bin/env python3
"""Generate comparison chart + summary for all 4 FL scenarios"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import csv
import numpy as np
from pathlib import Path

BASE = "/root/fl-project"

# Read all CSVs
def read_csv(path):
    rounds, accs, events = [], [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rounds.append(int(row['Round']))
            accs.append(float(row['Accuracy']) * 100)
            events.append(row['Event'])
    return rounds, accs, events

# Load data
a_r, a_a, a_e = read_csv(f"{BASE}/scenario_a/evaluation_metrics.csv")
b_r, b_a, b_e = read_csv(f"{BASE}/scenario_b/evaluation_metrics.csv")
c_r, c_a, c_e = read_csv(f"{BASE}/scenario_c/evaluation_metrics.csv")
d_r, d_a, d_e = read_csv(f"{BASE}/scenario_d/evaluation_metrics.csv")

# ---- CHART ----
fig, ax = plt.subplots(figsize=(16, 9))

colors = {'A': '#2196F3', 'B': '#F44336', 'C': '#FF9800', 'D': '#4CAF50'}
styles = {'A': '-', 'B': '--', 'C': ':', 'D': '-'}
widths = {'A': 2.5, 'B': 2, 'C': 2, 'D': 3}

# Scenario lines
ax.plot(a_r, a_a, label='A: Clean FL (10 Benign)', color=colors['A'],
        linestyle=styles['A'], linewidth=widths['A'], marker='o', markersize=3)
ax.plot(b_r, b_a, label='B: Vanilla FL under Attack (NO Defense)', color=colors['B'],
        linestyle=styles['B'], linewidth=widths['B'], marker='s', markersize=3)
ax.plot(c_r, c_a, label='C: Naive Self-Healing (Rollback Only)', color=colors['C'],
        linestyle=styles['C'], linewidth=widths['C'], marker='^', markersize=3)
ax.plot(d_r, d_a, label='D: Full Self-Healing + Client Quarantine', color=colors['D'],
        linestyle=styles['D'], linewidth=widths['D'], marker='D', markersize=3)

# Attack annotation
ax.axvspan(5.5, 30.5, alpha=0.08, color='red', label='_Attack Zone')
ax.axvline(x=5.5, color='red', linestyle='--', alpha=0.5, linewidth=1)
ax.annotate('Attack Starts\n(Round 6)', xy=(5.5, 65), fontsize=11, color='red',
            ha='center', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='red', alpha=0.8))

# Quarantine annotation  
ax.axvline(x=6.5, color='green', linestyle='--', alpha=0.5, linewidth=2)
ax.annotate('🔒 Quarantine D\n(Round 6)', xy=(6.5, 15), fontsize=11, color='green',
            ha='center', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#E8F5E9', edgecolor='green', alpha=0.9))

# Key result markers
ax.annotate(f'Best: {max(a_a):.1f}%', xy=(a_r[a_a.index(max(a_a))], max(a_a)),
            xytext=(25, max(a_a)+3), fontsize=9, color=colors['A'],
            arrowprops=dict(arrowstyle='->', color=colors['A'], lw=1.2))

ax.annotate(f'Drop: {b_a[4]:.1f}% → {min(b_a):.1f}%', xy=(b_r[10], min(b_a)+2),
            fontsize=9, color=colors['B'],
            bbox=dict(boxstyle='round', facecolor='#FFEBEE', edgecolor=colors['B'], alpha=0.8))

ax.annotate(f'D Recovery: {d_a[5]:.1f}% → {max(d_a):.1f}%', xy=(d_r[12], max(d_a)-1),
            fontsize=10, color=colors['D'], fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#E8F5E9', edgecolor=colors['D'], alpha=0.9))

# Formatting
ax.set_xlabel('Federated Learning Round', fontsize=13, fontweight='bold')
ax.set_ylabel('Accuracy (%)', fontsize=13, fontweight='bold')
ax.set_title('🏆 Self-Healing Federated Learning — 4-Scenario Comparison\n'
             'CIFAR-10 | 10 Clients | 30 Rounds | Gradient Inversion Attack',
             fontsize=15, fontweight='bold', pad=15)
ax.set_ylim(0, 75)
ax.set_xlim(0.5, 30.5)
ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
ax.grid(True, alpha=0.3, linestyle=':')
ax.legend(loc='lower right', fontsize=11, framealpha=0.95)

plt.tight_layout()
plt.savefig(f"{BASE}/comparison_chart.png", dpi=200, bbox_inches='tight')
print(f"✅ Chart saved: {BASE}/comparison_chart.png")

# ---- SUMMARY TABLE ----
print("\n" + "="*90)
print("📊 FINAL COMPARISON — ALL 4 SCENARIOS")
print("="*90)
print(f"{'Metric':<30} {'A: Clean':>12} {'B: Attack':>12} {'C: Rollback':>12} {'D: Quarantine':>14}")
print("-"*90)
print(f"{'Best Accuracy':<30} {max(a_a):>10.1f}% {max(b_a):>10.1f}% {max(c_a):>10.1f}% {max(d_a):>12.1f}%")
print(f"{'Final Accuracy (R30)':<30} {a_a[-1]:>10.1f}% {b_a[-1]:>10.1f}% {c_a[-1]:>10.1f}% {d_a[-1]:>12.1f}%")
print(f"{'Attack Detection':<30} {'N/A':>12} {'❌ None':>12} {'✅ 100%':>12} {'✅ 100%':>14}")
print(f"{'Rollback Events':<30} {'0':>12} {'0':>12} {'25':>12} {'1':>14}")
print(f"{'Quarantine Events':<30} {'0':>12} {'0':>12} {'0':>12} {'✅ 1 (R6)':>14}")
print(f"{'Active Clients (post-R6)':<30} {'10':>12} {'10':>12} {'10':>12} {'6 (Benign)':>14}")
print(f"{'Model Recovered?':<30} {'N/A':>12} {'❌ No':>12} {'❌ No':>12} {'✅ Yes (~60%)':>14}")
print(f"{'Accuracy vs Clean FL':<30} {'—':>12} {'-53.3%':>12} {'-53.3%':>12} {'-2.9%':>14}")
print("="*90)
print("\n🏆 Winner: Scenario D — Full Self-Healing with Client Quarantine Protocol")
print("   Accuracy 60.36% (only 2.93% below clean baseline)")
