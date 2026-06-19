"""
real_routing_engine.py
======================
OSMnx + NetworkX multi-route intelligence for all 10 scenarios.

For every incident, generates 3 candidate routes:
  1. FASTEST      – minimise travel time (speed-aware edge weights)
  2. LEAST_TRAFFIC – minimise congestion exposure (avoid blocked/high-risk zones)
  3. BALANCED     – trade off travel time + congestion exposure

Each route carries:
  - route_km          : road-network distance (km)
  - travel_min        : estimated travel time (min)
  - congestion_score  : exposure score (0-100, lower = safer)
  - risky_corridors   : count of high-risk corridor edges crossed
  - extra_km          : extra vs shortest possible path
  - label             : human-readable route tag
  - why               : one-line explanation

Usage (standalone test):
    python -X utf8 real_routing_engine.py

Usage (from enhance_dashboard.py):
    from real_routing_engine import load_graph, get_multi_routes_for_scenarios
"""
import sys, math, warnings, itertools
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any
warnings.filterwarnings('ignore')

import networkx as nx

BASE_DIR   = Path(r'C:\hackthongrid')
CACHE_PATH = BASE_DIR / 'bengaluru_drive.graphml'

# ── Speed table: OSM highway type → typical speed (km/h) ─────────────────────
HIGHWAY_SPEED = {
    'motorway': 80, 'motorway_link': 60,
    'trunk': 60,    'trunk_link': 50,
    'primary': 50,  'primary_link': 40,
    'secondary': 40,'secondary_link': 30,
    'tertiary': 30, 'tertiary_link': 25,
    'unclassified': 25,
    'residential': 20,
    'living_street': 10,
    'service': 15,
    'road': 25,
}

# ── High-risk corridor keyword matches ───────────────────────────────────────
RISKY_ROAD_KEYWORDS = [
    'outer ring', 'orr', 'mg road', 'bellary', 'hosur', 'mysore',
    'whitefield', 'bannerghatta', 'tumkur', 'old madras', 'sankey',
    'lalbagh', 'town hall', 'cubbon', 'marathahalli', 'hebbal',
]

