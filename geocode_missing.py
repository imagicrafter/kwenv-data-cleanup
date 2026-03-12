#!/usr/bin/env python3
"""Geocode all SF records (DKW + clean) missing from geodata.js using Geocodio, then merge with territory assignment."""
import json, os, re, sys, time

try:
    import openpyxl
    import requests
except ImportError:
    print("ERROR: pip install openpyxl requests", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SF_EXPORT = '/Users/justinmartin/Downloads/sf-customer-list-full.xlsx'
GEOCODIO_URL = 'https://api.geocod.io/v1.7/geocode'
BATCH_SIZE = 100  # Geocodio batch limit


def norm(name):
    stripped = re.sub(r'^DKW[\s\-\u2013]*', '', name, flags=re.I)
    return re.sub(r'[^A-Z0-9]', '', stripped.upper())


def load_env():
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


def load_geodata():
    geodata_path = os.path.join(SCRIPT_DIR, 'geodata.js')
    with open(geodata_path) as f:
        js = f.read()
    json_str = js.replace('const GEODATA = ', '').rstrip().rstrip(';')
    return json.loads(json_str)


def parse_kml(path):
    from xml.etree import ElementTree as ET
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


def point_in_polygon(lat, lng, polygon):
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


def haversine(lat1, lng1, lat2, lng2):
    """Distance in km between two lat/lng points."""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_territory(lat, lng, territories):
    """Find nearest territory by distance to polygon centroid. Returns (name, distance_km)."""
    best_name = None
    best_dist = float('inf')
    for t in territories:
        clat = sum(p[1] for p in t['polygon']) / len(t['polygon'])
        clng = sum(p[0] for p in t['polygon']) / len(t['polygon'])
        d = haversine(lat, lng, clat, clng)
        if d < best_dist:
            best_dist = d
            best_name = t['name']
    return best_name, best_dist


def get_missing_addresses(geodata):
    """Find ALL records (DKW + clean) in SF export that are NOT in geodata."""
    wb = openpyxl.load_workbook(SF_EXPORT, read_only=True)
    ws = wb.active

    geo_names = set(geodata['locations'].keys())
    missing = []
    seen_norms = set()

    # Find header row dynamically
    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True)):
        if row and str(row[0] or '').strip() == 'Customer Name':
            header_row = i + 1
            headers = [str(c or '').strip().lower() for c in row]
            break

    if not header_row:
        print('ERROR: Could not find header row in SF export', file=sys.stderr)
        sys.exit(1)

    # Find address column indices
    def find_col(keywords):
        for j, h in enumerate(headers):
            if all(k in h for k in keywords):
                return j
        return None

    col_name = find_col(['customer', 'name'])
    col_addr = find_col(['primary', 'address 1']) or find_col(['address 1']) or find_col(['address'])
    col_city = find_col(['primary', 'city']) or find_col(['city'])
    col_state = find_col(['primary', 'state']) or find_col(['state'])
    col_zip = find_col(['primary', 'zip']) or find_col(['zip'])

    print(f'  Columns: name={col_name}, addr={col_addr}, city={col_city}, state={col_state}, zip={col_zip}')

    dkw_count = 0
    clean_count = 0

    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        name = str(row[col_name] or '').strip() if col_name is not None else ''
        if not name:
            continue
        n = norm(name)
        if n in geo_names or n in seen_norms:
            continue

        address = str(row[col_addr] or '').strip() if col_addr is not None else ''
        city = str(row[col_city] or '').strip() if col_city is not None else ''
        state = str(row[col_state] or '').strip() if col_state is not None else ''
        zipcode = str(row[col_zip] or '').strip() if col_zip is not None else ''

        if not address:
            continue

        full_address = address
        if city:
            full_address += ', ' + city
        if state:
            full_address += ', ' + state
        if zipcode:
            full_address += ' ' + zipcode

        is_dkw = bool(re.match(r'^DKW[\s\-\u2013]', name, re.I))
        # For display name, strip DKW prefix if present
        display_name = re.sub(r'^DKW[\s\-\u2013]*', '', name, flags=re.I) if is_dkw else name

        missing.append({
            'norm': n,
            'name': name,
            'display_name': display_name,
            'address': full_address,
        })
        seen_norms.add(n)

        if is_dkw:
            dkw_count += 1
        else:
            clean_count += 1

    wb.close()
    print(f'  Missing: {dkw_count} DKW + {clean_count} clean = {dkw_count + clean_count} total')
    return missing


