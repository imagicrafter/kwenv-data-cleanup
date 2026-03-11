#!/usr/bin/env python3
"""Generate geodata.js — geocoded locations with territory assignments via point-in-polygon."""
import json, os, re, sys
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    print("ERROR: requests package required. pip install requests", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def norm(name):
    """Normalize name — matches the app's JS norm() function exactly."""
    stripped = re.sub(r'^DKW[\s\-\u2013]*', '', name, flags=re.I)
    return re.sub(r'[^A-Z0-9]', '', stripped.upper())


def point_in_polygon(lat, lng, polygon):
    """Ray casting algorithm. polygon = [(lng, lat), ...]"""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def parse_kml(path):
    """Parse KML, return list of {name, polygon: [(lng, lat), ...]}"""
    tree = ET.parse(path)
    root = tree.getroot()
    ns = 'http://www.opengis.net/kml/2.2'

    territories = []
    for pm in root.iter(f'{{{ns}}}Placemark'):
        name_el = pm.find(f'{{{ns}}}name')
        coords_el = pm.find(f'.//{{{ns}}}coordinates')
        if name_el is None or coords_el is None:
            continue
        name = name_el.text.strip()
        polygon = []
        for coord in coords_el.text.strip().split():
            parts = coord.split(',')
            lng, lat = float(parts[0]), float(parts[1])
            polygon.append((lng, lat))
        territories.append({'name': name, 'polygon': polygon})

    return territories


def load_env():
    """Walk up from script dir to find .env and load it."""
    d = SCRIPT_DIR
    for _ in range(10):
        env_file = os.path.join(d, '.env')
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        d = os.path.dirname(d)


def fetch_locations(supabase_url, supabase_key):
    """Fetch geocoded locations from kwenv_fleetillo.locations via REST API."""
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Accept-Profile': 'kwenv_fleetillo',
    }
    params = {
        'select': 'name,latitude,longitude,city,state,postal_code',
        'latitude': 'not.is.null',
        'limit': '5000',
    }
    resp = requests.get(f'{supabase_url}/rest/v1/locations', headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def main():
    load_env()
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    if not supabase_url or not supabase_key:
        print('ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required', file=sys.stderr)
        sys.exit(1)

    # Fetch locations
    locations = fetch_locations(supabase_url, supabase_key)
    print(f'Fetched {len(locations)} geocoded locations from Supabase')

    # Parse KML
    kml_path = os.path.join(SCRIPT_DIR, 'territories.kml')
    if not os.path.exists(kml_path):
        print(f'ERROR: {kml_path} not found', file=sys.stderr)
        sys.exit(1)

    territories = parse_kml(kml_path)
    print(f'Parsed {len(territories)} territory polygons from KML')
    for t in territories:
        print(f'  {t["name"]} ({len(t["polygon"])} vertices)')

    # Point-in-polygon assignment
    territory_names = sorted(set(t['name'] for t in territories))
    location_map = {}
    assigned = 0
    unassigned_list = []

    for loc in locations:
        lat = float(loc['latitude'])
        lng = float(loc['longitude'])
        n = norm(loc['name'])

        territory = None
        for t in territories:
            if point_in_polygon(lat, lng, t['polygon']):
                territory = t['name']
                break

        entry = {'n': loc['name'], 'lat': lat, 'lng': lng}
        if territory:
            entry['t'] = territory
            assigned += 1
        else:
            unassigned_list.append(loc['name'])

        # Keep first match if duplicate normalized names
        if n not in location_map:
            location_map[n] = entry

    print(f'\nResults: {assigned} assigned, {len(unassigned_list)} unassigned')
    if unassigned_list and len(unassigned_list) <= 20:
        print('Unassigned locations:')
        for name in unassigned_list:
            print(f'  {name}')

    # Build polygon map for export (territory name -> [{lat, lng}, ...])
    polygon_map = {}
    for t in territories:
        polygon_map[t['name']] = [{'lat': lat, 'lng': lng} for lng, lat in t['polygon']]

    # Write geodata.js
    geodata = {
        'territories': territory_names,
        'locations': location_map,
        'polygons': polygon_map,
    }

    output_path = os.path.join(SCRIPT_DIR, 'geodata.js')
    with open(output_path, 'w') as f:
        f.write('const GEODATA = ')
        json.dump(geodata, f, separators=(',', ':'))
        f.write(';\n')

    size_kb = os.path.getsize(output_path) / 1024
    print(f'Wrote {output_path} ({size_kb:.1f} KB)')


if __name__ == '__main__':
    main()