# ── Scenario definitions ──────────────────────────────────────────────────────
SCENARIOS = [
    {
        'id': 'S01', 'name': 'S01 — Accident ORR',
        'source_lat': 12.9716, 'source_lon': 77.5946,
        'dest_lat':   12.9136, 'dest_lon':   77.7100,
        'incident_lat': 12.9352, 'incident_lon': 77.6900,
        'requires_closure': True,  'blockage_radius_m': 400,
        'corridor': 'ORR East 1',
        'event_cause': 'accident',
    },
    {
        'id': 'S02', 'name': 'S02 — Vehicle Breakdown Hosur Rd',
        'source_lat': 12.9352, 'source_lon': 77.6245,
        'dest_lat':   12.8560, 'dest_lon':   77.6645,
        'incident_lat': 12.9071, 'incident_lon': 77.6286,
        'requires_closure': False, 'blockage_radius_m': 0,
        'corridor': 'Hosur Road',
        'event_cause': 'vehicle_breakdown',
    },
    {
        'id': 'S03', 'name': 'S03 — Waterlogging Whitefield',
        'source_lat': 13.0190, 'source_lon': 77.6556,
        'dest_lat':   12.9760, 'dest_lon':   77.7100,
        'incident_lat': 13.0000, 'incident_lon': 77.6814,
        'requires_closure': True,  'blockage_radius_m': 300,
        'corridor': 'ORR East 2',
        'event_cause': 'water_logging',
    },
    {
        'id': 'S04', 'name': 'S04 — Protest Town Hall',
        'source_lat': 12.9850, 'source_lon': 77.5988,
        'dest_lat':   12.9600, 'dest_lon':   77.6020,
        'incident_lat': 12.9738, 'incident_lon': 77.5965,
        'requires_closure': True,  'blockage_radius_m': 500,
        'corridor': 'CBD 1',
        'event_cause': 'protest',
    },
    {
        'id': 'S05', 'name': 'S05 — VIP Movement Bellary Rd',
        'source_lat': 12.9850, 'source_lon': 77.5988,
        'dest_lat':   13.0420, 'dest_lon':   77.5947,
        'incident_lat': 13.0000, 'incident_lon': 77.5841,
        'requires_closure': True,  'blockage_radius_m': 400,
        'corridor': 'Bellary Road 1',
        'event_cause': 'vip_movement',
    },
    {
        'id': 'S06', 'name': 'S06 — Metro Construction ORR',
        'source_lat': 12.9760, 'source_lon': 77.6950,
        'dest_lat':   12.9465, 'dest_lon':   77.6987,
        'incident_lat': 12.9695, 'incident_lon': 77.7007,
        'requires_closure': False, 'blockage_radius_m': 0,
        'corridor': 'ORR East 2',
        'event_cause': 'construction',
    },
    {
        'id': 'S07', 'name': 'S07 — IPL Match Chinnaswamy',
        'source_lat': 12.9850, 'source_lon': 77.5988,
        'dest_lat':   12.9650, 'dest_lon':   77.6000,
        'incident_lat': 12.9793, 'incident_lon': 77.5996,
        'requires_closure': False, 'blockage_radius_m': 0,
        'corridor': 'CBD 2',
        'event_cause': 'public_event',
    },
    {
        'id': 'S08', 'name': 'S08 — Tree Fall Sankey Road',
        'source_lat': 13.0190, 'source_lon': 77.5700,
        'dest_lat':   12.9900, 'dest_lon':   77.5800,
        'incident_lat': 13.0062, 'incident_lon': 77.5794,
        'requires_closure': True,  'blockage_radius_m': 200,
        'corridor': 'Bellary Road 1',
        'event_cause': 'tree_fall',
    },
    {
        'id': 'S09', 'name': 'S09 — Procession Mysore Road',
        'source_lat': 12.9600, 'source_lon': 77.5400,
        'dest_lat':   12.9200, 'dest_lon':   77.5000,
        'incident_lat': 12.9441, 'incident_lon': 77.5274,
        'requires_closure': True,  'blockage_radius_m': 350,
        'corridor': 'Mysore Road',
        'event_cause': 'procession',
    },
    {
        'id': 'S10', 'name': 'S10 — Public Gathering Lalbagh',
        'source_lat': 12.9600, 'source_lon': 77.5700,
        'dest_lat':   12.9300, 'dest_lon':   77.5900,
        'incident_lat': 12.9507, 'incident_lon': 77.5848,
        'requires_closure': False, 'blockage_radius_m': 0,
        'corridor': 'Non-corridor',
        'event_cause': 'public_event',
    },
]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _edge_speed_kmh(edge_data: dict) -> float:
    """Derive speed in km/h from edge attributes."""
    hw = edge_data.get('highway', 'road')
    if isinstance(hw, list):
        hw = hw[0]
    return HIGHWAY_SPEED.get(str(hw).lower(), 25)


def _edge_travel_time_s(edge_data: dict) -> float:
    """Travel time in seconds for a single edge."""
    length_m = edge_data.get('length', 100.0)
    if isinstance(length_m, list):
        length_m = float(length_m[0])
    speed_ms = _edge_speed_kmh(edge_data) * 1000 / 3600
    return length_m / max(speed_ms, 0.1)


def _road_name_lower(edge_data: dict) -> str:
    name = edge_data.get('name', '')
    if isinstance(name, list):
        name = ' '.join(str(n) for n in name)
    return str(name).lower()


def _is_risky_road(edge_data: dict) -> bool:
    name = _road_name_lower(edge_data)
    return any(kw in name for kw in RISKY_ROAD_KEYWORDS)


def _congestion_weight(edge_data: dict, blk_lat: float, blk_lon: float,
                       radius_m: float, blk_weight: float = 5.0) -> float:
    """
    Congestion penalty factor for an edge.
    - Higher near blockage point
    - Higher on known risky roads
    """
    u_lat = edge_data.get('_u_lat', 0.0)
    u_lon = edge_data.get('_u_lon', 0.0)
    dist_to_blk = _haversine_m(u_lat, u_lon, blk_lat, blk_lon)

    # Proximity penalty: 1.0 far away, blk_weight near blockage
    prox = 1.0 + (blk_weight - 1.0) * max(0.0, 1.0 - dist_to_blk / max(radius_m * 3, 500))

    # Risky road penalty
    risky = 2.0 if _is_risky_road(edge_data) else 1.0

    return prox * risky


