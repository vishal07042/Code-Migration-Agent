"use strict";

/**
 * Tagged JSON: encodes values JSON can't represent.
 * Tags (single-key objects):
 *   {"$undefined":1}  undefined
 *   {"$nan":1}        NaN
 *   {"$inf":1}        Infinity
 *   {"$neginf":1}     -Infinity
 *   {"$negzero":1}    -0  (spec lists -0 as round-trip requirement)
 *   {"$bigint":".."}  BigInt (decimal string)
 *   {"$date":"..."}   Date (ISO string)
 */

function isTaggedObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v) && !(v instanceof Date);
}

function encodeValue(v) {
  if (v === undefined) return { $undefined: 1 };
  if (typeof v === "number") {
    if (Number.isNaN(v)) return { $nan: 1 };
    if (v === Infinity) return { $inf: 1 };
    if (v === -Infinity) return { $neginf: 1 };
    if (Object.is(v, -0)) return { $negzero: 1 };
    return v;
  }
  if (typeof v === "bigint") return { $bigint: v.toString() };
  if (v instanceof Date) return { $date: v.toISOString() };
  if (Array.isArray(v)) {
    // Preserve holes as undefined markers (dense encoding).
    const out = new Array(v.length);
    for (let i = 0; i < v.length; i++) {
      out[i] = i in v ? encodeValue(v[i]) : { $undefined: 1 };
    }
    return out;
  }
  if (isTaggedObject(v)) {
    const keys = Object.keys(v);
    // A user object that collides with a tag shape: escape it.
    if (keys.length === 1 && keys[0].startsWith("$")) {
      const k = keys[0];
      if (
        ["$undefined", "$nan", "$inf", "$neginf", "$negzero", "$bigint", "$date"].includes(k)
      ) {
        return { $escaped: encodeValue(v[k]) };
      }
    }
    const out = {};
    for (const k of keys) out[k] = encodeValue(v[k]);
    return out;
  }
  return v;
}

function decodeValue(v) {
  if (Array.isArray(v)) return v.map(decodeValue);
  if (v !== null && typeof v === "object" && !(v instanceof Date)) {
    const keys = Object.keys(v);
    if (keys.length === 1) {
      const k = keys[0];
      if (k === "$undefined") return undefined;
      if (k === "$nan") return NaN;
      if (k === "$inf") return Infinity;
      if (k === "$neginf") return -Infinity;
      if (k === "$negzero") return -0;
      if (k === "$bigint") return BigInt(v[k]);
      if (k === "$date") return new Date(v[k]);
      if (k === "$escaped") return { [k]: decodeValue(v[k]) };
    }
    const out = {};
    for (const k of keys) out[k] = decodeValue(v[k]);
    return out;
  }
  return v;
}

function encode(obj) {
  return JSON.stringify(encodeValue(obj));
}

function decode(text) {
  if (text === undefined || text === null || text === "") return decodeValue(null);
  return decodeValue(JSON.parse(text));
}

module.exports = { encode, decode, encodeValue, decodeValue };
