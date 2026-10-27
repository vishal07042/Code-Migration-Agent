"use strict";

/**
 * Dependency analysis without npm deps (regex-based, v1).
 * Scans *.js under <root> (excluding node_modules), extracting:
 *   imports: require('./x'), import ... from './x', import('./x')
 *   exports: module.exports = {...}, exports.name =, function/const top-level names
 * Prints JSON: {files: {relpath: {imports: [rel...], exports: [...]}}}
 * Only relative imports are resolved; bare packages listed in `packages`.
 *
 * Usage: node tools/analyze.js <rootDir>
 */

const fs = require("fs");
const path = require("path");

function walk(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.isFile() && e.name.endsWith(".js") && !e.name.endsWith(".test.js")) out.push(p);
  }
  return out;
}

function resolveImport(fromFile, spec) {
  if (!spec.startsWith(".")) return null;
  const base = path.resolve(path.dirname(fromFile), spec);
  const candidates = [base, base + ".js", path.join(base, "index.js")];
  for (const c of candidates) {
    try {
      if (fs.statSync(c).isFile()) return c;
    } catch {
      /* try next */
    }
  }
  return base + ".js"; // unresolved but probably intended; flagged downstream
}

function analyzeFile(abs, root) {
  const src = fs.readFileSync(abs, "utf8");
  const imports = new Set();
  const packages = new Set();
  const addSpec = (spec) => {
    if (spec.startsWith(".")) {
      imports.add(path.relative(root, resolveImport(abs, spec)).replace(/\\/g, "/"));
    } else if (!spec.startsWith("node:")) {
      packages.add(spec.split("/")[0]);
    }
  };
  for (const m of src.matchAll(/require\(\s*['"]([^'"]+)['"]\s*\)/g)) addSpec(m[1]);
  for (const m of src.matchAll(/import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/g)) addSpec(m[1]);
  for (const m of src.matchAll(/import\(\s*['"]([^'"]+)['"]\s*\)/g)) addSpec(m[1]);

  const exports = new Set();
  for (const m of src.matchAll(/module\.exports\s*=\s*\{([^}]*)\}/g)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/[:\s]/)[0];
      if (name) exports.add(name);
    }
  }
  for (const m of src.matchAll(/(?:^|\n)\s*(?:exports\.([\w$]+)|function\s+([\w$]+)|(?:const|let|var)\s+([\w$]+)\s*=)/g)) {
    exports.add(m[1] || m[2] || m[3]);
  }
  return { imports: [...imports].sort(), exports: [...exports].sort(), packages: [...packages].sort() };
}

function main() {
  const root = path.resolve(process.argv[2] || ".");
  const files = walk(root, []);
  const out = {};
  for (const abs of files) {
    out[path.relative(root, abs).replace(/\\/g, "/")] = analyzeFile(abs, root);
  }
  process.stdout.write(JSON.stringify({ files: out }, null, 2) + "\n");
}

main();
