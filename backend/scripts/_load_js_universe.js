// _load_js_universe.js — load demo data from data.js
// Since data.js v2 became an async loader (no static STOCK_UNIVERSE),
// we instead read the schema hardcoded elsewhere via fallback:
//   1. Try evaluating data.js; if window.STOCK_UNIVERSE is set, use it
//   2. Otherwise fall back to fetching /data/latest/demo_subset.json from
//      the local filesystem (if it exists from a previous pipeline run)

const fs = require('fs');
const path = process.argv[2];
const outPath = process.argv[3];
const src = fs.readFileSync(path, 'utf8');
const window = {};
eval(src);
if (window.STOCK_UNIVERSE && Array.isArray(window.STOCK_UNIVERSE)) {
  fs.writeFileSync(outPath, JSON.stringify(window.STOCK_UNIVERSE), 'utf8');
  process.exit(0);
}

// Fallback: read from data/latest/demo_subset.json
const fallback = path.replace(/[\\/]data\.js$/, '') + '/data/latest/demo_subset.json';
try {
  if (fs.existsSync(fallback)) {
    const data = fs.readFileSync(fallback, 'utf8');
    fs.writeFileSync(outPath, data, 'utf8');
    process.exit(0);
  }
} catch (e) {}

process.stderr.write('STOCK_UNIVERSE not in data.js, and ' + fallback + ' not found\n');
process.exit(1);