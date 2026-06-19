"""
Generate Folium traffic dashboard and EDA charts.
Run with: python -X utf8 generate_dashboard.py
"""
import sys, math, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

BASE_DIR   = Path(r'C:\hackthongrid')
OUTPUT_DIR = BASE_DIR

# Load cleaned data
print('Loading cleaned events...')
df_feat = pd.read_csv(OUTPUT_DIR / 'cleaned_events.csv', low_memory=False)
print(f'  Shape: {df_feat.shape}')

# ── Recompute congestion scores for heatmap ───────────────────────────────────
CAUSE_PTS  = {'accident':30,'water_logging':25,'protest':28,'vip_movement':26,'procession':24,'public_event':22,'construction':18,'tree_fall':16,'congestion':20,'vehicle_breakdown':12,'pot_holes':8,'road_conditions':6,'others':5,'unknown':5}
CORR_PTS   = {'ORR East 1':20,'ORR East 2':18,'CBD 1':20,'CBD 2':18,'ORR North 1':16,'ORR North 2':15,'Bellary Road 1':16,'Bellary Road 2':14,'Hosur Road':16,'Tumkur Road':14,'Mysore Road':14,'Bannerghata Road':14,'Old Madras Road':12,'West of Chord Road':12,'Magadi Road':10,'Non-corridor':4}
PRIO_PTS   = {'High':10,'Medium':6,'Low':2}

if 'congestion_score' not in df_feat.columns:
    print('  Recomputing congestion scores...')
    def _cong_row(row):
        s = CAUSE_PTS.get(str(row.get('event_cause','unknown')).lower(), 5)
        s += 20 if str(row.get('requires_road_closure',False)) in ['True','1','true'] else 0
        s += CORR_PTS.get(str(row.get('corridor','Non-corridor')), 8)
        s += PRIO_PTS.get(str(row.get('priority','Low')), 2)
        h = int(row.get('start_hour', 12)) if pd.notna(row.get('start_hour')) else 12
        s += 10 if h in [8,9,18,19] else (7 if 7<=h<=10 or 17<=h<=20 else (2 if 22<=h or h<=6 else 4))
        if int(row.get('weekday',0)) >= 5: s = int(s*0.85)
        if str(row.get('event_type','unplanned')) == 'unplanned': s += 5
        return min(100, max(0, s))
    df_feat['congestion_score'] = df_feat.apply(_cong_row, axis=1)
    print(f'  Congestion score added. Mean={df_feat["congestion_score"].mean():.1f}')

# ──────────────────────────────────────────────────────────────────────────────
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((phi2-phi1)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians((lon2-lon1)/2))**2
    return 2 * R * math.asin(math.sqrt(a))

# ── Load demo results ─────────────────────────────────────────────────────────
demo_df = pd.read_csv(OUTPUT_DIR / 'demo_results.csv')
print(f'  Demo results: {len(demo_df)} rows')

