#!/usr/bin/env python3
"""Check how many DKW records from the SF export have geocode matches."""
import openpyxl, re, json

def norm(name):
    stripped = re.sub(r'^DKW[\s\-\u2013]*', '', name, flags=re.I)
    return re.sub(r'[^A-Z0-9]', '', stripped.upper())

# Load SF export DKW names
wb = openpyxl.load_workbook('/Users/justinmartin/Downloads/sf-customer-list-full.xlsx', read_only=True)
ws = wb.active

dkw_names = {}
for row in ws.iter_rows(min_row=2, values_only=True):
    name = str(row[0] or '').strip()
    if re.match(r'^DKW[\s\-\u2013]', name, re.I):
        n = norm(name)
        if n not in dkw_names:
            dkw_names[n] = name

# Load geodata
with open('projects/fleetillo/clients/kw-environmental/apps/data-management/geodata.js') as f:
    js = f.read()
    json_str = js.replace('const GEODATA = ', '').rstrip().rstrip(';')
    geodata = json.loads(json_str)

geo_names = set(geodata['locations'].keys())

matched = set(dkw_names.keys()) & geo_names
unmatched = set(dkw_names.keys()) - geo_names

# Count how many matched have territories
with_territory = sum(1 for n in matched if geodata['locations'][n].get('t'))
without_territory = len(matched) - with_territory

print(f'Total DKW records in SF: {len(dkw_names)}')
print(f'Geocoded locations available: {len(geo_names)}')
print(f'DKW records WITH geocode match: {len(matched)}')
print(f'  - With territory assignment: {with_territory}')
print(f'  - Outside all territories: {without_territory}')
print(f'DKW records WITHOUT geocode: {len(unmatched)}')
print(f'\n--- Unmatched DKW records (no geocode) ---')
for n in sorted(unmatched):
    print(f'  {dkw_names[n]}')