def extract_path_coords(G, path: List[int]) -> List[Tuple[float, float]]:
    """Return (lat, lon) list following actual road geometry."""
    coords = []
    for u, v in zip(path[:-1], path[1:]):
        edge_data = G.get_edge_data(u, v)
        if edge_data is None:
            continue
        edge = edge_data[0] if (isinstance(edge_data, dict) and 0 in edge_data) else edge_data
        if 'geometry' in edge:
            for lon, lat in list(edge['geometry'].coords):
                coords.append((lat, lon))
        else:
            coords.append((G.nodes[u]['y'], G.nodes[u]['x']))
    if path:
        coords.append((G.nodes[path[-1]]['y'], G.nodes[path[-1]]['x']))
    # Deduplicate
    if not coords:
        return coords
    deduped = [coords[0]]
    for pt in coords[1:]:
        if pt != deduped[-1]:
            deduped.append(pt)
    return deduped


def path_length_km(G, path: List[int]) -> float:
    total_m = 0.0
    for u, v in zip(path[:-1], path[1:]):
        ed = G.get_edge_data(u, v)
        if ed is None:
            continue
        e = ed[0] if (isinstance(ed, dict) and 0 in ed) else ed
        l = e.get('length', 0.0)
        if isinstance(l, list):
            l = float(l[0])
        total_m += l
    return round(total_m / 1000.0, 2)


def path_travel_min(G, path: List[int]) -> float:
    total_s = 0.0
    for u, v in zip(path[:-1], path[1:]):
        ed = G.get_edge_data(u, v)
        if ed is None:
            continue
        e = ed[0] if (isinstance(ed, dict) and 0 in ed) else ed
        total_s += _edge_travel_time_s(e)
    return round(total_s / 60.0, 1)


def path_congestion_score(G, path: List[int],
                          blk_lat: float, blk_lon: float,
                          blk_radius_m: float) -> Tuple[float, int]:
    """
    Returns (congestion_exposure_score 0-100, risky_corridors_count).
    Score is average congestion weight across all edges, normalized to 0-100.
    """
    weights = []
    risky_count = 0
    for u, v in zip(path[:-1], path[1:]):
        ed = G.get_edge_data(u, v)
        if ed is None:
            continue
        e = ed[0] if (isinstance(ed, dict) and 0 in ed) else ed
        e['_u_lat'] = G.nodes[u]['y']
        e['_u_lon'] = G.nodes[u]['x']
        w = _congestion_weight(e, blk_lat, blk_lon, blk_radius_m)
        weights.append(w)
        if _is_risky_road(e):
            risky_count += 1
    if not weights:
        return 0.0, 0
    avg_w = sum(weights) / len(weights)
    # Normalize: 1.0 (clean) → 0, 10.0 (max blockage+risky) → 100
    score = min(100.0, max(0.0, (avg_w - 1.0) / 9.0 * 100.0))
    return round(score, 1), risky_count


def remove_blocked_nodes(G, blk_lat: float, blk_lon: float, radius_m: float):
    G2 = G.copy()
    to_remove = [n for n, d in G2.nodes(data=True)
                 if _haversine_m(blk_lat, blk_lon, d['y'], d['x']) <= radius_m]
    G2.remove_nodes_from(to_remove)
    return G2, len(to_remove)


def _add_time_weights(G):
    """Add 'travel_time' attribute to all edges (seconds)."""
    for u, v, k, data in G.edges(keys=True, data=True):
        G[u][v][k]['travel_time'] = _edge_travel_time_s(data)


def _add_congestion_weights(G, blk_lat: float, blk_lon: float, blk_radius_m: float):
    """
    Add 'cong_weight' to each edge = length_m × congestion_factor.
    Edges near the blockage or on risky roads cost more.
    """
    for u, v, k, data in G.edges(keys=True, data=True):
        data['_u_lat'] = G.nodes[u]['y']
        data['_u_lon'] = G.nodes[u]['x']
        length_m = data.get('length', 100.0)
        if isinstance(length_m, list):
            length_m = float(length_m[0])
        cw = _congestion_weight(data, blk_lat, blk_lon, blk_radius_m)
        G[u][v][k]['cong_weight'] = length_m * cw


