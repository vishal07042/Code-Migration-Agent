/**
 * Pure string helpers (eval corpus).
 */

/**
 * @param {string} s
 */
function capitalize(s) {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * @param {string} s
 * @param {number} n
 */
function repeat(s, n) {
  if (!Number.isInteger(n) || n < 0) throw new Error("repeat: non-negative integer expected");
  return s.repeat(n);
}

/**
 * @param {string} s
 */
function words(s) {
  const t = s.trim();
  if (t === "") return [];
  return t.split(/\s+/);
}

module.exports = { capitalize, repeat, words };
