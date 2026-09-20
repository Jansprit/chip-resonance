// _load_js_universe.js — load STOCK_UNIVERSE from data.js and emit JSON
const fs = require('fs');
const path = process.argv[2];
const outPath = process.argv[3];
const src = fs.readFileSync(path, 'utf8');
const window = {};
eval(src);
fs.writeFileSync(outPath, JSON.stringify(window.STOCK_UNIVERSE), 'utf8');