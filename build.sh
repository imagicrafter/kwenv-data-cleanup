#!/usr/bin/env bash
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────
PASSWORD="${KW_APP_PASSWORD:?Set KW_APP_PASSWORD env var}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Step 0: Generate geodata from Supabase + KML ─────────────────────────
echo "Generating geodata.js..."
python3 generate_geodata.py

# ── Step 1: Regenerate self-contained build ─────────────────────────────
echo "Regenerating KW_DataCleanup.html..."
python3 -c "
import re, sys
with open('KW_DataCleanup.html','r') as f: old = f.read()
with open('index.html','r') as f: new = f.read()
m = re.search(r'(<script>/\*! xlsx\.js.*?</script>)', old, re.DOTALL)
if not m: print('ERROR: Could not find inlined SheetJS block', file=sys.stderr); sys.exit(1)
xlsx_block = m.group(1)
cdn_tag = '<script src=\"https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js\"></script>'
if cdn_tag not in new: print('ERROR: CDN tag not found in index.html', file=sys.stderr); sys.exit(1)
# Also inline geodata.js
with open('geodata.js','r') as f: geodata = f.read()
geodata_tag = '<script src=\"geodata.js\"></script>'
result = new.replace(cdn_tag, xlsx_block).replace(geodata_tag, '<script>' + geodata + '</script>')
with open('KW_DataCleanup.html','w') as f: f.write(result)
print('  Done.')
"

# ── Step 2: Encrypt for GitHub Pages ────────────────────────────────────
echo "Encrypting for GitHub Pages..."
mkdir -p docs
npx pagecrypt KW_DataCleanup.html docs/index.html "$PASSWORD"

# ── Step 3: Replace pagecrypt default UI with minimal passcode form ─────
echo "Applying minimal password template..."
node -e "
const fs = require('fs');
let html = fs.readFileSync('docs/index.html', 'utf8');

// Replace the title
html = html.replace(/<title>Protected Page<\/title>/, '<title>Access</title>');

// Replace pagecrypt's default styles with our minimal ones
const minimalStyles = \`.hidden{display:none!important}*{margin:0;padding:0;box-sizing:border-box}body{min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb}main{display:flex;align-items:center;justify-content:center}.box{display:flex;gap:8px;align-items:center}form{display:flex;gap:8px}input[type=password]{padding:10px 16px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;width:240px;outline:none}input[type=password]:focus{border-color:#6b7280}input[type=submit]{padding:10px 20px;border:none;border-radius:8px;background:#374151;color:#fff;font-size:14px;font-weight:500;cursor:pointer}input[type=submit]:hover{background:#1f2937}header{flex-direction:column;align-items:center;gap:8px}header.flex{display:flex}header svg,header p,#load .spinner{display:none}#load p{font-size:14px;color:#6b7280}header.red p{color:#dc2626}\`;
html = html.replace(/<style>[\s\S]*?<\/style>/, '<style>' + minimalStyles + '</style>');

// Replace the form placeholder text
html = html.replace(/aria-label=Password/, 'aria-label=Passcode placeholder=Passcode');
html = html.replace(/value=Submit/, 'value=Go');

fs.writeFileSync('docs/index.html', html);
"
echo "  Done."

echo ""
echo "Build complete. Files ready:"
echo "  KW_DataCleanup.html  — self-contained (for local/download use)"
echo "  docs/index.html      — encrypted (for GitHub Pages)"
echo ""
echo "Next: git add docs/ && git commit && git push"
