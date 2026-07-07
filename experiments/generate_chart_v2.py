#!/usr/bin/env python3
"""Generate comparison chart — ASCII-safe version"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import csv

BASE = "/root/fl-project"

def read_csv(path):
    rounds, accs = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rounds.append(int(row['Round']))
            accs.append(float(row['Accuracy']) * 100)
    return rounds, accs

a_r, a_a = read_csv(f"{BASE}/scenario_a/evaluation_metrics.csv")
b_r, b_a = read_csv(f"{BASE}/scenario_b/evaluation_metrics.csv")
c_r, c_a = read_csv(f"{BASE}/scenario_c/evaluation_metrics.csv")
d_r, d_a = read_csv(f"{BASE}/scenario_d/evaluation_metrics.csv")

fig, ax = plt.subplots(figsize=(16, 10))

colors = {'A': '#1565C0', 'B': '#C62828', 'C': '#E65100', 'D': '#2E7D32'}
# Plot
ax.plot(a_r, a_a, color=colors['A'], linewidth=3, marker='o', markersize=4,
        label='A: Clean FL (10 Benign)')
ax.plot(b_r, b_a, color=colors['B'], linewidth=2.5, linestyle='--', marker='s', markersize=4,
        label='B: Vanilla FL under Attack (No Defense)')
ax.plot(c_r, c_a, color=colors['C'], linewidth=2, linestyle=':', marker='^', markersize=4,
        label='C: Naive Self-Healing (Rollback Only)')
ax.plot(d_r, d_a, color=colors['D'], linewidth=3.5, marker='D', markersize=5,
        label='D: Full Self-Healing + Client Quarantine')

# Attack zone
ax.axvspan(5.5, 30.5, alpha=0.06, color='red')
ax.axvline(x=5.5, color='red', linestyle='--', alpha=0.4, linewidth=1)
ax.text(5.5, 72, 'Gradient Inversion Attack Starts (Round 6)', fontsize=10,
        color='red', ha='center', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='red', alpha=0.8))

# Quarantine marker
ax.axvline(x=6.5, color='#2E7D32', linestyle='--', alpha=0.6, linewidth=2)
ax.text(6.5, 18, 'Quarantine (Round 6)\n[4 Malicious Removed]', fontsize=10,
        color='#2E7D32', ha='center', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#E8F5E9', edgecolor='#2E7D32', alpha=0.9))

# Annotations
ax.annotate(f'Peak: {max(a_a):.1f}%', xy=(a_r[a_a.index(max(a_a))], max(a_a)),
            xytext=(24, max(a_a)+3), fontsize=9, color=colors['A'],
            arrowprops=dict(arrowstyle='->', color=colors['A'], lw=1.2))

ax.annotate(f'Freefall: {b_a[4]:.1f}% -> {b_a[10]:.1f}%', xy=(b_r[10], b_a[10]+2),
            fontsize=10, color=colors['B'], fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#FFEBEE', edgecolor=colors['B'], alpha=0.8))

ax.annotate(f'Recovery: {d_a[5]:.1f}% -> {max(d_a):.1f}%', xy=(d_r[12], max(d_a)-1),
            fontsize=11, color=colors['D'], fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#E8F5E9', edgecolor=colors['D'], alpha=0.9))

ax.annotate(f'C stays at 10%', xy=(c_r[20], c_a[20]),
            fontsize=10, color=colors['C'], fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#FFF3E0', edgecolor=colors['C'], alpha=0.8))

# Formatting
ax.set_xlabel('Federated Learning Round', fontsize=14, fontweight='bold')
ax.set_ylabel('Test Accuracy (%)', fontsize=14, fontweight='bold')
ax.set_title('Self-Healing Federated Learning - 4-Scenario Comparison\n'
             'CIFAR-10 | 10 Clients (6 Benign + 4 Malicious) | 30 Rounds',
             fontsize=16, fontweight='bold', pad=15)
ax.set_ylim(0, 75)
ax.set_xlim(0.5, 30.5)
ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
ax.grid(True, alpha=0.3, linestyle=':')
ax.legend(loc='lower right', fontsize=12, framealpha=0.95,
          shadow=True, fancybox=True)

plt.tight_layout()
plt.savefig(f"{BASE}/fl_comparison_4_scenarios.png", dpi=200, bbox_inches='tight')
print(f"Done: {BASE}/fl_comparison_4_scenarios.png")