def _add_balanced_weights(G, alpha: float = 0.5, beta: float = 0.5):
    """
    Balanced weight = alpha × travel_time (s) + beta × cong_weight (normalised).
    Assumes travel_time and cong_weight already set.
    """
    for u, v, k, data in G.edges(keys=True, data=True):
        tt = data.get('travel_time', 60.0)
        cw = data.get('cong_weight', data.get('length', 100.0))
        G[u][v][k]['balanced_weight'] = alpha * tt + beta * (cw / 10.0)


# ── K-shortest diverse paths ──────────────────────────────────────────────────

def _k_shortest_paths(G, src: int, dst: int, weight: str,
                      K: int = 5, max_cand: int = 20) -> List[List[int]]:
    """
    Return up to K shortest simple paths by `weight`, using Yen's algorithm
    (NetworkX simple_paths). We cap at max_cand to avoid infinite loops.
    """
    paths = []
    try:
        gen = nx.shortest_simple_paths(G, src, dst, weight=weight)
        for i, p in enumerate(gen):
            paths.append(p)
            if len(paths) >= K or i >= max_cand:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.exception.NetworkXError):
        pass
    return paths


def _paths_are_different(p1: List[int], p2: List[int], min_diff_frac: float = 0.15) -> bool:
    """True if paths differ by at least min_diff_frac fraction of edges."""
    e1 = set(zip(p1[:-1], p1[1:]))
    e2 = set(zip(p2[:-1], p2[1:]))
    if not e1 or not e2:
        return False
    union = e1 | e2
    intersection = e1 & e2
    jaccard_diff = 1.0 - len(intersection) / len(union)
    return jaccard_diff >= min_diff_frac


def _select_diverse_paths(candidates: List[List[int]],
                           n: int = 3) -> List[List[int]]:
    """
    From a list of candidate paths, pick up to `n` maximally diverse ones.
    Always keeps the first (globally shortest for that weight).
    """
    if not candidates:
        return []
    selected = [candidates[0]]
    for cand in candidates[1:]:
        if len(selected) >= n:
            break
        if all(_paths_are_different(cand, sel) for sel in selected):
            selected.append(cand)
    return selected


# ── Core: build route dict from a path ────────────────────────────────────────

def _build_route_dict(G, path: List[int], route_type: str,
                      blk_lat: float, blk_lon: float,
                      blk_radius_m: float, shortest_km: float,
                      label: str, why: str) -> dict:
    coords = extract_path_coords(G, path)
    km = path_length_km(G, path)
    travel_min = path_travel_min(G, path)
    cong_score, risky_corridors = path_congestion_score(
        G, path, blk_lat, blk_lon, blk_radius_m)
    extra_km = round(max(0.0, km - shortest_km), 2)
    return {
        'route_type':       route_type,
        'coords':           coords,
        'route_km':         km,
        'travel_min':       travel_min,
        'congestion_score': cong_score,
        'risky_corridors':  risky_corridors,
        'extra_km':         extra_km,
        'label':            label,
        'why':              why,
        'node_count':       len(path),
        'coord_count':      len(coords),
        'fallback':         False,
    }


# ── Core: load graph ──────────────────────────────────────────────────────────

def load_graph(force_download: bool = False):
    import osmnx as ox
    ox.settings.log_console = False
    ox.settings.use_cache = True

    if CACHE_PATH.exists() and not force_download:
        print(f'  Loading graph from cache: {CACHE_PATH.name}')
        G = ox.load_graphml(str(CACHE_PATH))
        print(f'  Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges')
        return G, 'cache'

    print('  Downloading Bengaluru drive graph (60-120s)...')
    G = ox.graph_from_place('Bengaluru, Karnataka, India',
                             network_type='drive', simplify=True)
    ox.save_graphml(G, str(CACHE_PATH))
    sz = CACHE_PATH.stat().st_size // (1024 * 1024)
    print(f'  Graph downloaded & cached: {G.number_of_nodes():,} nodes, '
          f'{G.number_of_edges():,} edges ({sz} MB)')
    return G, 'downloaded'


# ── Core: route one scenario → 3 candidate routes ─────────────────────────────

