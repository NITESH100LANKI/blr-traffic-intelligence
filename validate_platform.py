"""
Validation script for the Traffic Intelligence Platform.
Runs all core modules without OSMnx (uses simulated routing).
"""
import warnings; warnings.filterwarnings('ignore')
import os, sys, json, math, traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR   = Path(r'C:\hackthongrid')
DATA_FILE  = BASE_DIR / 'Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv'
OUTPUT_DIR = BASE_DIR

# ── CELL 3: Data Pipeline ─────────────────────────────────────────────────────
print('[CELL 3] Loading data...')
df_raw = pd.read_csv(DATA_FILE, low_memory=False)
print(f'  Raw: {df_raw.shape}')

USEFUL_COLS = ['id','event_type','latitude','longitude','endlatitude','endlongitude',
               'address','event_cause','requires_road_closure','start_datetime',
               'end_datetime','status','corridor','priority','description',
               'veh_type','police_station','zone','junction','created_date','closed_datetime']
available = [c for c in USEFUL_COLS if c in df_raw.columns]
df = df_raw[available].copy()

for col in ['latitude','longitude','endlatitude','endlongitude']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df.loc[df[col] == 0, col] = np.nan

for col in ['start_datetime','end_datetime','closed_datetime','created_date']:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)

df['event_cause'] = df['event_cause'].fillna('unknown').str.strip()
df['event_type']  = df['event_type'].fillna('unplanned').str.strip()
df['corridor']    = df['corridor'].fillna('Non-corridor').str.strip()
df['priority']    = df['priority'].fillna('Low').str.strip()
df['status']      = df['status'].fillna('unknown').str.strip()
df = df.dropna(axis=1, how='all')
df_geo = df.dropna(subset=['latitude','longitude']).copy()
print(f'  Working: {df.shape}  Geo-valid: {df_geo.shape}')
assert df_geo.shape[0] > 1000, "Too few valid geo rows"

# ── CELL 5: Feature Engineering ───────────────────────────────────────────────
print('[CELL 5] Feature engineering...')
df_feat = df_geo.copy()
df_feat['start_hour'] = df_feat['start_datetime'].dt.hour.fillna(12).astype(int)
df_feat['weekday']    = df_feat['start_datetime'].dt.weekday.fillna(0).astype(int)
df_feat['month']      = df_feat['start_datetime'].dt.month.fillna(1).astype(int)
df_feat['is_weekend'] = (df_feat['weekday'] >= 5).astype(int)
df_feat['rush_hour']  = df_feat['start_hour'].apply(lambda h: 1 if (7<=h<=10) or (17<=h<=20) else 0)
df_feat['peak_hour']  = df_feat['start_hour'].apply(lambda h: 1 if h in [8,9,18,19] else 0)
df_feat['night_time'] = df_feat['start_hour'].apply(lambda h: 1 if h>=22 or h<=6 else 0)

def compute_duration(row):
    try:
        if pd.notna(row.get('closed_datetime')) and pd.notna(row.get('start_datetime')):
            delta = (row['closed_datetime'] - row['start_datetime']).total_seconds() / 60
            return max(0, delta) if delta < 1440 else np.nan
    except:
        pass
    return np.nan

df_feat['event_duration_mins'] = df_feat.apply(compute_duration, axis=1)

HIGH_RISK = {
    'ORR East 1':9,'ORR East 2':8,'ORR North 1':8,'ORR North 2':7,
    'CBD 1':9,'CBD 2':9,'Bellary Road 1':8,'Bellary Road 2':7,
    'Hosur Road':8,'Tumkur Road':7,'Mysore Road':7,'Bannerghata Road':7,
    'Old Madras Road':7,'Magadi Road':6,'West of Chord Road':6,'Non-corridor':3,
}
df_feat['corridor_risk_score'] = df_feat['corridor'].map(HIGH_RISK).fillna(5)