# ── 10 Scenarios (mirrored from validate_platform.py) ────────────────────────
SCENARIOS = [
    {'scenario_name':'S01 — Accident ORR','event_cause':'accident','event_type':'unplanned','requires_road_closure':True,'latitude':12.9352,'longitude':77.6900,'source_lat':12.9716,'source_lon':77.5946,'destination_lat':12.9136,'destination_lon':77.7100,'corridor':'ORR East 1','priority':'High','start_hour':8,'weekday':1,'address':'Marathahalli Junction, ORR','police_station':'HAL Old Airport'},
    {'scenario_name':'S02 — Vehicle Breakdown Hosur Rd','event_cause':'vehicle_breakdown','event_type':'unplanned','requires_road_closure':False,'latitude':12.9071,'longitude':77.6286,'source_lat':12.9352,'source_lon':77.6245,'destination_lat':12.8560,'destination_lon':77.6645,'corridor':'Hosur Road','priority':'High','start_hour':18,'weekday':3,'address':'Hosur Road, Vivekananda Circle, Bommanahalli','police_station':'Madiwala'},
    {'scenario_name':'S03 — Waterlogging Whitefield','event_cause':'water_logging','event_type':'unplanned','requires_road_closure':True,'latitude':13.0000,'longitude':77.6814,'source_lat':13.0190,'source_lon':77.6556,'destination_lat':12.9760,'destination_lon':77.7100,'corridor':'ORR East 2','priority':'High','start_hour':7,'weekday':2,'address':'Whitefield Road, ITI Underpass, Dooravani Nagar','police_station':'K.R. Pura'},
    {'scenario_name':'S04 — Protest Town Hall','event_cause':'protest','event_type':'planned','requires_road_closure':True,'latitude':12.9738,'longitude':77.5965,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':12.9600,'destination_lon':77.6020,'corridor':'CBD 1','priority':'High','start_hour':10,'weekday':4,'address':'Town Hall, Ambedkar Veedhi, Cubbon Park, Bengaluru','police_station':'Cubbon Park'},
    {'scenario_name':'S05 — VIP Movement Bellary Rd','event_cause':'vip_movement','event_type':'planned','requires_road_closure':True,'latitude':13.0000,'longitude':77.5841,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':13.0420,'destination_lon':77.5947,'corridor':'Bellary Road 1','priority':'High','start_hour':9,'weekday':0,'address':'Bellary Road, Sadashiva Nagar to Hebbal','police_station':'Sadashivanagar'},
    {'scenario_name':'S06 — Metro Construction ORR','event_cause':'construction','event_type':'planned','requires_road_closure':False,'latitude':12.9695,'longitude':77.7007,'source_lat':12.9760,'source_lon':77.6950,'destination_lat':12.9465,'destination_lon':77.6987,'corridor':'ORR East 2','priority':'High','start_hour':7,'weekday':1,'address':'Outer Ring Road, Karthik Nagar, Marathahalli Metro','police_station':'HAL Old Airport'},
    {'scenario_name':'S07 — IPL Match Chinnaswamy','event_cause':'public_event','event_type':'planned','requires_road_closure':False,'latitude':12.9793,'longitude':77.5996,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':12.9650,'destination_lon':77.6000,'corridor':'CBD 2','priority':'High','start_hour':17,'weekday':5,'address':'MG Road, Cubbon Park Area, Bengaluru','police_station':'Cubbon Park'},
    {'scenario_name':'S08 — Tree Fall Sankey Road','event_cause':'tree_fall','event_type':'unplanned','requires_road_closure':True,'latitude':13.0062,'longitude':77.5794,'source_lat':13.0190,'source_lon':77.5700,'destination_lat':12.9900,'destination_lon':77.5800,'corridor':'Bellary Road 1','priority':'Low','start_hour':20,'weekday':3,'address':'Sankey Road, Bashyam Circle, Sadashiva Nagar','police_station':'Sadashivanagar'},
    {'scenario_name':'S09 — Procession Mysore Road','event_cause':'procession','event_type':'planned','requires_road_closure':True,'latitude':12.9441,'longitude':77.5274,'source_lat':12.9600,'source_lon':77.5400,'destination_lat':12.9200,'destination_lon':77.5000,'corridor':'Mysore Road','priority':'High','start_hour':6,'weekday':6,'address':'Mysore Road, Nayandahalli Junction','police_station':'Byatarayanapura'},
    {'scenario_name':'S10 — Public Gathering Lalbagh','event_cause':'public_event','event_type':'planned','requires_road_closure':False,'latitude':12.9507,'longitude':77.5848,'source_lat':12.9600,'source_lon':77.5700,'destination_lat':12.9300,'destination_lon':77.5900,'corridor':'Non-corridor','priority':'Medium','start_hour':8,'weekday':6,'address':'Lalbagh Botanical Garden, V V Puram, Bengaluru','police_station':'V.V.Puram (C.Pet)'},
]

RISK_SCORES = {
    'S01 — Accident ORR':             {'risk':'CRITICAL','score':95,'officers':13,'barricades':18,'patrol_vehicles':4},
    'S02 — Vehicle Breakdown Hosur Rd':{'risk':'MODERATE','score':53,'officers':4,'barricades':8,'patrol_vehicles':2},
    'S03 — Waterlogging Whitefield':   {'risk':'CRITICAL','score':85,'officers':9,'barricades':13,'patrol_vehicles':2},
    'S04 — Protest Town Hall':         {'risk':'CRITICAL','score':85,'officers':26,'barricades':33,'patrol_vehicles':7},
    'S05 — VIP Movement Bellary Rd':   {'risk':'CRITICAL','score':82,'officers':22,'barricades':26,'patrol_vehicles':9},
    'S06 — Metro Construction ORR':    {'risk':'MODERATE','score':53,'officers':6,'barricades':19,'patrol_vehicles':2},
    'S07 — IPL Match Chinnaswamy':     {'risk':'MODERATE','score':48,'officers':15,'barricades':19,'patrol_vehicles':4},
    'S08 — Tree Fall Sankey Road':     {'risk':'HIGH',    'score':66,'officers':6,'barricades':12,'patrol_vehicles':2},
    'S09 — Procession Mysore Road':    {'risk':'HIGH',    'score':59,'officers':14,'barricades':20,'patrol_vehicles':3},
    'S10 — Public Gathering Lalbagh':  {'risk':'MODERATE','score':35,'officers':12,'barricades':15,'patrol_vehicles':3},
}

# ── Build Folium Map ──────────────────────────────────────────────────────────
import folium
from folium.plugins import HeatMap

print('Building Folium dashboard...')

m = folium.Map(location=[12.9716, 77.5946], zoom_start=12, tiles='CartoDB dark_matter')

layer_incidents = folium.FeatureGroup(name='🔴 Incidents', show=True)
layer_orig      = folium.FeatureGroup(name='🔵 Original Routes', show=True)
layer_alt       = folium.FeatureGroup(name='🟢 Alternate Routes', show=True)
layer_heatmap   = folium.FeatureGroup(name='🌡️ Congestion Heatmap', show=False)

RISK_COLORS = {'CRITICAL':'red','HIGH':'orange','MODERATE':'blue','LOW':'green'}

for sc in SCENARIOS:
    name = sc['scenario_name']
    lat  = sc['latitude']
    lon  = sc['longitude']
    slat, slon = sc['source_lat'], sc['source_lon']
    dlat, dlon = sc['destination_lat'], sc['destination_lon']

    res   = RISK_SCORES.get(name, {'risk':'LOW','score':30,'officers':2,'barricades':4,'patrol_vehicles':1})
    risk  = res['risk']
    score = res['score']

    # Simulated route distances
    orig_km = round(_haversine_km(slat, slon, dlat, dlon) * 1.35, 2)
    alt_km  = round(orig_km * 1.15, 2)
    extra   = round(alt_km - orig_km, 2)
    delay   = max(0, round(extra * 2.0 + 5, 1))

    mid_lat = (slat + dlat) / 2
    mid_lon = (slon + dlon) / 2
    orig_coords = [(slat, slon), (mid_lat, mid_lon), (dlat, dlon)]
    alt_coords  = [(slat, slon), (mid_lat+0.005, mid_lon+0.005), (dlat, dlon)]

    popup_html = f"""
    <div style="font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:12px;
                border-radius:8px;border:1px solid #58a6ff;min-width:290px">
        <h3 style="color:#58a6ff;margin:0 0 8px 0;font-size:13px">{name}</h3>
        <hr style="border-color:#30363d;margin:4px 0">
        <b style="color:#f78166">Risk:</b> {risk} &nbsp;
        <b>Score:</b> <span style="color:#ffa657">{score}/100</span><br>
        <b>Cause:</b> {sc['event_cause'].replace('_',' ').title()}<br>
        <b>Corridor:</b> {sc['corridor']}<br>
        <b>Priority:</b> {sc['priority']} | <b>Hour:</b> {sc['start_hour']}:00<br>
        <hr style="border-color:#30363d;margin:4px 0">
        <b style="color:#3fb950">👮 Officers:</b> {res['officers']}&emsp;
        <b>🚧 Barricades:</b> {res['barricades']}&emsp;
        <b>🚓 Vehicles:</b> {res['patrol_vehicles']}<br>
        <hr style="border-color:#30363d;margin:4px 0">
        <b>🛤️ Original:</b> {orig_km} km<br>
        <b style="color:#3fb950">🔄 Alternate:</b> {alt_km} km (+{extra} km, ~{delay} min)<br>
        <b>Engine:</b> Simulated (OSMnx in notebook)
    </div>"""

    folium.CircleMarker(
        location=[lat, lon],
        radius=14 + (score // 15),
        color=RISK_COLORS.get(risk, 'blue'),
        fill=True, fill_color=RISK_COLORS.get(risk, 'blue'),
        fill_opacity=0.75, weight=2,
        popup=folium.Popup(popup_html, max_width=330),
        tooltip=f"{name} | {risk} | {score}/100"
    ).add_to(layer_incidents)

    folium.PolyLine(orig_coords, color='#4d9de0', weight=3, opacity=0.7,
                    tooltip=f'Original: {orig_km} km').add_to(layer_orig)

    folium.PolyLine(alt_coords, color='#3fb950', weight=3, opacity=0.7, dash_array='6 3',
                    tooltip=f'Alternate: {alt_km} km (+{extra} km)').add_to(layer_alt)

    folium.Marker([slat, slon],
                  icon=folium.Icon(color='blue', icon='play', prefix='fa'),
                  tooltip=f'Start: {name}').add_to(layer_orig)

    folium.Marker([dlat, dlon],
                  icon=folium.Icon(color='green', icon='flag', prefix='fa'),
                  tooltip=f'End: {name}').add_to(layer_orig)

# Dataset heatmap
print('  Adding congestion heatmap from 8k events...')
heat_data = df_feat[['latitude','longitude','congestion_score']].dropna()
heat_data = heat_data.sample(min(2000, len(heat_data)), random_state=42)
heat_pts  = [[r['latitude'], r['longitude'], r['congestion_score']/100]
             for _, r in heat_data.iterrows()]
HeatMap(heat_pts, radius=12, blur=8, min_opacity=0.3,
        gradient={'0.4':'blue','0.65':'lime','1':'red'}).add_to(layer_heatmap)

for layer in [layer_incidents, layer_orig, layer_alt, layer_heatmap]:
    layer.add_to(m)

legend_html = """
<div style="position:fixed;bottom:30px;left:30px;z-index:9999;
            background:#0d1117;border:1px solid #30363d;border-radius:8px;
            padding:14px;font-family:monospace;color:#e6edf3;font-size:12px;box-shadow:0 4px 20px rgba(0,0,0,0.5)">
    <b style="color:#58a6ff;font-size:15px">🚦 BLR Traffic Command</b><br>
    <small style="color:#8b949e">Event-Driven Congestion Platform</small>
    <hr style="border-color:#30363d;margin:8px 0">
    <b style="color:#8b949e">RISK LEVELS</b><br>
    <span style="color:red;font-size:16px">●</span> CRITICAL (75-100)<br>
    <span style="color:orange;font-size:16px">●</span> HIGH (55-74)<br>
    <span style="color:#4d9de0;font-size:16px">●</span> MODERATE (35-54)<br>
    <span style="color:green;font-size:16px">●</span> LOW (0-34)<br>
    <hr style="border-color:#30363d;margin:8px 0">
    <b style="color:#8b949e">ROUTES</b><br>
    <span style="color:#4d9de0">━━</span> Original Route<br>
    <span style="color:#3fb950">╌╌</span> Alternate Route<br>
    <hr style="border-color:#30363d;margin:8px 0">
    <small style="color:#8b949e">Stack: OSMnx · NetworkX · Folium<br>AI: Gemini 1.5 Flash</small>
</div>"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(position='topright', collapsed=False).add_to(m)

dashboard_path = OUTPUT_DIR / 'traffic_dashboard.html'
m.save(str(dashboard_path))
sz = dashboard_path.stat().st_size // 1024
print(f'  ✅ Dashboard saved → {dashboard_path.name} ({sz:,} KB)')

# ── EDA Charts (matplotlib with Agg backend) ──────────────────────────────────
try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend — avoids DLL issues
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    plt.rcParams.update({
        'figure.facecolor': '#0d1117', 'axes.facecolor': '#0d1117',
        'axes.edgecolor': '#30363d',   'axes.labelcolor': '#e6edf3',
        'xtick.color': '#e6edf3',      'ytick.color': '#e6edf3',
        'text.color': '#e6edf3',       'grid.color': '#21262d',
    })

    print('Building EDA charts...')
    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    fig.patch.set_facecolor('#0d1117')
    fig.suptitle('Bengaluru Traffic Event — EDA Dashboard', fontsize=18,
                 color='#58a6ff', fontweight='bold', y=1.01)

    def styled_bar(ax, labels, values, title, color='#58a6ff', top_n=12):
        if len(labels) > top_n: labels, values = labels[:top_n], values[:top_n]
        colors = [color if i < 3 else '#30363d' for i in range(len(labels))]
        bars = ax.barh(range(len(labels)), values, color=colors)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_title(title, color='#e6edf3', fontsize=12, fontweight='bold')
        ax.invert_yaxis()
        for bar, val in zip(bars, values):
            ax.text(bar.get_width()+1, bar.get_y()+bar.get_height()/2,
                    f'{int(val):,}', va='center', fontsize=8, color='#e6edf3')

    # 1. Event cause
    df_raw_c = pd.read_csv(BASE_DIR / 'Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv', low_memory=False)
    df_raw_c['event_cause'] = df_raw_c['event_cause'].fillna('unknown').str.strip()
    df_raw_c['corridor']    = df_raw_c['corridor'].fillna('Non-corridor').str.strip()
    df_raw_c['priority']    = df_raw_c['priority'].fillna('Low').str.strip()
    df_raw_c['requires_road_closure'] = df_raw_c['requires_road_closure'].fillna(False)
    df_raw_c['start_datetime'] = pd.to_datetime(df_raw_c['start_datetime'], errors='coerce', utc=True)

    cause_vc = df_raw_c['event_cause'].value_counts()
    styled_bar(axes[0,0], cause_vc.index.tolist(), cause_vc.values.tolist(), 'Event Cause Distribution', '#58a6ff')

    corr_vc = df_raw_c['corridor'].value_counts()
    styled_bar(axes[0,1], corr_vc.index.tolist(), corr_vc.values.tolist(), 'Corridor Distribution', '#3fb950')

    df_raw_c['hour'] = df_raw_c['start_datetime'].dt.hour
    hourly = df_raw_c['hour'].value_counts().sort_index()
    axes[1,0].plot(hourly.index, hourly.values, color='#f78166', linewidth=2, marker='o', markersize=4)
    axes[1,0].fill_between(hourly.index, hourly.values, alpha=0.3, color='#f78166')
    axes[1,0].axvspan(7, 10, alpha=0.15, color='#ffa657', label='Morning Rush')
    axes[1,0].axvspan(17, 20, alpha=0.15, color='#d2a8ff', label='Evening Rush')
    axes[1,0].legend(fontsize=8)
    axes[1,0].set_xlabel('Hour of Day')
    axes[1,0].set_title('Hourly Event Frequency', color='#e6edf3', fontsize=12, fontweight='bold')

    prio_vc = df_raw_c['priority'].value_counts()
    axes[1,1].pie(prio_vc.values, labels=prio_vc.index,
                  colors=['#f78166','#ffa657','#3fb950','#58a6ff'][:len(prio_vc)],
                  autopct='%1.1f%%', textprops={'color':'#e6edf3'}, startangle=90)
    axes[1,1].set_title('Priority Distribution', color='#e6edf3', fontsize=12, fontweight='bold')

    df_raw_c['dow'] = df_raw_c['start_datetime'].dt.day_name()
    dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    dow_vc = df_raw_c['dow'].value_counts().reindex(dow_order, fill_value=0)
    axes[2,0].bar(range(7), dow_vc.values,
                  color=['#f78166' if d in ['Saturday','Sunday'] else '#58a6ff' for d in dow_order])
    axes[2,0].set_xticks(range(7))
    axes[2,0].set_xticklabels([d[:3] for d in dow_order])
    axes[2,0].set_title('Day-of-Week Distribution', color='#e6edf3', fontsize=12, fontweight='bold')
    axes[2,0].legend(handles=[mpatches.Patch(color='#f78166',label='Weekend'),
                               mpatches.Patch(color='#58a6ff',label='Weekday')], fontsize=8)

    rc_vc = df_raw_c['requires_road_closure'].value_counts()
    axes[2,1].bar(rc_vc.index.astype(str), rc_vc.values, color=['#3fb950','#f78166'])
    axes[2,1].set_title('Road Closure Required', color='#e6edf3', fontsize=12, fontweight='bold')
    for i, v in enumerate(rc_vc.values):
        axes[2,1].text(i, v+10, f'{v:,}', ha='center', fontsize=10, color='#e6edf3')

    plt.tight_layout()
    eda_path = OUTPUT_DIR / 'eda_dashboard.png'
    plt.savefig(eda_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    sz2 = eda_path.stat().st_size // 1024
    print(f'  ✅ EDA chart saved → {eda_path.name} ({sz2:,} KB)')
except Exception as e:
    print(f'  ⚠️ Chart generation error: {e}')

print('\n=== FINAL DELIVERABLES ===')
for label, path in [
    ('Cleaned Events Dataset', OUTPUT_DIR/'cleaned_events.csv'),
    ('EDA Dashboard PNG',      OUTPUT_DIR/'eda_dashboard.png'),
    ('Traffic Dashboard HTML', OUTPUT_DIR/'traffic_dashboard.html'),
    ('Demo Results CSV',       OUTPUT_DIR/'demo_results.csv'),
]:
    exists = path.exists()
    size   = f'{path.stat().st_size//1024:,} KB' if exists else 'NOT FOUND'
    print(f'  {"DONE" if exists else "FAIL"} {label:<35} {path.name} ({size})')

print('\nAll outputs generated!')