def route_scenario_multi(G, sc: dict, verbose: bool = True) -> dict:
    """
    Compute 3 candidate routes (fastest, least_traffic, balanced) for one scenario.

    Returns:
    {
      'name':    str,
      'engine':  str,
      'routes':  [
          {route_type, coords, route_km, travel_min, congestion_score,
           risky_corridors, extra_km, label, why, node_count, coord_count, fallback},
          ...  (3 entries, types: fastest / least_traffic / balanced)
      ],
      # Backwards-compatible keys (from fastest route):
      'orig_coords', 'alt_coords', 'orig_km', 'alt_km', 'extra_km', 'delay_min',
      'orig_nodes', 'alt_nodes', 'blocked_nodes_removed', 'fallback', 'fallback_reason'
    }
    """
    import osmnx as ox

    name      = sc['name']
    slat, slon = sc['source_lat'],   sc['source_lon']
    dlat, dlon = sc['dest_lat'],     sc['dest_lon']
    blat, blon = sc['incident_lat'], sc['incident_lon']
    radius_m   = sc['blockage_radius_m']
    needs_block = sc['requires_closure'] and radius_m > 0

    result = {
        'name':   name,
        'engine': 'OSMnx+NetworkX',
        'routes': [],
        # backward-compat
        'orig_coords': [], 'alt_coords':  [],
        'orig_km':     0.0, 'alt_km':     0.0,
        'extra_km':    0.0, 'delay_min':  0.0,
        'orig_nodes':  0,   'alt_nodes':  0,
        'blocked_nodes_removed': 0,
        'fallback': False, 'fallback_reason': '',
    }

    try:
        src_node = ox.nearest_nodes(G, X=slon, Y=slat)
        dst_node = ox.nearest_nodes(G, X=dlon, Y=dlat)

        # ── Build working graph (remove blocked nodes if needed) ──────────────
        if needs_block:
            G_work, blocked_count = remove_blocked_nodes(G, blat, blon, radius_m)
            result['blocked_nodes_removed'] = blocked_count
            # Re-snap to valid nodes
            try:
                src_node = ox.nearest_nodes(G_work, X=slon, Y=slat)
                dst_node = ox.nearest_nodes(G_work, X=dlon, Y=dlat)
            except Exception:
                G_work = G   # fallback: use full graph
        else:
            G_work = G

        # ── Verify connectivity first ─────────────────────────────────────────
        try:
            base_path = nx.shortest_path(G_work, src_node, dst_node, weight='length')
        except nx.NetworkXNoPath:
            if needs_block:
                # Try with smaller radius
                for factor in [0.5, 0.25, 0.0]:
                    r2 = radius_m * factor
                    if r2 == 0:
                        G_work = G
                        src_node = ox.nearest_nodes(G, X=slon, Y=slat)
                        dst_node = ox.nearest_nodes(G, X=dlon, Y=dlat)
                    else:
                        G_work, _ = remove_blocked_nodes(G, blat, blon, r2)
                        src_node = ox.nearest_nodes(G_work, X=slon, Y=slat)
                        dst_node = ox.nearest_nodes(G_work, X=dlon, Y=dlat)
                    try:
                        base_path = nx.shortest_path(G_work, src_node, dst_node, weight='length')
                        if verbose:
                            print(f'  {sc["id"]} blockage radius reduced to {r2}m')
                        break
                    except nx.NetworkXNoPath:
                        continue
                else:
                    raise ValueError('No path found even with reduced blockage radius')
            else:
                raise

        shortest_km = path_length_km(G_work, base_path)

        # ── Add edge weights for each routing objective ───────────────────────
        # We add all weight attributes to the same graph instance.
        # If needs_block is True, G_work is already a copy created by remove_blocked_nodes,
        # so we don't need to copy it again. Otherwise we copy G_work to avoid modifying G.
        if needs_block:
            G_routed = G_work
        else:
            G_routed = G_work.copy()

        _add_time_weights(G_routed)
        _add_congestion_weights(G_routed, blat, blon, max(radius_m, 300))
        _add_balanced_weights(G_routed, alpha=0.5, beta=0.5)

        # ── Compute best path for each objective directly using Dijkstra ──────
        try:
            path_fast = nx.shortest_path(G_routed, src_node, dst_node, weight='travel_time')
        except nx.NetworkXNoPath:
            path_fast = base_path

        try:
            path_cong = nx.shortest_path(G_routed, src_node, dst_node, weight='cong_weight')
        except nx.NetworkXNoPath:
            path_cong = base_path

        try:
            path_bal = nx.shortest_path(G_routed, src_node, dst_node, weight='balanced_weight')
        except nx.NetworkXNoPath:
            path_bal = base_path

        # If all three came out identical, force diversity via penalisation
        if (path_fast == path_cong == path_bal):
            # Penalise edges of path_fast to get different paths
            G_pen = G_routed.copy()
            fast_edges = set(zip(path_fast[:-1], path_fast[1:]))
            PENALTY = 8.0
            for u, v, k2, data in G_pen.edges(keys=True, data=True):
                if (u, v) in fast_edges or (v, u) in fast_edges:
                    G_pen[u][v][k2]['length'] = data.get('length', 100.0) * PENALTY

            try:
                path_cong = nx.shortest_path(G_pen, src_node, dst_node, weight='length')
            except nx.NetworkXNoPath:
                path_cong = path_fast

            # For balanced: penalise both path_fast and path_cong edges with moderate penalty
            G_pen2 = G_routed.copy()
            pen_edges = (set(zip(path_fast[:-1], path_fast[1:])) |
                         set(zip(path_cong[:-1], path_cong[1:])))
            for u, v, k2, data in G_pen2.edges(keys=True, data=True):
                if (u, v) in pen_edges or (v, u) in pen_edges:
                    G_pen2[u][v][k2]['length'] = data.get('length', 100.0) * 4.0
            try:
                path_bal = nx.shortest_path(G_pen2, src_node, dst_node, weight='length')
            except nx.NetworkXNoPath:
                path_bal = path_fast

        # ── Build route dicts ─────────────────────────────────────────────────
        r_fast = _build_route_dict(
            G_routed, path_fast, 'fastest', blat, blon, radius_m, shortest_km,
            label='⚡ Fastest Route',
            why='Minimises travel time using speed-class road weights'
        )
        r_cong = _build_route_dict(
            G_routed, path_cong, 'least_traffic', blat, blon, radius_m, shortest_km,
            label='🌿 Least Traffic Route',
            why='Avoids congested corridors and blockage proximity'
        )
        r_bal = _build_route_dict(
            G_routed, path_bal,  'balanced', blat, blon, radius_m, shortest_km,
            label='⚖️ Balanced Route',
            why='Balances travel time with congestion avoidance'
        )

        # ── Score routes and pick recommendation ──────────────────────────────
        # scoring formula: composite_score = travel_min * 0.4 + cong_score * 0.4 + extra_km * 0.2 * 10
        def composite(r):
            return (r['travel_min'] * 0.4 +
                    r['congestion_score'] * 0.4 +
                    r['extra_km'] * 2.0)

        routes = [r_fast, r_cong, r_bal]
        best = min(routes, key=composite)
        best['recommended'] = True
        for r in routes:
            r.setdefault('recommended', False)

        result['routes'] = routes

        # ── Backwards-compatible keys ─────────────────────────────────────────
        # orig = fastest, alt = least_traffic
        result['orig_coords'] = r_fast['coords']
        result['alt_coords']  = r_cong['coords']
        result['orig_km']     = r_fast['route_km']
        result['alt_km']      = r_cong['route_km']
        result['extra_km']    = r_cong['extra_km']
        result['delay_min']   = round(max(0.0, r_cong['extra_km'] * 2.0 + 2.0), 1)
        result['orig_nodes']  = r_fast['node_count']
        result['alt_nodes']   = r_cong['node_count']

        if verbose:
            print(f'  {sc["id"]} ⚡ fastest      : {r_fast["route_km"]:.2f}km  {r_fast["travel_min"]}min  cong={r_fast["congestion_score"]:.0f}')
            print(f'  {sc["id"]} 🌿 least_traffic: {r_cong["route_km"]:.2f}km  {r_cong["travel_min"]}min  cong={r_cong["congestion_score"]:.0f}')
            print(f'  {sc["id"]} ⚖️  balanced     : {r_bal["route_km"]:.2f}km  {r_bal["travel_min"]}min  cong={r_bal["congestion_score"]:.0f}')
            print(f'  {sc["id"]} ✅ recommended  : {best["label"]}')

    except Exception as e:
        result['fallback'] = True
        result['fallback_reason'] = str(e)
        if verbose:
            print(f'  {sc["id"]} FALLBACK ({e}): using simulated 3-route stub')

        hav = _haversine_m(slat, slon, dlat, dlon) / 1000.0
        base_km = round(hav * 1.35, 2)
        mid = ((slat+dlat)/2, (slon+dlon)/2)

        def _stub_route(route_type, km_factor, offset, label, why):
            km = round(base_km * km_factor, 2)
            return {
                'route_type':       route_type,
                'coords':           [(slat,slon),(mid[0]+offset[0], mid[1]+offset[1]),(dlat,dlon)],
                'route_km':         km,
                'travel_min':       round(km / 30 * 60, 1),
                'congestion_score': 50.0,
                'risky_corridors':  0,
                'extra_km':         round(km - base_km, 2),
                'label':            label,
                'why':              why + ' (simulated fallback)',
                'node_count':       3,
                'coord_count':      3,
                'fallback':         True,
                'recommended':      route_type == 'fastest',
            }

        r_f = _stub_route('fastest',      1.0,  (0.0,   0.0),   '⚡ Fastest Route',       'Fastest path (simulated)')
        r_c = _stub_route('least_traffic',1.15, (0.006, 0.006), '🌿 Least Traffic Route', 'Avoids congestion (simulated)')
        r_b = _stub_route('balanced',     1.08, (0.003, 0.003), '⚖️ Balanced Route',      'Balanced option (simulated)')

        result['routes']      = [r_f, r_c, r_b]
        result['orig_coords'] = r_f['coords']
        result['alt_coords']  = r_c['coords']
        result['orig_km']     = r_f['route_km']
        result['alt_km']      = r_c['route_km']
        result['extra_km']    = r_c['extra_km']
        result['delay_min']   = round(r_c['extra_km'] * 2.0 + 2.0, 1)
        result['engine']      = 'Simulated (fallback)'

    return result