CAUSE_SEV = {
    'accident':9,'vehicle_breakdown':5,'water_logging':7,'construction':6,
    'protest':8,'vip_movement':8,'public_event':7,'tree_fall':6,'procession':7,
    'congestion':8,'pot_holes':4,'road_conditions':4,'others':3,'unknown':3,
}
df_feat['cause_severity']  = df_feat['event_cause'].map(CAUSE_SEV).fillna(4)
df_feat['priority_score']  = df_feat['priority'].map({'High':3,'Medium':2,'Low':1}).fillna(1)
df_feat['closure_flag']    = df_feat['requires_road_closure'].astype(int)
df_feat['impact_score']    = (
    df_feat['cause_severity']       * 0.40 +
    df_feat['corridor_risk_score']  * 0.30 +
    df_feat['priority_score']       * 0.30 +
    df_feat['rush_hour']            * 0.10 * 10 +
    df_feat['closure_flag']         * 0.10 * 10
).clip(0,10).round(2)

cause_counts = df_feat['event_cause'].value_counts(normalize=True)*100
cause_norm   = (cause_counts - cause_counts.min())/(cause_counts.max()-cause_counts.min()+1e-9)*10
df_feat['cause_frequency_score'] = df_feat['event_cause'].map(cause_norm).fillna(5)

clean_path = OUTPUT_DIR / 'cleaned_events.csv'
df_feat.to_csv(clean_path, index=False)
print(f'  Features: {df_feat.shape}')
print(f'  Impact score mean: {df_feat["impact_score"].mean():.2f}')
print(f'  Saved: {clean_path.name}')

# ── CELL 6: Congestion Engine ─────────────────────────────────────────────────
print('[CELL 6] Congestion engine...')

def compute_congestion_score(event: dict) -> dict:
    score = 0
    cause_pts = {
        'accident':30,'water_logging':25,'protest':28,'vip_movement':26,
        'procession':24,'public_event':22,'construction':18,'tree_fall':16,
        'congestion':20,'vehicle_breakdown':12,'pot_holes':8,'road_conditions':6,
        'others':5,'unknown':5,
    }
    cause = str(event.get('event_cause','unknown')).lower()
    score += cause_pts.get(cause, 5)
    if event.get('requires_road_closure') in [True,'True','true',1,'1']:
        score += 20
    corridor_pts = {
        'ORR East 1':20,'ORR East 2':18,'CBD 1':20,'CBD 2':18,
        'ORR North 1':16,'ORR North 2':15,'Bellary Road 1':16,
        'Bellary Road 2':14,'Hosur Road':16,'Tumkur Road':14,
        'Mysore Road':14,'Bannerghata Road':14,'Old Madras Road':12,
        'West of Chord Road':12,'Magadi Road':10,'Non-corridor':4,
    }
    score += corridor_pts.get(str(event.get('corridor','Non-corridor')), 8)
    score += {'High':10,'Medium':6,'Low':2}.get(str(event.get('priority','Low')), 2)
    hour = int(event.get('start_hour', 12))
    if hour in [8,9,18,19]:              score += 10
    elif 7<=hour<=10 or 17<=hour<=20:    score += 7
    elif 22<=hour or hour<=6:            score += 2
    else:                                score += 4
    if int(event.get('weekday', 0)) >= 5:
        score = int(score * 0.85)
    if str(event.get('event_type','unplanned')) == 'unplanned':
        score += 5
    score = min(100, max(0, score))
    if   score >= 75: risk = 'CRITICAL'
    elif score >= 55: risk = 'HIGH'
    elif score >= 35: risk = 'MODERATE'
    else:             risk = 'LOW'
    return {
        'congestion_score': score,
        'risk_level':       risk,
        'severity_category':{'CRITICAL':'Gridlock','HIGH':'Severe','MODERATE':'Moderate','LOW':'Minor'}[risk],
        'response_urgency': {'CRITICAL':'IMMEDIATE','HIGH':'URGENT','MODERATE':'STANDARD','LOW':'ROUTINE'}[risk],
    }

cong_results = df_feat.apply(lambda r: compute_congestion_score(r.to_dict()), axis=1)
cong_df = pd.DataFrame(cong_results.tolist())
df_feat = pd.concat([df_feat.reset_index(drop=True), cong_df], axis=1)
print(f'  Risk distribution:')
print(df_feat['risk_level'].value_counts().to_string())

# ── CELL 7: Resource Recommender ──────────────────────────────────────────────
print('[CELL 7] Resource recommender...')

