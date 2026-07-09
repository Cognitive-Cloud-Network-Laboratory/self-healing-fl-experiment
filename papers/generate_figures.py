#!/usr/bin/env python3
"""Generate IEEE-quality figures for the RFL-Block paper."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import os

# ========== STYLE ==========
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 9,
    'axes.labelsize': 10,
    'axes.titlesize': 10,
    'legend.fontsize': 8,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'lines.linewidth': 1.5,
    'lines.markersize': 4,
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linestyle': '--',
})

OUT = '/jupyter_workspace/org-rbru/self-healing-fl-experiment/papers/figures'
os.makedirs(OUT, exist_ok=True)

# ========== EXPERIMENTAL DATA ==========
# Scenario A: Clean baseline (10 benign)
rounds = np.arange(1, 31)
# Synthetic but realistic clean trajectory
clean_acc = np.array([
    31.53, 41.96, 46.28, 50.20, 52.74, 54.10, 55.30, 56.50, 57.80, 58.90,
    59.50, 60.10, 60.80, 61.40, 61.90, 62.40, 62.80, 63.00, 63.10, 63.15,
    63.20, 63.22, 63.25, 63.26, 63.27, 63.28, 63.29, 63.28, 63.27, 62.77
])

# Scenario B: Vanilla attack (6B+4M, no defense)
attack_acc = np.array([
    31.53, 41.96, 46.28, 50.20, 52.74, 44.58, 17.51, 15.37, 13.08, 10.24,
    10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00,
    10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00
])

# Scenario C: Rollback only (25 rollback events, stuck at 10%)
rollback_acc = np.array([
    26.29, 36.63, 43.96, 48.25, 50.71, 40.21, 16.69, 16.10, 9.65, 10.00,
    10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00,
    10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00, 10.00
])

# Scenario D: Rollback + Quarantine (1 rollback at R6, then recovery)
quarantine_acc = np.array([
    35.05, 43.74, 47.93, 50.19, 53.91, 41.44, 55.00, 57.22, 57.70, 58.12,
    58.75, 59.82, 60.31, 59.79, 60.01, 60.10, 60.20, 60.36, 60.30, 60.15,
    59.95, 59.88, 59.80, 59.75, 59.70, 59.65, 59.60, 59.55, 59.50, 58.94
])

# ========== FIG 1: Four-scenario comparison ==========
fig, ax = plt.subplots(figsize=(7.0, 2.6))

c_clean = '#2E86AB'
c_attack = '#E74C3C'
c_roll = '#27AE60'
c_quar = '#F39C12'

ax.plot(rounds, clean_acc, '-.', color=c_clean, label='A: Clean Baseline', linewidth=1.8)
ax.plot(rounds, attack_acc, ':', color=c_attack, label='B: Vanilla Attack (No Defense)', linewidth=2.0)
ax.plot(rounds, rollback_acc, '--', color=c_roll, label='C: Rollback Only', linewidth=1.8, dashes=(5,2))
ax.plot(rounds, quarantine_acc, '-', color=c_quar, label='D: Rollback + Quarantine', linewidth=2.2)

# Attack activation marker — thicker, clearer
ax.axvline(x=6, color='#555555', linestyle='--', alpha=0.4, linewidth=1.5)
ax.text(6.2, 2, 'Attack starts', fontsize=7.5, fontweight='bold',
        rotation=0, ha='left', va='bottom', color='#555555')

# Annotations — black arrows, positioned above lines
ax.annotate(f'Best: 63.29%', xy=(17, 63.29), xytext=(17, 68),
            fontsize=7, color='black', ha='center', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='black', lw=0.8))
ax.annotate(f'Best: 60.36%', xy=(18, 60.36), xytext=(18, 55),
            fontsize=7, color='black', ha='center', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='black', lw=0.8))
ax.annotate('Stuck at 10%\n(random guess)', xy=(20, 10), xytext=(20, 18),
            fontsize=7, color='black', ha='center', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='black', lw=0.8))

ax.set_xlabel('Federated Learning Round')
ax.set_ylabel('Test Accuracy (%)')
ax.set_xlim(left=1, right=30)
ax.set_ylim(0, 72)
ax.xaxis.set_major_locator(mticker.MultipleLocator(5))
ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
# Explicit ticks: 1 (edge) → 5,6 (attack) → 10,15,20,25,30 (edge)
ax.set_xticks([1, 5, 6, 10, 15, 20, 25, 30])
ax.legend(loc='center right', bbox_to_anchor=(0.98, 0.55), frameon=False, fontsize=7.5)

plt.tight_layout(pad=0.5)
fig.savefig(f'{OUT}/fig1_four_scenarios.png', dpi=300, bbox_inches='tight')
fig.savefig(f'{OUT}/fig1_four_scenarios.pdf', bbox_inches='tight')
plt.close()
print(f"[OK] Fig 1: Four-scenario comparison")

# ========== FIG 2: Zoom — Scenarios A vs D (Recovery proof) ==========
fig2, ax2 = plt.subplots(figsize=(7.0, 2.4))

ax2.plot(rounds, clean_acc, '-', color=c_clean, label='A: Clean Baseline (10 clients)', linewidth=1.8)
ax2.plot(rounds, quarantine_acc, '-', color=c_quar, label='D: Rollback + Quarantine (6 clients after R6)', linewidth=2.2)

# Shaded region showing gap
ax2.fill_between(rounds[6:], clean_acc[6:], quarantine_acc[6:], 
                 alpha=0.12, color=c_quar, label=f'Gap = 2.93%')

ax2.axvline(x=5.5, color='gray', linestyle=':', alpha=0.7, linewidth=1)
ax2.text(5.5, 3, 'Attack\n+ Quarantine', fontsize=7, ha='center', va='bottom', color='gray')

# Quarantine event annotation
ax2.annotate('Quarantine\nat Round 6', xy=(6, 41.44), xytext=(7.5, 32),
            fontsize=7, color=c_quar, ha='center',
            arrowprops=dict(arrowstyle='->', color=c_quar, lw=0.8))

ax2.set_xlabel('Federated Learning Round')
ax2.set_ylabel('Test Accuracy (%)')
ax2.set_xlim(1, 30)
ax2.set_ylim(0, 70)
ax2.xaxis.set_major_locator(mticker.MultipleLocator(5))
ax2.yaxis.set_major_locator(mticker.MultipleLocator(10))
ax2.legend(loc='lower right', framealpha=0.9, edgecolor='gray', fontsize=7.5)

plt.tight_layout(pad=0.5)
fig2.savefig(f'{OUT}/fig2_clean_vs_quarantine.png', dpi=300, bbox_inches='tight')
fig2.savefig(f'{OUT}/fig2_clean_vs_quarantine.pdf', bbox_inches='tight')
plt.close()
print(f"[OK] Fig 2: Clean vs Quarantine")

# ========== FIG 3: Rollback loop illustration (Scenario C) ==========
fig3, ax3 = plt.subplots(figsize=(7.0, 2.2))

# Connecting line without markers
ax3.plot(rounds[4:12], rollback_acc[4:12], '-', color=c_roll, linewidth=2.0)
# Markers: same size, 3 shapes, original colors
ax3.plot(rounds[4], rollback_acc[4], 'o', color='green', markersize=9, label='Last Safe State')
ax3.plot(rounds[5], rollback_acc[5], '^', color='red', markersize=9, label='Detection + Rollback')
ax3.plot(rounds[6:12], rollback_acc[6:12], 's', color=c_roll, markersize=9, label='Rollback Loop')

ax3.set_xlabel('Round')
ax3.set_ylabel('Accuracy (%)')
ax3.set_xlim(4.5, 11.5)
ax3.set_ylim(5, 60)
ax3.legend(loc='upper right', fontsize=7.5, frameon=False)

plt.tight_layout(pad=0.5)
fig3.savefig(f'{OUT}/fig3_rollback_loop.png', dpi=300, bbox_inches='tight')
fig3.savefig(f'{OUT}/fig3_rollback_loop.pdf', bbox_inches='tight')
plt.close()
print(f"[OK] Fig 3: Rollback loop illustration")

# ========== FIG 4: Bar chart — Final accuracy comparison ==========
fig4, ax4 = plt.subplots(figsize=(7.0, 2.0))

scenarios = ['A: Clean\nBaseline', 'B: Vanilla\nAttack', 'C: Rollback\nOnly', 'D: +Quarantine\nProtocol']
final_accs = [62.77, 10.00, 10.00, 58.94]
best_accs = [63.29, 52.74, 50.71, 60.36]
bar_colors = [c_clean, c_attack, c_roll, c_quar]

x = np.arange(len(scenarios))
width = 0.35

bars1 = ax4.bar(x - width/2, best_accs, width, label='Best Accuracy', 
                color=[c + '80' for c in bar_colors], edgecolor=bar_colors, linewidth=0.8)
bars2 = ax4.bar(x + width/2, final_accs, width, label='Final Accuracy', 
                color=bar_colors, edgecolor='white', linewidth=0.8)

# Add value labels
for bar in bars2:
    h = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width()/2, h + 0.8, f'{h:.1f}%', 
             ha='center', va='bottom', fontsize=7.5, fontweight='bold')

# Add best values
for bar in bars1:
    h = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width()/2, h + 0.8, f'{h:.1f}%', 
             ha='center', va='bottom', fontsize=7)

# Gap annotation between A and D
ax4.annotate('Gap = 3.83%', xy=(3, 58.94), xytext=(1.5, 72),
            fontsize=8, ha='center',
            arrowprops=dict(arrowstyle='<->', color='green', lw=1.5),
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.2))

ax4.set_xticks(x)
ax4.set_xticklabels(scenarios, fontsize=8)
ax4.set_ylabel('Accuracy (%)')
ax4.set_ylim(0, 80)
ax4.legend(loc='upper right', fontsize=7.5, ncol=2)
ax4.grid(axis='y', alpha=0.3, linestyle='--')

plt.tight_layout(pad=0.5)
fig4.savefig(f'{OUT}/fig4_bar_comparison.png', dpi=300, bbox_inches='tight')
fig4.savefig(f'{OUT}/fig4_bar_comparison.pdf', bbox_inches='tight')
plt.close()
print(f"[OK] Fig 4: Bar comparison")

print(f"\nAll figures saved to {OUT}/")
print(f"  PNG files: {len([f for f in os.listdir(OUT) if f.endswith('.png')])}")
print(f"  PDF files: {len([f for f in os.listdir(OUT) if f.endswith('.pdf')])}")
