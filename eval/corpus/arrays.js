/**
 * Pure array helpers (eval corpus). Note: default sort is lexicographic,
 * so numeric sorts always pass an explicit comparator (trap #4).
 */

/**
 * Dedupe preserving first-seen order (JS Set: SameValueZero).
 * @param {Array} xs
 */
function unique(xs) {
  return [...new Set(xs)];
}

/**
 * @param {Array} xs
 */
function sortedNumeric(xs) {
  return [...xs].sort((a, b) => a - b);
}

/**
 * @param {Array} xs
 */
function flattenOnce(xs) {
  return xs.flat();
}

module.exports = { unique, sortedNumeric, flattenOnce };