def recommend_resources(event: dict) -> dict:
    cause    = str(event.get('event_cause','unknown')).lower()
    priority = str(event.get('priority','Low'))
    corridor = str(event.get('corridor','Non-corridor'))
    closure  = event.get('requires_road_closure',False) in [True,'True','true',1,'1']
    hour     = int(event.get('start_hour',12))
    rush     = (7<=hour<=10) or (17<=hour<=20)
    is_corr  = corridor not in ['Non-corridor','NULL','','nan']

    configs = {
        'accident':         {'officers':6,  'barricades':8,  'patrol_vehicles':2,  'plan':'Cordon zone, tow coordination.'},
        'vehicle_breakdown':{'officers':2,  'barricades':4,  'patrol_vehicles':1,  'plan':'Barricade, tow truck within 30min.'},
        'water_logging':    {'officers':4,  'barricades':6,  'patrol_vehicles':1,  'plan':'Block entry, BWSSB/BBMP drainage.'},
        'construction':     {'officers':3,  'barricades':10, 'patrol_vehicles':1,  'plan':'Channelized lane, speed monitoring.'},
        'protest':          {'officers':12, 'barricades':15, 'patrol_vehicles':3,  'plan':'Perimeter barricades, PCR vans.'},
        'vip_movement':     {'officers':10, 'barricades':12, 'patrol_vehicles':4,  'plan':'Pilot escort, junction officers.'},
        'public_event':     {'officers':8,  'barricades':10, 'patrol_vehicles':2,  'plan':'Parking zones, crowd management.'},
        'tree_fall':        {'officers':3,  'barricades':6,  'patrol_vehicles':1,  'plan':'Block lane, BBMP clearance.'},
        'procession':       {'officers':8,  'barricades':12, 'patrol_vehicles':2,  'plan':'Escort, upstream diversion.'},
        'congestion':       {'officers':4,  'barricades':4,  'patrol_vehicles':1,  'plan':'Manual signal, contraflow assess.'},
        'pot_holes':        {'officers':1,  'barricades':4,  'patrol_vehicles':0,  'plan':'Warning signs, BBMP repair.'},
        'others':           {'officers':2,  'barricades':3,  'patrol_vehicles':1,  'plan':'Standard protocols.'},
    }
    cfg  = configs.get(cause, configs['others']).copy()
    mult = 1.0
    if rush:           mult += 0.5
    if closure:        mult += 0.3
    if is_corr:        mult += 0.2
    if priority=='High': mult += 0.2

    cong = compute_congestion_score(event)
    sc   = cong['congestion_score']
    if   sc >= 75: div = 'IMMEDIATE — Activate alternate routes NOW'
    elif sc >= 55: div = 'HIGH — Divert within 10 minutes'
    elif sc >= 35: div = 'MODERATE — Prepare alternate routes'
    else:          div = 'LOW — Monitor and stand by'

    return {
        'risk_level':        cong['risk_level'],
        'congestion_score':  sc,
        'severity_category': cong['severity_category'],
        'officers':          max(1, round(cfg['officers']        * mult)),
        'barricades':        max(2, round(cfg['barricades']      * mult)),
        'patrol_vehicles':   max(0, round(cfg['patrol_vehicles'] * mult)),
        'diversion_urgency': div,
        'action_plan':       cfg['plan'],
        'response_urgency':  cong['response_urgency'],
    }

test_ev = {
    'event_cause':'accident','requires_road_closure':True,
    'corridor':'ORR East 1','priority':'High',
    'start_hour':8,'weekday':2,'event_type':'unplanned'
}
r = recommend_resources(test_ev)
print(f'  Test OK: {r["risk_level"]} score={r["congestion_score"]} '
      f'officers={r["officers"]} barricades={r["barricades"]} vehicles={r["patrol_vehicles"]}')

# ── CELL 9: Simulated Routing ─────────────────────────────────────────────────
print('[CELL 9] Routing engine (simulated fallback)...')

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def generate_alternate_route(source_lat, source_lon, destination_lat, destination_lon,
                              blocked_lat=None, blocked_lon=None, block_radius_m=150) -> dict:
    straight = _haversine_km(source_lat, source_lon, destination_lat, destination_lon)
    orig_km  = round(straight * 1.35, 2)
    alt_km   = round(orig_km  * 1.15, 2)
    extra    = round(alt_km - orig_km, 2)
    delay    = max(0, round(extra * 2.0 + 5, 1))
    mid_lat  = (source_lat + destination_lat) / 2
    mid_lon  = (source_lon + destination_lon) / 2
    return {
        'original_route_coords':  [(source_lat, source_lon), (mid_lat, mid_lon), (destination_lat, destination_lon)],
        'alternate_route_coords': [(source_lat, source_lon), (mid_lat+0.005, mid_lon+0.005), (destination_lat, destination_lon)],
        'original_distance_km':   orig_km,
        'alternate_distance_km':  alt_km,
        'extra_distance_km':      extra,
        'estimated_delay_minutes':delay,
        'route_found':            True,
        'routing_engine':         'Simulated',
        'diversion_recommendation': f'[SIMULATED] Alternate +{extra}km (~{delay}min). Officers at upstream junction.',
        'warnings':               ['No OSMnx graph in validation mode — using simulated route'],
    }

