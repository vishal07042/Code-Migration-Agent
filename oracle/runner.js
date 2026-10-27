"use strict";

/**
 * Oracle runner: loads a JS module, reads {function, args} JSON per line
 * from stdin, prints {"ok":true,"result":...} or {"ok":false,"error":...}
 * per line. Results are tagged-JSON encoded (see tagged_json.js).
 *
 * Usage: node oracle/runner.js <modulePath>
 * The module may use `module.exports = {fn...}` (CJS).
 */

const fs = require("fs");
const path = require("path");
const { encodeValue, decodeValue } = require("./tagged_json");

async function main() {
  const modPath = process.argv[2];
  if (!modPath) {
    console.error("Usage: node oracle/runner.js <modulePath>");
    process.exit(2);
  }
  const abs = path.resolve(modPath);
  if (!fs.existsSync(abs)) {
    console.error(`Module not found: ${abs}`);
    process.exit(2);
  }
  // eslint-disable-next-line import/no-dynamic-require, global-require
  const mod = require(abs);

  const readline = require("readline");
  const rl = readline.createInterface({ input: process.stdin, terminal: false });

  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let req;
    try {
      req = decodeValue(JSON.parse(trimmed));
    } catch (e) {
      process.stdout.write(JSON.stringify({ ok: false, error: `bad request: ${e.message}` }) + "\n");
      continue;
    }
    const { function: fname, args } = req;
    try {
      const fn = mod[fname];
      if (typeof fn !== "function") throw new Error(`not a function: ${fname}`);
      const result = await fn(...(Array.isArray(args) ? args : []));
      process.stdout.write(JSON.stringify({ ok: true, result: encodeValue(result) }) + "\n");
    } catch (e) {
      const msg = e && e.message ? e.message : String(e);
      process.stdout.write(JSON.stringify({ ok: false, error: msg }) + "\n");
    }
  }
}

main().catch((e) => {
  console.error(e && e.stack ? e.stack : String(e));
  process.exit(1);
});