# ── Route all scenarios ────────────────────────────────────────────────────────

def get_multi_routes_for_scenarios(G, scenarios=None, verbose=True) -> Dict[str, dict]:
    """Route all scenarios, return dict keyed by scenario name."""
    if scenarios is None:
        scenarios = SCENARIOS
    results = {}
    for sc in scenarios:
        if verbose:
            print(f'\n  [{sc["id"]}] {sc["name"]}')
        r = route_scenario_multi(G, sc, verbose=verbose)
        results[sc['name']] = r
    return results


# Backwards-compatible alias
def get_routes_for_scenarios(G, scenarios=None, verbose=True) -> Dict[str, dict]:
    return get_multi_routes_for_scenarios(G, scenarios=scenarios, verbose=verbose)


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('=' * 70)
    print('  MULTI-ROUTE INTELLIGENCE ENGINE — OSMnx + NetworkX')
    print('=' * 70)

    print('\n[1] Loading Bengaluru road graph...')
    G, source = load_graph()
    print(f'  Source: {source}')

    print('\n[2] Testing S01 (single scenario)...')
    s01 = [sc for sc in SCENARIOS if sc['id'] == 'S01'][0]
    r = route_scenario_multi(G, s01, verbose=True)

    print(f'\n  Engine : {r["engine"]}')
    print(f'  Routes : {len(r["routes"])}')
    for rt in r['routes']:
        rec = '  ← RECOMMENDED' if rt.get('recommended') else ''
        print(f'  {rt["label"]:30s}  {rt["route_km"]:5.2f}km  {rt["travel_min"]:5.1f}min  '
              f'cong={rt["congestion_score"]:5.1f}  extra={rt["extra_km"]:4.2f}km{rec}')
        print(f'    Why: {rt["why"]}')

    print('\n[3] Routing all 10 scenarios...')
    all_results = get_multi_routes_for_scenarios(G, verbose=True)

    print('\n[4] Summary:')
    for name, r in all_results.items():
        fb = 'FALLBACK' if r['fallback'] else 'OSMnx  '
        rec = next((rt for rt in r['routes'] if rt.get('recommended')), r['routes'][0])
        print(f'  {fb}  {name:<40}  recommended={rec["label"]}  '
              f'{rec["route_km"]:.2f}km  {rec["travel_min"]}min')

    print('\n  Multi-route engine test complete.')