rte = generate_alternate_route(12.9716, 77.5946, 12.9352, 77.6245)
print(f'  Orig: {rte["original_distance_km"]}km | Alt: {rte["alternate_distance_km"]}km | Extra: {rte["extra_distance_km"]}km')

# ── AI Fallback ───────────────────────────────────────────────────────────────
def generate_incident_report(event, resources, route):
    cause = event.get('event_cause','unknown').replace('_',' ').title()
    text  = f"""BENGALURU TRAFFIC POLICE — INCIDENT REPORT
Date/Time  : {datetime.now().strftime('%d %B %Y, %H:%M IST')}
Incident   : {cause} at {event.get('address', event.get('police_station','Unknown'))}
Risk Level : {resources.get('risk_level')} (Score: {resources.get('congestion_score')}/100)

RESOURCES: Officers={resources.get('officers')} | Barricades={resources.get('barricades')} | Vehicles={resources.get('patrol_vehicles')}
ROUTING  : Original={route.get('original_distance_km')}km → Alternate={route.get('alternate_distance_km')}km (+{route.get('extra_distance_km')}km, ~{route.get('estimated_delay_minutes')}min)
ACTION   : {resources.get('action_plan')}
STATUS   : Active | Response: {resources.get('response_urgency')}
"""
    return {'report_text':text,'generated_by':'fallback-template',
            'incident_id':f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'risk_level':resources.get('risk_level'),'congestion_score':resources.get('congestion_score')}

def generate_public_advisory(event, resources, route):
    cause = event.get('event_cause','unknown').replace('_',' ').title()
    delay = route.get('estimated_delay_minutes', 10)
    text  = f"""🚦 TRAFFIC ADVISORY — BENGALURU TRAFFIC POLICE
⚠️  {cause} at {event.get('address', event.get('police_station','Bengaluru'))}
Risk: {resources.get('risk_level')} | Delay: ~{delay} min
🔁 {route.get('diversion_recommendation','Use alternate routes.')}
✅ Avoid area for {int(delay)+15}min | Follow officer directions | Call 100/112
⏰ {datetime.now().strftime('%d %b %Y %H:%M IST')}
"""
    return {'advisory_text':text,'generated_by':'fallback-template',
            'severity':resources.get('risk_level'),'delay_minutes':delay}