def geocode_batch(addresses, api_key):
    """Geocode addresses using Geocodio individual GET requests."""
    results = {}
    failed = 0

    for i, item in enumerate(addresses):
        if (i + 1) % 50 == 0 or i == 0:
            print(f'  Geocoding {i + 1}/{len(addresses)}...')
        try:
            resp = requests.get(
                GEOCODIO_URL,
                params={'q': item['address'], 'api_key': api_key},
                timeout=15,
            )
            if resp.status_code == 403:
                print(f'  403 at record {i + 1} — quota limit. Saving {len(results)} results.')
                break
            if resp.status_code == 200:
                data = resp.json()
                if data.get('results') and len(data['results']) > 0:
                    loc = data['results'][0]['location']
                    results[item['norm']] = {
                        'lat': loc['lat'],
                        'lng': loc['lng'],
                        'accuracy': data['results'][0].get('accuracy', 0),
                    }
            else:
                failed += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f'  Failed: {item["display_name"]}: {e}')
        # Rate limit: ~1000/min on free tier
        if (i + 1) % 100 == 0:
            time.sleep(1)

    return results


def main():
    load_env()
    api_key = os.environ.get('GEOCODIO_API_KEY')
    if not api_key:
        print('ERROR: GEOCODIO_API_KEY required in .env', file=sys.stderr)
        sys.exit(1)

    # Load existing geodata
    geodata = load_geodata()
    print(f'Existing geodata: {len(geodata["locations"])} locations')

    # Find missing addresses
    missing = get_missing_addresses(geodata)
    print(f'Missing records needing geocoding: {len(missing)}')

    if not missing:
        print('Nothing to geocode!')
        return

    # Filter out records with no useful address
    geocodable = [m for m in missing if len(m['address']) > 10]
    skipped = len(missing) - len(geocodable)
    if skipped:
        print(f'Skipping {skipped} records with insufficient address data')
    print(f'Geocoding {len(geocodable)} addresses via Geocodio...')

    # Geocode
    geocoded = geocode_batch(geocodable, api_key)
    print(f'\nGeocoded: {len(geocoded)} of {len(geocodable)}')

    # Load KML territories for point-in-polygon
    kml_path = os.path.join(SCRIPT_DIR, 'territories.kml')
    territories = parse_kml(kml_path) if os.path.exists(kml_path) else []
    print(f'Territory polygons: {len(territories)}')

    # Merge into geodata
    polygon_assigned = 0
    nearest_assigned = 0
    for item in geocodable:
        geo = geocoded.get(item['norm'])
        if not geo:
            continue

        # Point-in-polygon territory assignment
        territory = None
        for t in territories:
            if point_in_polygon(geo['lat'], geo['lng'], t['polygon']):
                territory = t['name']
                break

        entry = {
            'n': item['display_name'],
            'lat': geo['lat'],
            'lng': geo['lng'],
        }
        if territory:
            entry['t'] = territory
            polygon_assigned += 1
        elif territories:
            # Nearest-territory fallback
            territory, dist_km = nearest_territory(geo['lat'], geo['lng'], territories)
            entry['t'] = territory
            entry['a'] = 'nearest'
            nearest_assigned += 1

        # Only add if not already in geodata
        if item['norm'] not in geodata['locations']:
            geodata['locations'][item['norm']] = entry

    print(f'\nNew locations added: {len(geocoded)}')
    print(f'  Polygon-assigned: {polygon_assigned}')
    print(f'  Nearest-assigned: {nearest_assigned}')
    print(f'Total locations now: {len(geodata["locations"])}')

    # Write updated geodata.js
    output_path = os.path.join(SCRIPT_DIR, 'geodata.js')
    with open(output_path, 'w') as f:
        f.write('const GEODATA = ')
        json.dump(geodata, f, separators=(',', ':'))
        f.write(';\n')

    size_kb = os.path.getsize(output_path) / 1024
    print(f'\nWrote {output_path} ({size_kb:.1f} KB)')


if __name__ == '__main__':
    main()
