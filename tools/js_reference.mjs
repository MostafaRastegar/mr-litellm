// Emit reference outputs from 9Router's original RTK filters as JSON.
// Run: node tools/js_reference.mjs > /tmp/js_out.json
import { readFileSync } from "node:fs";
import { autoDetectFilter } from "/tmp/rtk_src/autodetect.js";

const samples = JSON.parse(
  readFileSync("/tmp/rtk_src/parity_samples.json", "utf8")
);

const out = {};
for (const [name, text] of Object.entries(samples)) {
  const fn = autoDetectFilter(text);
  const filter = fn ? fn.filterName || fn.name : null;
  out[name] = {
    filter,
    output: fn ? fn(text) : text,
  };
}
process.stdout.write(JSON.stringify(out, null, 2));