# ── CELL 12: Run 10 Scenarios ─────────────────────────────────────────────────
print('[CELL 12] Running 10 demo scenarios...')
SCENARIOS = [
    {'scenario_name':'S01 — Accident ORR','event_cause':'accident','event_type':'unplanned','requires_road_closure':True,'latitude':12.9352,'longitude':77.6900,'source_lat':12.9716,'source_lon':77.5946,'destination_lat':12.9136,'destination_lon':77.7100,'corridor':'ORR East 1','priority':'High','start_hour':8,'weekday':1,'address':'Marathahalli Junction, ORR','police_station':'HAL Old Airport'},
    {'scenario_name':'S02 — Vehicle Breakdown Hosur Rd','event_cause':'vehicle_breakdown','event_type':'unplanned','requires_road_closure':False,'latitude':12.9071,'longitude':77.6286,'source_lat':12.9352,'source_lon':77.6245,'destination_lat':12.8560,'destination_lon':77.6645,'corridor':'Hosur Road','priority':'High','start_hour':18,'weekday':3,'address':'Hosur Road, Vivekananda Circle, Bommanahalli','police_station':'Madiwala'},
    {'scenario_name':'S03 — Waterlogging Whitefield','event_cause':'water_logging','event_type':'unplanned','requires_road_closure':True,'latitude':13.0000,'longitude':77.6814,'source_lat':13.0190,'source_lon':77.6556,'destination_lat':12.9760,'destination_lon':77.7100,'corridor':'ORR East 2','priority':'High','start_hour':7,'weekday':2,'address':'Whitefield Road, ITI Underpass, Dooravani Nagar','police_station':'K.R. Pura'},
    {'scenario_name':'S04 — Protest Town Hall','event_cause':'protest','event_type':'planned','requires_road_closure':True,'latitude':12.9738,'longitude':77.5965,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':12.9600,'destination_lon':77.6020,'corridor':'CBD 1','priority':'High','start_hour':10,'weekday':4,'address':'Town Hall, Ambedkar Veedhi, Cubbon Park','police_station':'Cubbon Park'},
    {'scenario_name':'S05 — VIP Movement Bellary Rd','event_cause':'vip_movement','event_type':'planned','requires_road_closure':True,'latitude':13.0000,'longitude':77.5841,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':13.0420,'destination_lon':77.5947,'corridor':'Bellary Road 1','priority':'High','start_hour':9,'weekday':0,'address':'Bellary Road, Sadashiva Nagar to Hebbal','police_station':'Sadashivanagar'},
    {'scenario_name':'S06 — Metro Construction ORR','event_cause':'construction','event_type':'planned','requires_road_closure':False,'latitude':12.9695,'longitude':77.7007,'source_lat':12.9760,'source_lon':77.6950,'destination_lat':12.9465,'destination_lon':77.6987,'corridor':'ORR East 2','priority':'High','start_hour':7,'weekday':1,'address':'Outer Ring Road, Karthik Nagar, Marathahalli','police_station':'HAL Old Airport'},
    {'scenario_name':'S07 — IPL Match Chinnaswamy','event_cause':'public_event','event_type':'planned','requires_road_closure':False,'latitude':12.9793,'longitude':77.5996,'source_lat':12.9850,'source_lon':77.5988,'destination_lat':12.9650,'destination_lon':77.6000,'corridor':'CBD 2','priority':'High','start_hour':17,'weekday':5,'address':'MG Road, Cubbon Park Area, Bengaluru','police_station':'Cubbon Park'},
    {'scenario_name':'S08 — Tree Fall Sankey Road','event_cause':'tree_fall','event_type':'unplanned','requires_road_closure':True,'latitude':13.0062,'longitude':77.5794,'source_lat':13.0190,'source_lon':77.5700,'destination_lat':12.9900,'destination_lon':77.5800,'corridor':'Bellary Road 1','priority':'Low','start_hour':20,'weekday':3,'address':'Sankey Road, Bashyam Circle, Sadashiva Nagar','police_station':'Sadashivanagar'},
    {'scenario_name':'S09 — Procession Mysore Road','event_cause':'procession','event_type':'planned','requires_road_closure':True,'latitude':12.9441,'longitude':77.5274,'source_lat':12.9600,'source_lon':77.5400,'destination_lat':12.9200,'destination_lon':77.5000,'corridor':'Mysore Road','priority':'High','start_hour':6,'weekday':6,'address':'Mysore Road, Nayandahalli Junction','police_station':'Byatarayanapura'},
    {'scenario_name':'S10 — Public Gathering Lalbagh','event_cause':'public_event','event_type':'planned','requires_road_closure':False,'latitude':12.9507,'longitude':77.5848,'source_lat':12.9600,'source_lon':77.5700,'destination_lat':12.9300,'destination_lon':77.5900,'corridor':'Non-corridor','priority':'Medium','start_hour':8,'weekday':6,'address':'Lalbagh Botanical Garden, V V Puram','police_station':'V.V.Puram (C.Pet)'},
]

demo_results = []
for sc in SCENARIOS:
    try:
        ev   = sc.copy()
        cong = compute_congestion_score(ev)
        ev.update(cong)
        res  = recommend_resources(ev)
        rte  = generate_alternate_route(
            ev.get('source_lat', ev['latitude']),
            ev.get('source_lon', ev['longitude']),
            ev.get('destination_lat', 12.9352),
            ev.get('destination_lon', 77.6245),
            blocked_lat=ev['latitude'],
            blocked_lon=ev['longitude'],
        )
        inc  = generate_incident_report(ev, res, rte)
        adv  = generate_public_advisory(ev, res, rte)
        demo_results.append({
            'scenario_name':sc['scenario_name'],'event':ev,'congestion':cong,
            'resources':res,'route':rte,'incident_report':inc,'public_advisory':adv
        })
        print(f'  ✅ {sc["scenario_name"][:40]:<40} | '
              f'{cong["risk_level"]:<8} ({cong["congestion_score"]:>3}/100) | '
              f'Officers={res["officers"]:>2} Barricades={res["barricades"]:>2} | '
              f'+{rte["extra_distance_km"]}km')
    except Exception as e:
        print(f'  ❌ {sc["scenario_name"]}: {e}')
        traceback.print_exc()

# ── CELL 14: CSV Export ───────────────────────────────────────────────────────
print('\n[CELL 14] Exporting CSV...')
rows = []
for result in demo_results:
    ev, res, rte = result['event'], result['resources'], result['route']
    inc, adv     = result['incident_report'], result['public_advisory']
    rows.append({
        'scenario':               result['scenario_name'],
        'event_cause':            ev.get('event_cause'),
        'corridor':               ev.get('corridor'),
        'priority':               ev.get('priority'),
        'hour':                   ev.get('start_hour'),
        'requires_road_closure':  ev.get('requires_road_closure'),
        'congestion_score':       res.get('congestion_score'),
        'risk_level':             res.get('risk_level'),
        'severity_category':      res.get('severity_category'),
        'response_urgency':       res.get('response_urgency'),
        'officers':               res.get('officers'),
        'barricades':             res.get('barricades'),
        'patrol_vehicles':        res.get('patrol_vehicles'),
        'diversion_urgency':      res.get('diversion_urgency'),
        'routing_engine':         rte.get('routing_engine'),
        'route_found':            rte.get('route_found'),
        'original_distance_km':   rte.get('original_distance_km'),
        'alternate_distance_km':  rte.get('alternate_distance_km'),
        'extra_distance_km':      rte.get('extra_distance_km'),
        'estimated_delay_minutes':rte.get('estimated_delay_minutes'),
        'diversion_recommendation':str(rte.get('diversion_recommendation',''))[:200],
        'incident_report':        str(inc.get('report_text',''))[:300],
        'public_advisory':        str(adv.get('advisory_text',''))[:300],
        'ai_engine':              inc.get('generated_by'),
    })

demo_df = pd.DataFrame(rows)
csv_path = OUTPUT_DIR / 'demo_results.csv'
demo_df.to_csv(csv_path, index=False)
print(f'  Saved demo_results.csv ({len(demo_df)} rows, {len(demo_df.columns)} cols)')

# ── CELL 15: Summary ──────────────────────────────────────────────────────────
print('\n' + '='*100)
print('  FINAL SUMMARY TABLE')
print('='*100)
summary = demo_df[['scenario','risk_level','congestion_score','officers','barricades',
                   'patrol_vehicles','route_found','extra_distance_km','diversion_urgency']].copy()
summary.columns = ['Scenario','Risk','Score','Officers','Barricades','Vehicles','Route?','Extra km','Diversion']
print(summary.to_string(index=False))
print('='*100)

# Readiness
checks = {
    'Data Pipeline':             True,
    'Feature Engineering':       'impact_score' in df_feat.columns,
    'Congestion Engine':         'congestion_score' in df_feat.columns,
    'Resource Recommender':      True,
    'Simulated Routing':         True,
    '10 Demo Scenarios':         len(demo_results) == 10,
    'Demo Results CSV':          csv_path.exists(),
    'Cleaned Dataset CSV':       (OUTPUT_DIR/'cleaned_events.csv').exists(),
}
passed = sum(v for v in checks.values())
total  = len(checks)
score  = round(passed/total*10, 1)
print(f'\n  {"Component":<40} Status')
print(f'  {"-"*40} ------')
for k, v in checks.items():
    print(f'  {k:<40} {"✅" if v else "❌"}')
print(f'\n  READINESS SCORE: {score}/10 ({passed}/{total} passed)')
print('\n✅ Validation complete!')

# ── CELL 16: Sample report ────────────────────────────────────────────────────
if demo_results:
    r = demo_results[0]
    print('\n' + '-'*70)
    print(f'SAMPLE INCIDENT REPORT — {r["scenario_name"]}')
    print('-'*70)
    print(r['incident_report']['report_text'])
    print('\nSAMPLE PUBLIC ADVISORY:')
    print(r['public_advisory']['advisory_text'])
