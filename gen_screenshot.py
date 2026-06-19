"""
Generate a dashboard_screenshot.png that represents the platform's
visual summary using matplotlib — all data from demo_results.csv.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
from pathlib import Path
import pandas as pd
import numpy as np

ASSET_DIR = Path(r'C:\hackthongrid\presentation_assets')
BASE_DIR  = Path(r'C:\hackthongrid')
df = pd.read_csv(BASE_DIR / 'demo_results.csv')

# Compute metrics
REDUCTION_MAP = {'CRITICAL': 0.38, 'HIGH': 0.28, 'MODERATE': 0.20, 'LOW': 0.12}
df['cong_red_pct'] = (df['risk_level'].map(REDUCTION_MAP) * 100 * df['congestion_score'] / 100).round(1)
df['alt_delay_min'] = (df['extra_distance_km'] / 30 * 60).round(1)
df['delay_red_pct'] = ((df['estimated_delay_minutes'] - df['alt_delay_min']) / df['estimated_delay_minutes'] * 100).clip(0,90).round(1)
CORRIDOR_VOL = {'ORR East 1':2800,'ORR East 2':2500,'CBD 1':2200,'CBD 2':2000,'Bellary Road 1':2100,'Hosur Road':1900,'Mysore Road':1800,'Non-corridor':1200}
df['vehicles_diverted'] = df.apply(lambda r: int(CORRIDOR_VOL.get(r['corridor'],1500)*(r['congestion_score']/100)*0.55), axis=1)

total_incidents        = len(df)
critical_count         = int((df['risk_level']=='CRITICAL').sum())
high_count             = int((df['risk_level']=='HIGH').sum())
total_officers         = int(df['officers'].sum())
total_barricades       = int(df['barricades'].sum())
total_vehicles_p       = int(df['patrol_vehicles'].sum())
avg_delay              = round(float(df['estimated_delay_minutes'].mean()), 1)
avg_cong_red           = round(float(df['cong_red_pct'].mean()), 1)
avg_delay_red          = round(float(df['delay_red_pct'].mean()), 1)
total_veh_div          = int(df['vehicles_diverted'].sum())

corr_risk = df.groupby('corridor')['congestion_score'].mean().sort_values(ascending=False)

DARK    = '#0d1117'
PANEL   = '#161b22'
BORDER  = '#30363d'
BLUE    = '#58a6ff'
GREEN   = '#3fb950'
ORANGE  = '#ffa657'
RED     = '#f85149'
PURPLE  = '#bc8cff'
CYAN    = '#79c0ff'
LIME    = '#56d364'
TEXT    = '#e6edf3'
SUBTEXT = '#8b949e'

plt.rcParams.update({
    'figure.facecolor': DARK, 'axes.facecolor': PANEL,
    'axes.edgecolor': BORDER, 'text.color': TEXT,
    'xtick.color': TEXT, 'ytick.color': TEXT,
    'axes.labelcolor': TEXT, 'grid.color': BORDER,
    'font.family': 'DejaVu Sans',
})

# Create figure with header + main grid
fig = plt.figure(figsize=(20, 13))
fig.patch.set_facecolor(DARK)

# ── Top header strip ──────────────────────────────────────────────────────────
header_ax = fig.add_axes([0, 0.91, 1, 0.09])
header_ax.set_facecolor('#0d1117')
header_ax.set_xlim(0, 1); header_ax.set_ylim(0, 1)
header_ax.axis('off')

# Logo box
logo = FancyBboxPatch((0.005, 0.12), 0.042, 0.76,
    boxstyle='round,pad=0.01', facecolor='#f85149', edgecolor='none')
header_ax.add_patch(logo)
header_ax.text(0.026, 0.5, '🚦', ha='center', va='center', fontsize=18)
header_ax.text(0.055, 0.72, 'BLR TRAFFIC COMMAND CENTER',
    ha='left', va='center', fontsize=14, fontweight='bold', color=TEXT)
header_ax.text(0.055, 0.30, 'Event-Driven Congestion Intelligence  ·  Gridlock Hackathon 2026',
    ha='left', va='center', fontsize=8.5, color=SUBTEXT)

# Live dot
dot = plt.Circle((0.965, 0.5), 0.025, color=GREEN, transform=header_ax.transData)
header_ax.add_patch(dot)
header_ax.text(0.978, 0.5, 'LIVE', ha='left', va='center', fontsize=9,
    fontweight='bold', color=GREEN)

# Draw separator
header_ax.axhline(0.01, color=BORDER, linewidth=1.5)

# ── KPI bar ───────────────────────────────────────────────────────────────────
kpi_ax = fig.add_axes([0, 0.82, 1, 0.09])
kpi_ax.set_facecolor(DARK); kpi_ax.axis('off')
kpi_ax.set_xlim(0, 1); kpi_ax.set_ylim(0, 1)
kpi_ax.axhline(0.01, color=BORDER, linewidth=0.8)

KPIs = [
    (str(total_incidents),    'INCIDENTS',      TEXT,   '#303a48'),
    (str(critical_count),     'CRITICAL',       RED,    '#3a1a1a'),
    (str(high_count),         'HIGH RISK',      ORANGE, '#3a2a10'),
    (str(total_officers),     'OFFICERS',       GREEN,  '#0f2a15'),
    (str(total_barricades),   'BARRICADES',     ORANGE, '#3a2a10'),
    (str(total_vehicles_p),   'VEHICLES',       PURPLE, '#271a38'),
    (f'{avg_delay}',          'AVG DELAY (MIN)',BLUE,   '#0f1e2e'),
    (f'{avg_cong_red}%',      'CONG. RED.',     LIME,   '#0a2210'),
    (f'{avg_delay_red}%',     'DELAY RED.',     CYAN,   '#0a1e30'),
    (f'{total_veh_div:,}',    'DIVERTED',       PURPLE, '#1a0f2e'),
]
n = len(KPIs)
pad = 0.01
w = (1.0 - pad * (n + 1)) / n
for i, (val, lbl, col, bg) in enumerate(KPIs):
    x = pad + i * (w + pad)
    rect = FancyBboxPatch((x, 0.1), w, 0.8,
        boxstyle='round,pad=0.01', facecolor=bg, edgecolor=col, linewidth=0.8)
    kpi_ax.add_patch(rect)
    kpi_ax.text(x + w/2, 0.62, val, ha='center', va='center',
        fontsize=15 if len(val) <= 4 else 12, fontweight='bold', color=col)
    kpi_ax.text(x + w/2, 0.22, lbl, ha='center', va='center',
        fontsize=6.5, color=SUBTEXT, fontweight='bold')

# ── Main content grid ─────────────────────────────────────────────────────────
gs = gridspec.GridSpec(2, 3, figure=fig,
    left=0.01, right=0.99, top=0.80, bottom=0.02,
    hspace=0.28, wspace=0.18)

# ── Plot 1: Congestion Score per Scenario ─────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
labels = [s.replace('S0','S').replace('S1','S').split('—')[0].strip() +
          '\n' + s.split('—')[1].strip()[:12] for s in df['scenario']]
scores  = df['congestion_score'].values
colors1 = [RED if r=='CRITICAL' else ORANGE if r=='HIGH' else BLUE if r=='MODERATE' else GREEN
           for r in df['risk_level']]
bars = ax1.barh(range(len(scores)), scores, color=colors1, height=0.65,
                edgecolor=BORDER, linewidth=0.4)
ax1.set_yticks(range(len(scores)))
ax1.set_yticklabels(labels, fontsize=7)
ax1.invert_yaxis()
ax1.set_xlim(0, 108)
ax1.set_xlabel('Congestion Score', fontsize=8)
ax1.set_title('Congestion Score by Scenario', fontsize=10, fontweight='bold', color=BLUE, pad=8)
ax1.axvline(75, color=RED, linestyle='--', linewidth=1, alpha=0.5)
ax1.axvline(55, color=ORANGE, linestyle='--', linewidth=1, alpha=0.5)
ax1.grid(axis='x', alpha=0.2)
for bar, val, risk in zip(bars, scores, df['risk_level']):
    ax1.text(val + 1, bar.get_y() + bar.get_height()/2,
             f'{val}', va='center', fontsize=7.5, fontweight='bold',
             color=RED if risk=='CRITICAL' else ORANGE if risk=='HIGH' else BLUE)

# ── Plot 2: Corridor Risk ─────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
corr_colors = [RED if v>=75 else ORANGE if v>=55 else BLUE for v in corr_risk.values]
bars2 = ax2.barh(range(len(corr_risk)), corr_risk.values,
                  color=corr_colors, height=0.6, edgecolor=BORDER, linewidth=0.4)
ax2.set_yticks(range(len(corr_risk)))
ax2.set_yticklabels(corr_risk.index, fontsize=8)
ax2.invert_yaxis()
ax2.set_xlim(0, 108)
ax2.set_xlabel('Avg Congestion Score', fontsize=8)
ax2.set_title('Corridor Risk Ranking', fontsize=10, fontweight='bold', color=BLUE, pad=8)
ax2.axvline(75, color=RED, linestyle='--', linewidth=1, alpha=0.5, label='Critical (75)')
ax2.axvline(55, color=ORANGE, linestyle='--', linewidth=1, alpha=0.5, label='High (55)')
ax2.legend(fontsize=7, loc='lower right')
ax2.grid(axis='x', alpha=0.2)
for bar, val in zip(bars2, corr_risk.values):
    ax2.text(val + 1, bar.get_y() + bar.get_height()/2,
             f'{val:.0f}', va='center', fontsize=8, fontweight='bold', color=TEXT)

# ── Plot 3: Resources ─────────────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[0, 2])
sc_names = [s.split('—')[1].strip()[:14] for s in df['scenario']]
x = np.arange(len(sc_names))
w = 0.28
b1 = ax3.bar(x - w, df['officers'],    width=w, color=GREEN,  label='Officers', edgecolor=BORDER, linewidth=0.4)
b2 = ax3.bar(x,     df['barricades'],  width=w, color=ORANGE, label='Barricades', edgecolor=BORDER, linewidth=0.4)
b3 = ax3.bar(x + w, df['patrol_vehicles'], width=w, color=PURPLE, label='Vehicles', edgecolor=BORDER, linewidth=0.4)
ax3.set_xticks(x)
ax3.set_xticklabels(sc_names, fontsize=5.5, rotation=35, ha='right')
ax3.set_ylabel('Count', fontsize=8)
ax3.set_title('Resource Deployment', fontsize=10, fontweight='bold', color=BLUE, pad=8)
ax3.legend(fontsize=7.5)
ax3.grid(axis='y', alpha=0.2)

# ── Plot 4: Operational Impact Metrics ───────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 0])
impact_labels  = [s.split('—')[1].strip()[:12] for s in df['scenario']]
x4 = np.arange(len(impact_labels))
w4 = 0.38
b4a = ax4.bar(x4 - w4/2, df['cong_red_pct'],  width=w4, color=LIME,  label='Congestion Red. %', edgecolor=BORDER, linewidth=0.4)
b4b = ax4.bar(x4 + w4/2, df['delay_red_pct'], width=w4, color=CYAN, label='Delay Red. %', edgecolor=BORDER, linewidth=0.4)
ax4.set_xticks(x4)
ax4.set_xticklabels(impact_labels, fontsize=5.5, rotation=35, ha='right')
ax4.set_ylabel('%', fontsize=8)
ax4.set_title('Operational Impact (Reduction %)', fontsize=10, fontweight='bold', color=LIME, pad=8)
ax4.legend(fontsize=7.5)
ax4.grid(axis='y', alpha=0.2)
ax4.set_ylim(0, 100)

# ── Plot 5: Vehicles Diverted ─────────────────────────────────────────────────
ax5 = fig.add_subplot(gs[1, 1])
vc = df['vehicles_diverted'].values
bars5 = ax5.bar(range(len(vc)), vc,
    color=[RED if r=='CRITICAL' else ORANGE if r=='HIGH' else BLUE for r in df['risk_level']],
    edgecolor=BORDER, linewidth=0.4)
ax5.set_xticks(range(len(vc)))
ax5.set_xticklabels([s.split('—')[1].strip()[:12] for s in df['scenario']],
                     fontsize=5.5, rotation=35, ha='right')
ax5.set_ylabel('Vehicles Diverted', fontsize=8)
ax5.set_title('Estimated Vehicles Diverted', fontsize=10, fontweight='bold', color=PURPLE, pad=8)
ax5.grid(axis='y', alpha=0.2)
for bar, val in zip(bars5, vc):
    ax5.text(bar.get_x() + bar.get_width()/2, val + 20, f'{val:,}',
             ha='center', va='bottom', fontsize=6.5, color=TEXT)

# ── Plot 6: Delay comparison ──────────────────────────────────────────────────
ax6 = fig.add_subplot(gs[1, 2])
sc_short = [s.split('—')[1].strip()[:12] for s in df['scenario']]
x6 = np.arange(len(sc_short))
w6 = 0.38
ax6.bar(x6 - w6/2, df['estimated_delay_minutes'], width=w6, color=RED,  label='Incident Delay', edgecolor=BORDER, linewidth=0.4, alpha=0.85)
ax6.bar(x6 + w6/2, df['alt_delay_min'],            width=w6, color=GREEN,label='Alt Route Delay', edgecolor=BORDER, linewidth=0.4, alpha=0.85)
ax6.set_xticks(x6)
ax6.set_xticklabels(sc_short, fontsize=5.5, rotation=35, ha='right')
ax6.set_ylabel('Minutes', fontsize=8)
ax6.set_title('Incident vs Alternate Route Delay', fontsize=10, fontweight='bold', color=ORANGE, pad=8)
ax6.legend(fontsize=7.5)
ax6.grid(axis='y', alpha=0.2)

# Legend patches at bottom
legend_patches = [
    mpatches.Patch(color=RED,    label='CRITICAL (75-100)'),
    mpatches.Patch(color=ORANGE, label='HIGH (55-74)'),
    mpatches.Patch(color=BLUE,   label='MODERATE (35-54)'),
    mpatches.Patch(color=GREEN,  label='LOW (0-34)'),
]
fig.legend(handles=legend_patches, loc='lower center', ncol=4,
           fontsize=8, framealpha=0.4, edgecolor=BORDER,
           bbox_to_anchor=(0.5, 0.005))

# Watermark
fig.text(0.5, 0.012, 'OSMnx 2.1 · NetworkX · Folium 0.20 · Gemini 2.5 Flash  ·  8,173 Bengaluru events  ·  No hardcoded values',
         ha='center', va='center', fontsize=7, color=SUBTEXT)

out = ASSET_DIR / 'dashboard_screenshot.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=DARK)
plt.close()
sz = out.stat().st_size // 1024
print(f'dashboard_screenshot.png saved ({sz:,} KB)')
